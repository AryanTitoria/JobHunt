"""Search discovers URLs/boards, never treats snippets as verified postings."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

from .fetch import Job, strip_html
from .http import HTTPClient, FetchError, public_url
from .identity import canonical_url
from .prefilter import _parse_date

ATS_HOSTS = {"boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
             "jobs.lever.co": "lever", "jobs.ashbyhq.com": "ashby",
             "careers.smartrecruiters.com": "smartrecruiters", "jobs.smartrecruiters.com": "smartrecruiters"}
RESTRICTED = {"linkedin.com", "indeed.com", "naukri.com", "glassdoor.com"}


@dataclass
class Board:
    ats: str
    slug: str
    name: str = ""

    @property
    def key(self):
        return f"{self.ats}:{self.slug}"

    def to_dict(self):
        return asdict(self)


def board_from_url(url: str) -> Board | None:
    try:
        p = urlsplit(public_url(url))
    except FetchError:
        return None
    ats = ATS_HOSTS.get((p.hostname or "").lower())
    if (p.hostname or "").endswith(".recruitee.com"):
        slug = p.hostname.split(".")[0]
        if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,119}", slug):
            return Board("recruitee", slug, slug.replace("-", " ").title())
    parts = p.path.strip("/").split("/")
    slug = unquote(parts[0]) if parts else ""
    if ats and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", slug) and slug not in {"embed", "api"}:
        return Board(ats, slug, slug.replace("-", " ").title())
    return None


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.blocks, self.links = [], []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("type", "").lower().split(";")[0] == "application/ld+json":
            self.current = []
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.blocks.append("".join(self.current))
            self.current = None


def _objects(value):
    if isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, dict):
        kind = value.get("@type", [])
        if "JobPosting" in ([kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []):
            yield value
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in value:
                yield from _objects(value[key])


def _names(value):
    if isinstance(value, list):
        return ", ".join(filter(None, (_names(v) for v in value)))
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return str(value or "")


def parse_page(url: str, text: str) -> tuple[list[Job], list[Board]]:
    parser = PageParser()
    parser.feed(text)
    boards = {b.key: b for link in parser.links if (b := board_from_url(urljoin(url, link)))}
    jobs = []
    for block in parser.blocks:
        try:
            payload = json.loads(block)
        except (ValueError, TypeError):
            continue
        for j in _objects(payload):
            title = strip_html(str(j.get("title") or ""))
            description = strip_html(str(j.get("description") or ""))
            company = _names(j.get("hiringOrganization"))
            if not title or not description or not company:
                continue
            expires = _parse_date(str(j.get("validThrough") or ""))
            if expires and expires < datetime.now(timezone.utc):
                continue
            locations = j.get("jobLocation") or []
            if isinstance(locations, dict):
                locations = [locations]
            locs = []
            for loc in locations if isinstance(locations, list) else []:
                address = loc.get("address", {}) if isinstance(loc, dict) else {}
                if isinstance(address, str):
                    locs.append(address)
                elif isinstance(address, dict):
                    locs.append(", ".join(filter(None, (_names(address.get(k)) for k in
                                                     ("addressLocality", "addressRegion", "addressCountry")))))
            remote = j.get("jobLocationType") == "TELECOMMUTE"
            requirements = _names(j.get("applicantLocationRequirements"))
            location = "; ".join(filter(None, locs))
            if remote:
                location = f"Remote ({requirements or location or 'eligibility not stated'})"
            try:
                target = canonical_url(urljoin(url, str(j.get("url") or url)))
            except FetchError:
                continue
            # Retain location restrictions; 'remote' does not imply worldwide.
            jobs.append(Job(job_id="jsonld:" + target, ats="jsonld", company=company,
                            title=title, location=location, url=target, description=description,
                            posted_at=j.get("datePosted"), valid_through=j.get("validThrough"),
                            remote=remote))
    return jobs, list(boards.values())


def search_queries(profile: dict, cfg: dict) -> list[str]:
    custom = cfg.get("queries")
    if custom:
        return list(dict.fromkeys(str(q) for q in custom if str(q).strip()))
    titles = cfg.get("titles") or profile.get("target_titles") or ["software engineer"]
    location = cfg.get("location", "India")
    stage = 'fresher entry level graduate' if cfg.get('years_experience', 0) == 0 else f"{cfg['years_experience']} years experience"
    mode = {'remote': 'remote', 'onsite': 'on-site', 'hybrid': 'hybrid'}.get(cfg.get('work_arrangement'), '')
    opportunity = 'internship students' if cfg.get('opportunity_type') == 'internships' else 'jobs'
    queries = [f'"{titles[0]}" "{location}" {stage} {mode} {opportunity} careers']
    if cfg.get('search_scope')=='combined':
        queries.extend(f'"{title}" "{location}" {stage} {mode} {opportunity} careers' for title in cfg.get('targeted_titles', [])[:2])
    field = cfg.get('field_of_study') or profile.get('field_of_study')
    if field and cfg.get('include_internships', True) and cfg.get('opportunity_type') != 'jobs':
        queries.append(f'"{field}" internship "{location}" students careers')
        if cfg.get('allow_remote', True) and cfg.get('work_arrangement', 'any') in {'any', 'remote'}:
            queries.append(f'"{field}" remote internship India worldwide students')
    hosts = ("job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com",
             "careers.smartrecruiters.com", "recruitee.com")
    queries.extend(f'"{title}" "{location}" {stage} {mode} {opportunity} site:{host}' for title in titles[:5] for host in hosts)
    if field and cfg.get('include_internships', True) and cfg.get('opportunity_type') != 'jobs':
        queries.extend(f'"{field}" internship "{location}" site:{host}' for host in hosts)
    for host in cfg.get('career_domains', []):
        queries.append(f'"{location}" {stage} {mode} {opportunity} site:{host}')
        if field and cfg.get('include_internships', True) and cfg.get('opportunity_type') != 'jobs':
            queries.append(f'"{field}" internship "{location}" site:{host}')
    return list(dict.fromkeys(queries))


def discover(client: HTTPClient, profile: dict, cfg: dict, cursor: int = 0):
    boards, pages, errors = {}, [], []
    urls = list(cfg.get("seed_urls") or [])
    queries = search_queries(profile, cfg)
    budget = int(cfg.get("max_queries", 4))
    from .search import configured_search_providers, search_urls
    providers = configured_search_providers()
    count = 0
    reserve = cfg.get('reserve_search')
    if cfg.get('enabled', True) and providers:
        for i in range(min(budget, len(queries))):
            index = cursor + i
            provider = providers[index % len(providers)]
            query = queries[index % len(queries)]
            count += 1
            if reserve is not None and not reserve(provider):
                errors.append(f'search: {provider} monthly application allowance reached')
                continue
            try:
                urls.extend(search_urls(client, provider, query, index // len(queries)))
            except FetchError as error:
                errors.append(f'search: {provider}: {error}')
    elif cfg.get('enabled', True):
        errors.append('No Tavily or Brave key configured: web search skipped; public job APIs still work')
    for url in dict.fromkeys(urls):
        try:
            public_url(url)
        except FetchError:
            continue
        board = board_from_url(url)
        if board:
            boards[board.key] = board
            continue
        host = (urlsplit(url).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in RESTRICTED):
            continue
        if cfg.get("fetch_pages", True) and len(pages) < int(cfg.get("max_pages", 10)):
            pages.append(url)
    return list(boards.values()), pages, errors, cursor + count
