"""Workday tenants expose a JSON search endpoint at
   {base}/wday/cxs/{tenant}/{site}/jobs (POST).
   We derive those from the public careers URL.
"""
import json
import re
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Mapping
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT


# Workday's public CXS endpoint caps each page at 20. We parallelize the
# pagination across this many threads to cut wall-clock by ~Nx for large
# tenants (NVIDIA: ~30s → ~5s with 8 workers).
_WORKDAY_PAGE_LIMIT = 20
_WORKDAY_PAGE_WORKERS = 8
_WORKDAY_MAX_OFFSET = 4000


log = logging.getLogger(__name__)
_HTML_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
_JSON_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _location_from_external_path(ext: str | None) -> str | None:
    """Workday list payloads often use locationsText='2 Locations' with no
    `locations` array. The job URL still embeds a primary site slug:
    /job/US-CA-Santa-Clara/... or /job/China-Beijing/..."""
    if not isinstance(ext, str) or not ext.strip():
        return None
    m = re.search(r"/job/([^/]+)/", ext)
    if not m:
        return None
    slug = m.group(1)
    m_us = re.match(r"^US-([A-Z]{2})-(.+)$", slug, re.I)
    if m_us:
        st = m_us.group(1).upper()
        city = re.sub(r"-", " ", m_us.group(2)).strip()
        return f"US, {st}, {city}"
    parts = slug.split("-")
    if len(parts) >= 2:
        country = parts[0]
        city = " ".join(parts[1:]).replace("-", " ")
        return f"{country}, {city}"
    return None


def _is_vague_locations_text(s: str) -> bool:
    low = s.strip().lower()
    if re.fullmatch(r"\d+\s+locations?", low):
        return True
    return low in {
        "multiple locations",
        "various locations",
        "various",
        "varies",
        "multiple us locations",
        "multiple cities",
        "multiple offices",
    }


def _multi_location_count(locations_text: str | None) -> int | None:
    if not isinstance(locations_text, str):
        return None
    m = re.fullmatch(r"(\d+)\s+locations?", locations_text.strip(), re.I)
    if m:
        return int(m.group(1))
    return None


def _parse_workday_posted(raw: str | None) -> str | None:
    """Workday returns strings like 'Posted Today', 'Posted Yesterday',
       'Posted 3 Days Ago', 'Posted 30+ Days Ago'. Convert to ISO8601 UTC."""
    if not raw:
        return None
    s = raw.lower().strip()
    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    if "today" in s:
        return now.isoformat(timespec="seconds")
    if "yesterday" in s:
        return (now - timedelta(days=1)).isoformat(timespec="seconds")
    m = re.search(r"(\d+)\+?\s*day", s)
    if m:
        return (now - timedelta(days=int(m.group(1)))).isoformat(timespec="seconds")
    m = re.search(r"(\d+)\+?\s*hour", s)
    if m:
        return (now - timedelta(hours=int(m.group(1)))).isoformat(timespec="seconds")
    m = re.search(r"(\d+)\+?\s*minute", s)
    if m:
        return (now - timedelta(minutes=int(m.group(1)))).isoformat(timespec="seconds")
    return None


def _extract_location(j: Mapping[str, Any]) -> str | None:
    arr = j.get("locations")
    if isinstance(arr, list) and arr:
        parts: list[str] = []
        for item in arr:
            if isinstance(item, Mapping):
                txt = item.get("display") or item.get("name") or item.get("location")
                if isinstance(txt, str) and txt.strip():
                    parts.append(txt.strip())
        if parts:
            return ", ".join(parts)

    loc_raw = j.get("locationsText")
    loc_text = loc_raw.strip() if isinstance(loc_raw, str) else ""
    ext = j.get("externalPath")
    from_path = _location_from_external_path(ext if isinstance(ext, str) else "")

    if loc_text and not _is_vague_locations_text(loc_text):
        return loc_text
    if from_path:
        n = _multi_location_count(loc_raw if loc_text else None)
        if n is not None and n > 1:
            return f"{from_path} (+{n - 1} more)"
        return from_path
    if loc_text:
        return loc_text

    bullets = j.get("bulletFields")
    if isinstance(bullets, list) and bullets:
        first = bullets[0]
        if isinstance(first, str) and first.strip():
            return first.strip()
    return None


