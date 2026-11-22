"""Bounded, rate-limited public HTTP. Discovery never follows private URLs."""
from __future__ import annotations

import ipaddress
import socket
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "JobSearch/1.0 (public job discovery platform)"


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def public_url(url: str, resolve: bool = False) -> str:
    try:
        p = urlsplit(url)
        if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
            raise ValueError()
        if p.port not in {None, 80, 443}:
            raise ValueError()
        host = p.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError()
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            addresses = ([ipaddress.ip_address(a[4][0]) for a in
                          socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                             type=socket.SOCK_STREAM)] if resolve else [])
        if any(not a.is_global for a in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise FetchError("invalid or non-public URL") from None
    return url


class HTTPClient:
    def __init__(self, timeout: float = 20, retries: int = 2, delay: float = 1.0,
                 max_bytes: int = 8_000_000):
        self.session = requests.Session()
        self.session.trust_env = False
        self.timeout, self.retries, self.delay = timeout, retries, delay
        self.max_bytes = max_bytes
        self.last: dict[str, float] = {}
        self.robots: dict[str, RobotFileParser] = {}
        self.requests = 0

    def close(self):
        self.session.close()

    def get(self, url: str, *, params=None, headers=None, retries=None, follow_redirects=True):
        original_host = urlsplit(url).netloc
        retry_count = self.retries if retries is None else retries
        for redirect in range(6):
            public_url(url, resolve=True)
            host = urlsplit(url).netloc
            if headers and urlsplit(url).scheme != "https":
                raise FetchError("authenticated requests require HTTPS")
            for attempt in range(retry_count + 1):
                time.sleep(max(0, self.delay - (time.monotonic() - self.last.get(host, 0))))
                self.last[host] = time.monotonic()
                self.requests += 1
                try:
                    # Credentials belong only to the original API host.
                    h = {"User-Agent": USER_AGENT, **(headers or {} if host == original_host else {})}
                    r = self.session.get(url, params=params, headers=h, timeout=self.timeout,
                                         allow_redirects=False, stream=True)
                    try:
                        chunks, size = [], 0
                        for chunk in r.iter_content(65536):
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise FetchError("response exceeds size limit")
                            chunks.append(chunk)
                        r._content = b"".join(chunks)
                    finally:
                        r.close()
                except requests.RequestException:
                    if attempt == retry_count:
                        raise FetchError("network request failed") from None
                    time.sleep(2 ** attempt)
                    continue
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    if attempt == retry_count:
                        raise FetchError(f"HTTP {r.status_code}", r.status_code)
                    wait = 2 ** attempt
                    value = r.headers.get("Retry-After")
                    if value:
                        try:
                            wait = float(value)
                        except ValueError:
                            try:
                                wait = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
                            except (ValueError, TypeError):
                                pass
                    if wait > 30:
                        raise FetchError("source requested a longer cooldown; retry on next run", r.status_code)
                    time.sleep(max(0, wait))
                    continue
                break
            if r.status_code in {301, 302, 303, 307, 308}:
                if not follow_redirects:
                    return r
                url = urljoin(url, r.headers.get("Location", ""))
                params = None
                continue
            if r.status_code >= 400:
                raise FetchError(f"HTTP {r.status_code}", r.status_code)
            return r
        raise FetchError("too many redirects")

    def json(self, url: str, **kwargs):
        try:
            return self.get(url, **kwargs).json()
        except requests.exceptions.JSONDecodeError:
            raise FetchError("source returned invalid JSON") from None

    def post_json(self, url: str, *, body, headers=None):
        """Paid/quota-counted search requests are attempted once, never redirected."""
        public_url(url, resolve=True)
        if urlsplit(url).scheme != 'https':
            raise FetchError('authenticated requests require HTTPS')
        host = urlsplit(url).netloc
        time.sleep(max(0, self.delay - (time.monotonic() - self.last.get(host, 0))))
        self.last[host] = time.monotonic()
        self.requests += 1
        try:
            response = self.session.post(url, json=body, headers={'User-Agent': USER_AGENT, **(headers or {})},
                                         timeout=self.timeout, allow_redirects=False, stream=True)
            try:
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise FetchError('response exceeds size limit')
                    chunks.append(chunk)
                response._content = b''.join(chunks)
            finally:
                response.close()
            if response.status_code != 200:
                raise FetchError(f'HTTP {response.status_code}', response.status_code)
            return response.json()
        except requests.RequestException:
            raise FetchError('search request failed') from None

    def _page_once(self, url: str):
        p = urlsplit(public_url(url))
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            robot = RobotFileParser()
            try:
                text = self.get(origin + "/robots.txt").text
            except FetchError as e:
                if e.status == 404:
                    text = "User-agent: *\nAllow: /"
                else:
                    raise FetchError("robots.txt unavailable or access denied") from None
            robot.parse(text.splitlines())
            self.robots[origin] = robot
        robot = self.robots[origin]
        if not robot.can_fetch(USER_AGENT, url):
            raise FetchError("robots.txt disallows this page")
        crawl_delay = robot.crawl_delay(USER_AGENT) or robot.crawl_delay("*") or 0
        if crawl_delay > 30:
            raise FetchError("robots.txt crawl delay exceeds this run's budget")
        host = p.netloc
        time.sleep(max(0, crawl_delay - (time.monotonic() - self.last.get(host, 0))))
        return self.get(url, follow_redirects=False)

    def page(self, url: str) -> str:
        # Each redirect must pass that destination's own robots policy.
        for _ in range(6):
            r = self._page_once(url)
            if r.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, r.headers.get("Location", ""))
                continue
            break
        else:
            raise FetchError("too many page redirects")
        content_type = r.headers.get("Content-Type", "").lower()
        if content_type and not any(t in content_type for t in ("text/html", "application/xhtml")):
            raise FetchError("not an HTML page")
        return r.text
