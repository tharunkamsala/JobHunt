"""TalentBrew search-page scraper.

Many TalentBrew sites render paginated search result cards server-side on
``/search-jobs`` pages. We follow those pages directly and derive a stable
title from the job URL slug instead of the noisy mixed card text.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
_CITY_STATE_RE = re.compile(r"\b([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})\b")


def _normalize_search_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    if not path.endswith("/search-jobs") and path.rstrip("/") == "":
        path = "/search-jobs"
    query = parse_qs(parsed.query, keep_blank_values=True)
    query.pop("p", None)
    return urlunparse(parsed._replace(path=path, query=urlencode(query, doseq=True)))


def _page_url(base_url: str, page_num: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page_num > 1:
        query["p"] = [str(page_num)]
    else:
        query.pop("p", None)
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _posting_id(href: str) -> str | None:
    path = urlparse(href).path
    m = re.search(r"/(\d{5,20})(?:/)?$", path)
    return m.group(1) if m else None


def _title_from_href(href: str) -> str | None:
    parts = [p for p in urlparse(href).path.split("/") if p]
    try:
        idx = parts.index("job")
    except ValueError:
        return None
    if idx + 2 >= len(parts):
        return None
    slug = parts[idx + 2].replace("-", " ").strip()
    slug = re.sub(r"\s+", " ", slug)
    return slug.title()[:220] if slug else None


def _location_from_card(card_text: str, href: str) -> str | None:
    text = re.sub(r"\s+", " ", card_text or "").strip()
    m = _CITY_STATE_RE.search(text)
    if m:
        return m.group(1)
    parts = [p for p in urlparse(href).path.split("/") if p]
    try:
        idx = parts.index("job")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    city = parts[idx + 1].replace("-", " ").strip()
    return city.title() if city else None


def _extract_jobs_from_page(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        if "/job/" not in urlparse(href).path:
            continue
        pid = _posting_id(href) or href
        if pid in seen:
            continue
        title = _title_from_href(href)
        if not title:
            continue
        seen.add(pid)
        card = a.find_parent(["li", "article", "div"]) or a
        card_text = card.get_text(" ", strip=True) if card else a.get_text(" ", strip=True)
        jobs.append({
            "title": title,
            "location": _location_from_card(card_text, href),
            "url": href,
            "posting_id": pid if pid != href else None,
            "posted_at": None,
        })
    return jobs


def _total_pages(soup: BeautifulSoup) -> int:
    section = soup.find(id="search-results")
    if not section:
        return 1
    raw = section.get("data-total-pages") or "1"
    try:
        return max(1, min(int(raw), 25))
    except Exception:
        return 1


def fetch(url: str) -> list[dict]:
    base_url = _normalize_search_url(url)
    jobs: list[dict] = []
    seen: set[str] = set()

    first_url = _page_url(base_url, 1)
    try:
        r = transport_fetch(
            first_url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            strategy=FetchStrategy.REQUESTS,
        )
    except Exception:
        return []
    if r.status_code != 200 or not r.text:
        return []

    first_soup = BeautifulSoup(r.text, "lxml")
    total_pages = _total_pages(first_soup)

    for page_num in range(1, total_pages + 1):
        current_url = r.url if page_num == 1 else _page_url(base_url, page_num)
        current_html = r.text if page_num == 1 else None
        if current_html is None:
            try:
                page_resp = transport_fetch(
                    current_url,
                    headers=HEADERS,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True,
                    strategy=FetchStrategy.REQUESTS,
                )
            except Exception:
                break
            if page_resp.status_code != 200 or not page_resp.text:
                break
            current_html = page_resp.text
            current_url = page_resp.url
        page_jobs = _extract_jobs_from_page(current_html, current_url)
        if not page_jobs:
            break
        new_on_page = 0
        for job in page_jobs:
            pid = job.get("posting_id") or job["url"]
            if pid in seen:
                continue
            seen.add(pid)
            jobs.append(job)
            new_on_page += 1
        if new_on_page == 0:
            break
    return jobs