def _workday_posting_id(j: Mapping[str, Any], ext: str) -> str | None:
    for k in ("jobPostingId", "id"):
        v = j.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()[:200]
    if ext:
        m = re.search(r"/job/[^/]*/([^\s$?#]+)", ext)
        if m:
            return m.group(1).strip()[:200]
    return None


def _job_from_workday_node(j: Mapping[str, Any], base: str | None = None) -> dict | None:
    title = j.get("title")
    if not isinstance(title, str) or not title.strip():
        return None
    ext = j.get("externalPath", "")
    url = None
    if isinstance(ext, str) and ext.strip():
        url = ext.strip()
        if base and not re.match(r"^https?://", url, re.I):
            url = f"{base}{url}"
    return {
        "title": title.strip(),
        "location": _extract_location(j),
        "url": url,
        "posting_id": _workday_posting_id(j, ext if isinstance(ext, str) else ""),
        "posted_at": _parse_workday_posted(j.get("postedOn") or j.get("postedOnDate")),
    }


def _script_json_blobs(html: str) -> list[Any]:
    decoder = json.JSONDecoder()
    blobs: list[Any] = []
    for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, re.I | re.S):
        script = (m.group(1) or "").strip()
        if not script:
            continue
        for jp in re.finditer(r"JSON\.parse\(\s*([\"'])(.*?)\1\s*\)", script, re.S):
            try:
                escaped = jp.group(2).encode("utf-8").decode("unicode_escape")
                blobs.append(json.loads(escaped))
            except Exception:
                pass
        starts = [i for i, ch in enumerate(script) if ch in "[{"]
        for start in starts:
            try:
                obj, _end = decoder.raw_decode(script[start:])
            except Exception:
                continue
            blobs.append(obj)
            break
    return blobs


def _walk_for_postings(node: Any, out: list[Mapping[str, Any]]) -> None:
    if isinstance(node, Mapping):
        keys = set(node.keys())
        if "title" in keys and (
            "locationsText" in keys or
            "locations" in keys or
            "bulletFields" in keys or
            "externalPath" in keys or
            "jobPostingId" in keys or
            "postedOn" in keys or
            "postedOnDate" in keys
        ):
            out.append(node)
        for v in node.values():
            _walk_for_postings(v, out)
        return
    if isinstance(node, list):
        for item in node:
            _walk_for_postings(item, out)


