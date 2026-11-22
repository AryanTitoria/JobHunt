"""Source contracts and connectors. A failed fetch is never an empty snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlsplit, urljoin

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError

from .discovery import Board, parse_page, PageParser, board_from_url
import re
from .fetch import ENDPOINTS, Job, strip_html
from .http import HTTPClient, FetchError
from .identity import canonical_url


@dataclass
class SourceResult:
    key: str
    jobs: list[Job] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    authoritative: bool = False
    boards: list[Board] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)


class JobSource(Protocol):
    key: str

    def fetch(self, client: HTTPClient) -> SourceResult: ...


@dataclass
class ATSSource:
    board: Board

    @property
    def key(self):
        return self.board.key

    def fetch(self, client):
        if self.board.ats in {'smartrecruiters', 'recruitee'}:
            from .career_ats import fetch_board
            return fetch_board(self.board, client)
        endpoint, parser = ENDPOINTS[self.board.ats]
        body = client.json(endpoint.format(slug=self.board.slug))
        # Do not close an entire board when a vendor changes its response schema.
        rows = body if self.board.ats == "lever" else body.get("jobs") if isinstance(body, dict) else None
        if not isinstance(rows, list) or any(not isinstance(j, dict) or not j.get("id") for j in rows):
            raise FetchError("unexpected ATS payload; previous snapshot retained")
        jobs = parser(self.board.slug, self.board.name or self.board.slug, body)
        if any(not j.title or not j.url for j in jobs):
            raise FetchError("incomplete ATS payload; previous snapshot retained")
        return SourceResult(self.key, jobs, authoritative=True)


class RemotiveSource:
    key = "feed:remotive"

    def fetch(self, client):
        body = client.json("https://remotive.com/api/remote-jobs", retries=0)
        if not isinstance(body, dict) or not isinstance(body.get("jobs"), list):
            raise FetchError("unexpected Remotive payload")
        jobs = [Job(job_id=f"remotive:{j['id']}", ats="Remotive", company=j["company_name"],
                    title=j["title"], location=f"Remote ({j.get('candidate_required_location') or 'eligibility not stated'})",
                    url=j["url"], description=strip_html(j.get("description")),
                    posted_at=j.get("publication_date"), salary=j.get("salary"), remote=True)
                for j in body["jobs"]]
        return SourceResult(self.key, jobs)


@dataclass
class ArbeitnowSource:
    max_pages: int = 2
    key = "feed:arbeitnow"

    def fetch(self, client):
        jobs = []
        for page in range(1, self.max_pages + 1):
            body = client.json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
            if not isinstance(body, dict) or not isinstance(body.get("data"), list):
                raise FetchError("unexpected Arbeitnow payload")
            for j in body["data"]:
                ts = j.get("created_at")
                date = datetime.fromtimestamp(ts, timezone.utc).isoformat() if isinstance(ts, (int, float)) else None
                location = j.get("location") or ""
                if j.get("remote"):
                    location = f"Remote ({location or 'eligibility not stated'})"
                jobs.append(Job(job_id="arbeitnow:" + j["slug"], ats="Arbeitnow",
                                company=j["company_name"], title=j["title"], location=location,
                                url=j["url"], description=strip_html(j.get("description")),
                                posted_at=date, remote=bool(j.get("remote"))))
            if not (body.get("links") or {}).get("next"):
                break
        # A bounded feed is not a complete inventory, so absence never means closed.
        return SourceResult(self.key, jobs)


@dataclass
class PageSource:
    url: str
    depth: int = 0

    @property
    def key(self):
        return "page:" + canonical_url(self.url)

    def fetch(self, client):
        text = client.page(self.url)
        jobs, boards = parse_page(self.url, text)
        pages = []
        if self.depth < 1:
            parser = PageParser()
            parser.feed(text)
            for link in parser.links:
                target = urljoin(self.url, link)
                if (urlsplit(target).hostname == urlsplit(self.url).hostname and
                    re.search(r'job|career|intern|graduate|student|vacan', urlsplit(target).path, re.I) and
                    not board_from_url(target)):
                    try:
                        target = canonical_url(target)
                    except FetchError:
                        continue
                    if target != canonical_url(self.url) and target not in pages:
                        pages.append(target)
                if len(pages) >= 8:
                    break
        if not jobs and not boards and not pages:
            return SourceResult(self.key, success=False, error='No structured jobs found; this site may require a dedicated connector')
        return SourceResult(self.key, jobs, boards=boards, pages=pages)


@dataclass
class RSSSource:
    url: str
    name: str = "RSS"

    @property
    def key(self):
        return "rss:" + canonical_url(self.url)

    def fetch(self, client):
        root = ElementTree.fromstring(client.get(self.url).content)
        jobs = []
        # RSS and Atom. Never infer a company from a title; use feed attribution.
        for item in root.iter():
            if item.tag.split("}")[-1] not in {"item", "entry"}:
                continue
            values = {child.tag.split("}")[-1]: child for child in item}
            def text(key):
                el = values.get(key)
                return "".join(el.itertext()).strip() if el is not None else ""
            link = values.get("link")
            url = (link.get("href") or text("link")) if link is not None else ""
            if not url:
                continue
            date = text("pubDate") or text("published") or text("updated")
            if date:
                try:
                    date = parsedate_to_datetime(date).isoformat()
                except (ValueError, TypeError):
                    pass
            title = strip_html(text("title"))
            description = strip_html(text("encoded") or text("content") or text("description") or text("summary"))
            if not title or not description:
                continue
            target = canonical_url(url)
            jobs.append(Job(job_id=self.key + ":" + (text("guid") or text("id") or target),
                            ats=self.name, company=text("company") or text("creator") or self.name,
                            title=title, location=text("location"), url=target,
                            description=description, posted_at=date or None))
        return SourceResult(self.key, jobs)


def collect(source: JobSource, client: HTTPClient) -> SourceResult:
    try:
        result = source.fetch(client)
        # Validate the complete snapshot before allowing any closure reconciliation.
        for job in result.jobs:
            if not job.application_url:
                job.application_url = job.url
            if job.application_url:
                from .http import public_url
                public_url(job.application_url)
            job.url = canonical_url(job.url)
            if not job.title or not job.description:
                raise FetchError("source contains incomplete postings")
        return result
    except (FetchError, ValueError, TypeError, KeyError, AttributeError, OverflowError, ParseError, DefusedXmlException) as e:
        return SourceResult(source.key, success=False, error=f"{type(e).__name__}: {e}")
