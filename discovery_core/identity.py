"""Conservative cross-source identity; never merge by title alone."""
import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .http import public_url


def canonical_url(url: str) -> str:
    p = urlsplit(public_url(url))
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in
             {"ref", "source", "gh_src", "lever-source", "trackingid"}]
    host = p.netloc.lower()
    host = host.removesuffix(":443") if p.scheme == "https" else host.removesuffix(":80")
    # The two Greenhouse board hosts are aliases for the same posting.
    if host == "boards.greenhouse.io":
        host = "job-boards.greenhouse.io"
    return urlunsplit((p.scheme.lower(), host, p.path.rstrip("/") or "/",
                       urlencode(sorted(query)), ""))


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def fingerprint(job) -> str | None:
    desc = normalized(job.description)
    if len(desc) < 120 or not job.company or not job.location:
        return None
    body = "|".join(normalized(s) for s in (job.company, job.title, job.location, desc))
    return hashlib.sha256(body.encode()).hexdigest()


def content_hash(job) -> str:
    body = "|".join(normalized(s or "") for s in
                    (job.title, job.company, job.location, job.description, job.salary))
    return hashlib.sha256(body.encode()).hexdigest()