def _html_fallback_jobs(url: str, base: str | None = None) -> list[dict]:
    try:
        r = requests.get(
            url,
            headers=_HTML_HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
    except Exception:
        return []
    if r.status_code != 200 or not r.text:
        return []

    postings: list[Mapping[str, Any]] = []
    for blob in _script_json_blobs(r.text):
        _walk_for_postings(blob, postings)

    jobs: list[dict] = []
    seen: set[tuple[str, str, str | None, str | None]] = set()
    for node in postings:
        job = _job_from_workday_node(node, base=base)
        if not job:
            continue
        key = (
            job["title"].lower(),
            (job.get("location") or "").lower(),
            job.get("url"),
            job.get("posting_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        jobs.append(job)
    jobs.extend(_anchor_fallback_jobs(r.text, url, base=base, seen=seen))
    return jobs


def _anchor_fallback_jobs(html: str, page_url: str, base: str | None = None,
                          seen: set[tuple[str, str, str | None, str | None]] | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen = seen or set()
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if "/job/" not in href:
            continue
        text = " ".join(
            x.strip() for x in [
                a.get_text(" ", strip=True),
                a.get("aria-label"),
                a.get("title"),
                a.get("data-automation-id"),
            ] if isinstance(x, str) and x.strip()
        ).strip()
        title = re.sub(r"\s+", " ", text).strip()
        if not title or len(title) < 4:
            continue
        full = href
        if not re.match(r"^https?://", full, re.I):
            anchor_base = base or re.match(r"^(https?://[^/]+)", page_url).group(1)
            full = f"{anchor_base}{full if href.startswith('/') else '/' + href}"
        card_text = a.parent.get_text(" ", strip=True) if a.parent else ""
        loc = None
        m = re.search(
            r"(Remote[^|,;]*|[A-Z][A-Za-z .'-]+,\s*[A-Z]{2}|[A-Z][A-Za-z .'-]+,\s*United States)",
            card_text,
        )
        if m:
            loc = m.group(1).strip()
        job = {
            "title": title[:220],
            "location": loc,
            "url": full,
            "posting_id": _workday_posting_id({}, href),
            "posted_at": None,
        }
        key = (
            job["title"].lower(),
            (job.get("location") or "").lower(),
            job.get("url"),
            job.get("posting_id"),
        )
        if key in seen:
            continue
        seen.add(key)
        jobs.append(job)
    return jobs


def _derive_api(url: str) -> tuple[str, str, str] | None:
    # e.g. https://company.wd5.myworkdayjobs.com/en-US/External
    u = (url or "").strip()
    m = re.match(r"(https?://[^/]+)/([^/]+)/([^/?#]+)", u)
    if not m:
        return None
    base, _lang, site = m.group(1), m.group(2), m.group(3)
    # tenant is the subdomain before first dot (company.wd5.myworkdayjobs.com → company)
    host = re.match(r"https?://([^.]+)\.", base).group(1)
    return base, host, site


def _post_page(api: str, offset: int, limit: int) -> tuple[int, list[Mapping[str, Any]], int | None]:
    """POST one page. Returns (status, postings, total). Retries on 5xx/timeout."""
    payload = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
    for attempt in range(1, 4):
        try:
            r = requests.post(api, json=payload, headers=_JSON_HEADERS, timeout=REQUEST_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == 3:
                log.warning(f"Workday max retries on {api}@{offset}: {type(e).__name__}")
                return 0, [], None
            time.sleep(2 ** (attempt - 1))
            continue
        if r.status_code < 500:
            break
        if attempt == 3:
            return r.status_code, [], None
        time.sleep(2 ** (attempt - 1))

    if r.status_code != 200:
        return r.status_code, [], None
    try:
        data = r.json()
    except Exception:
        return r.status_code, [], None
    postings = data.get("jobPostings") or []
    if not isinstance(postings, list):
        postings = []
    total_raw = data.get("total")
    try:
        total = int(total_raw) if total_raw is not None else None
    except Exception:
        total = None
    return r.status_code, postings, total


def fetch(url: str) -> list[dict]:
    parts = _derive_api(url)
    if not parts:
        return _html_fallback_jobs(url)
    base, tenant, site = parts
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    # Probe page 0 first so we learn `total` and know how many parallel
    # follow-up pages to issue.
    status, first_postings, total = _post_page(api, 0, _WORKDAY_PAGE_LIMIT)
    if status != 200:
        return _html_fallback_jobs(url, base=base)

    raw_pages: dict[int, list[Mapping[str, Any]]] = {0: first_postings}

    # Build the list of additional offsets we still need to fetch.
    if total is None or total <= 0:
        total_for_planning = _WORKDAY_MAX_OFFSET
    else:
        total_for_planning = min(total, _WORKDAY_MAX_OFFSET)
    next_offsets = list(range(_WORKDAY_PAGE_LIMIT, total_for_planning, _WORKDAY_PAGE_LIMIT))

    if next_offsets:
        with ThreadPoolExecutor(max_workers=_WORKDAY_PAGE_WORKERS) as pool:
            futures = {pool.submit(_post_page, api, off, _WORKDAY_PAGE_LIMIT): off for off in next_offsets}
            saw_empty_after: int | None = None
            for fut in as_completed(futures):
                off = futures[fut]
                try:
                    s, postings, _ = fut.result()
                except Exception:
                    continue
                if s != 200 or not postings:
                    # When `total` was unknown we use the first empty page
                    # to bound future work — but we still process whatever
                    # parallel calls have already returned non-empty pages.
                    if total is None or total <= 0:
                        saw_empty_after = off if saw_empty_after is None else min(saw_empty_after, off)
                    continue
                raw_pages[off] = postings

            # If we discovered the natural end of the list (no `total`),
            # drop pages beyond the first empty one so we don't add stale.
            if saw_empty_after is not None:
                raw_pages = {o: p for o, p in raw_pages.items() if o < saw_empty_after}

    jobs: list[dict] = []
    seen_keys: set[tuple[str, str | None, str | None]] = set()
    for off in sorted(raw_pages.keys()):
        for j in raw_pages[off]:
            job = _job_from_workday_node(j, base=base)
            if not job:
                continue
            key = (job["title"].lower(), job.get("url"), job.get("posting_id"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            jobs.append(job)

    if jobs:
        return jobs
    return _html_fallback_jobs(url, base=base)
