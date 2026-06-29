"""Dedicated handlers for big-tech career sites that don't use a
standard ATS or hide behind vanity SPAs.

Each function returns a list of raw {title, location, url, posted_at, posting_id?} dicts.
The outer pipeline filters by location/role categories.
"""
from __future__ import annotations

import html as htmlmod
import json as jsonlib
import os
import re
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

from config import (
    PLAYWRIGHT_ENABLED,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_TIMEOUT_MS,
    REQUEST_TIMEOUT,
    USER_AGENT,
)


# Hard wall-clock cap for the isolated Playwright worker subprocess. The
# whole point of running it out-of-process is that we'd rather lose
# Microsoft/Meta on a single sweep than block the entire run, so we cap
# at ~3 minutes per target. Override with $PLAYWRIGHT_WORKER_TIMEOUT.
_WORKER_TIMEOUT_SEC = int(os.environ.get("PLAYWRIGHT_WORKER_TIMEOUT", "180"))


def _run_playwright_worker(target: str) -> list[dict]:
    """Spawn scraper.playwright_worker as a subprocess and return jobs.

    Failures (timeout, non-zero exit, malformed JSON, worker self-reported
    error) all collapse to an empty list — Playwright issues must never
    propagate up and break the outer sweep.
    """
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "scraper.playwright_worker", target]
    env = {**os.environ}
    pw_browsers = repo_root / ".venv" / "playwright-browsers"
    if pw_browsers.exists():
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(pw_browsers)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=_WORKER_TIMEOUT_SEC,
            env=env,
        )
    except subprocess.TimeoutExpired:
        log.warning("Playwright worker (%s) timed out after %ss",
                    target, _WORKER_TIMEOUT_SEC)
        return []
    except Exception as e:
        log.warning("Playwright worker (%s) failed to start: %s: %s",
                    target, type(e).__name__, e)
        return []
    if proc.returncode != 0:
        log.warning("Playwright worker (%s) exited %s; stderr=%s",
                    target, proc.returncode,
                    (proc.stderr or "").strip().splitlines()[-1:] or "")
        return []
    out = (proc.stdout or "").strip()
    if not out:
        return []
    try:
        payload = jsonlib.loads(out)
    except Exception:
        log.warning("Playwright worker (%s) emitted non-JSON output", target)
        return []
    if not payload.get("ok"):
        log.warning("Playwright worker (%s) reported error: %s",
                    target, payload.get("error"))
        return list(payload.get("jobs") or [])
    return list(payload.get("jobs") or [])


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers

HEADERS_HTML = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
    # Avoid brotli because requests doesn't decompress it by default.
    "Accept-Encoding": "gzip, deflate",
}

HEADERS_JSON = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}


def _retry_get(url: str, headers=None, **kw):
    """GET with exponential backoff retry."""
    for attempt in range(1, 4):
        try:
            r = requests.get(url, headers=headers or HEADERS_JSON, timeout=REQUEST_TIMEOUT, **kw)
            if r.status_code < 500:
                return r
            if attempt < 3:
                wait = 2 ** (attempt - 1)
                log.info(f"Retry {attempt}/3 for {url} (status {r.status_code}), waiting {wait}s")
                time.sleep(wait)
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == 3:
                log.warning(f"Max retries for {url}: {type(e).__name__}")
                return None
            wait = 2 ** (attempt - 1)
            log.info(f"Retry {attempt}/3 for {url} ({type(e).__name__}), waiting {wait}s")
            time.sleep(wait)
    return None


def _to_iso(s: str | None) -> str | None:
    """Best-effort convert various date strings to ISO8601 UTC naive."""
    if not s:
        return None
    s = s.strip()
    # Numeric timestamp (seconds or milliseconds)
    if s.isdigit():
        ts = int(s)
        if ts > 10_000_000_000:
            ts //= 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)\
                    .replace(tzinfo=None).isoformat(timespec="seconds")
        except Exception:
            return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y",
    ):
        try:
            return datetime.strptime(s, fmt).isoformat(timespec="seconds")
        except Exception:
            pass
    return None


def _slugify(s: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return slug or "job"


def _playwright_cards(page_url: str, link_selector: str, *, wait_ms: int = 7000) -> list[dict]:
    """Render a JS-heavy careers page and return visible job-card links."""
    if not PLAYWRIGHT_ENABLED:
        return []
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    cards: list[dict] = []
    seen: set[str] = set()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=PLAYWRIGHT_HEADLESS)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            page.goto(page_url, wait_until="domcontentloaded", timeout=PLAYWRIGHT_TIMEOUT_MS)
            try:
                page.wait_for_selector(link_selector, timeout=wait_ms)
            except Exception:
                page.wait_for_timeout(min(wait_ms, 3000))
            for _ in range(4):
                rows = page.eval_on_selector_all(
                    link_selector,
                    """els => els.map(e => ({
                        href: e.href || e.getAttribute('href') || '',
                        text: e.innerText || '',
                        aria: e.getAttribute('aria-label') || ''
                    }))""",
                )
                for row in rows:
                    href = (row.get("href") or "").strip()
                    text = (row.get("text") or "").strip()
                    if not href or href in seen or not text:
                        continue
                    seen.add(href)
                    cards.append({"href": href, "text": text, "aria": row.get("aria") or ""})
                page.mouse.wheel(0, 2800)
                page.wait_for_timeout(1200)
            context.close()
            browser.close()
    except Exception as e:
        # Concise one-liner; we keep the full first line so debugging is
        # easy without dumping a 30-line stack trace per failed query.
        log.warning("Playwright card scrape failed for %s: %s",
                    page_url, f"{type(e).__name__}: {str(e).splitlines()[0]}")
    return cards


# ---------------------------------------------------------------------------
# Amazon — public search JSON API (works great).

def amazon(_: str = "") -> list[dict]:
    out: list[dict] = []
    queries = ["software development engineer", "SDE", "machine learning",
               "data engineer", "new grad", "software engineer intern",
               "SDE intern", "cloud engineer", "systems engineer"]
    seen: set[str] = set()
    for q in queries:
        offset = 0
        for _ in range(4):  # up to 4 pages per query
            params = {
                "base_query": q, "result_limit": 100, "offset": offset,
                "sort": "recent", "normalized_country_code[]": "USA",
            }
            url = f"https://www.amazon.jobs/en/search.json?{urlencode(params, doseq=True)}"
            r = _retry_get(url, headers=HEADERS_JSON)
            if r is None or r.status_code != 200:
                break
            try:
                jobs = r.json().get("jobs", [])
            except Exception:
                break
            if not jobs:
                break
            for j in jobs:
                slug = j.get("job_path") or ""
                if slug in seen:
                    continue
                seen.add(slug)
                pid = j.get("id") or j.get("job_id")
                if pid is None and slug:
                    m = re.search(r"/(\d{3,20})(?:/|$)", str(slug))
                    pid = m.group(1) if m else None
                out.append({
                    "title":    j.get("title"),
                    "location": j.get("normalized_location") or j.get("location"),
                    "url":      f"https://www.amazon.jobs{slug}" if slug else None,
                    "posting_id": str(pid) if pid is not None else None,
                    "posted_at": _to_iso(j.get("posted_date") or j.get("updated_time")),
                })
            offset += 100
    return out


# ---------------------------------------------------------------------------
# Google — SSR HTML scrape (their careers page renders jobs server-side).

_GOOGLE_LI_RE = re.compile(
    r'<li\s[^>]*ssk=[\'"](\d+:\d+)[\'"][^>]*>([\s\S]{50,6000}?)</li>',
    re.I,
)
_GOOGLE_TITLE_RE    = re.compile(r'<h3[^>]*class="QJPWVe"[^>]*>([^<]+)</h3>', re.I)
_GOOGLE_LOCATION_RE = re.compile(r'<span class="r0wTof\s*"[^>]*>([^<]+)</span>', re.I)
_GOOGLE_APPLY_RE    = re.compile(r'href="(/about/careers/applications/jobs/results/\d+[^"?\s]*)', re.I)


def google(_: str = "") -> list[dict]:
    """Google Careers renders its job list server-side. We fetch a handful
    of query/pagination combos and parse out <li> cards."""
    out: list[dict] = []
    seen: set[str] = set()
    base = "https://www.google.com/about/careers/applications/jobs/results/"

    queries = ["software engineer", "machine learning", "data engineer", "new grad"]
    for q in queries:
        for page in range(1, 6):  # 6 pages × 20 per page = ~120 per query
            url = f"{base}?{urlencode({'q': q, 'page': page, 'location': 'United States'})}"
            r = _retry_get(url, headers=HEADERS_HTML)
            if r is None or r.status_code != 200:
                break
            cards = _GOOGLE_LI_RE.findall(r.text)
            if not cards:
                break
            added_this_page = 0
            for ssk, body in cards:
                if ssk in seen:
                    continue
                seen.add(ssk)
                title_m = _GOOGLE_TITLE_RE.search(body)
                loc_m   = _GOOGLE_LOCATION_RE.search(body)
                link_m  = _GOOGLE_APPLY_RE.search(body)
                title = htmlmod.unescape(title_m.group(1)).strip() if title_m else None
                if not title:
                    continue
                location = htmlmod.unescape(loc_m.group(1)).strip() if loc_m else None
                google_id = ssk.split(":")[-1]
                link = urljoin("https://www.google.com", link_m.group(1)) if link_m \
                        else urljoin(base, f"{google_id}-{_slugify(title)}")
                gid: str | None = None
                if link_m:
                    m2 = re.search(r"/(\d{4,20})", link_m.group(1))
                    if m2:
                        gid = m2.group(1)
                if not gid:
                    gid = google_id or ssk.replace(":", "-")
                out.append({
                    "title": title, "location": location, "url": link,
                    "posting_id": gid,
                    "posted_at": None,
                })
                added_this_page += 1
            if added_this_page == 0:
                break
    return out


# ---------------------------------------------------------------------------
# Apple — SSR HTML scrape from jobs.apple.com/en-us/search.

_APPLE_DETAIL_RE = re.compile(
    r'<a\s+class="link-inline[^"]*"\s+aria-label="[^"]+"\s+href="(/en-us/details/(\d+-\d+)/[^"?]+[^"]*)"[^>]*>'
    r'([^<]+)</a>',
    re.I,
)
_APPLE_TEAM_RE = re.compile(r'<span[^>]+class="team-name[^"]*"[^>]*>([^<]+)</span>', re.I)
_APPLE_POSTED_RE = re.compile(r'<span class="job-posted-date"[^>]*>([^<]+)</span>', re.I)
_APPLE_LOC_RE = re.compile(r'<span class="table-col-location[^"]*"[^>]*>\s*([^<]+)', re.I)


def apple(_: str = "") -> list[dict]:
    """Scrape Apple careers search pages. Their SSR HTML contains anchors
    of the form ``/en-us/details/<reqid>-<team>/<slug>``."""
    out: list[dict] = []
    seen: set[str] = set()

    queries = ["software+engineer", "machine+learning", "data+engineer", "new+grad"]
    for q in queries:
        for page in range(1, 11):  # Apple caps at ~40/page, 10 pages = 400 per query
            url = (
                f"https://jobs.apple.com/en-us/search?"
                f"sort=newest&key={q}&location=united-states-USA&page={page}"
            )
            r = _retry_get(url, headers=HEADERS_HTML)
            if r is None or r.status_code != 200:
                break
            hits = _APPLE_DETAIL_RE.findall(r.text)
            if not hits:
                break
            # Keep unique by reqid — each job shows up twice (title + "See full").
            before = len(out)
            for href, reqid, title_html in hits:
                if reqid in seen:
                    continue
                seen.add(reqid)
                title = htmlmod.unescape(title_html).strip()
                if not title or title.lower().startswith("see full"):
                    continue
                full_url = urljoin("https://jobs.apple.com", href)
                out.append({
                    "title": title,
                    # URL filter restricts the search to the USA; we don't
                    # get a precise city in the list view, so mark the
                    # result as US-wide so the outer is_usa() accepts it.
                    "location": "United States",
                    "url": full_url,
                    "posting_id": reqid,
                    "posted_at": None,
                })
            if len(out) == before:
                break
    return out


# ---------------------------------------------------------------------------
# Microsoft — their public site is an Eightfold SPA at
# apply.careers.microsoft.com. The Eightfold-style JSON endpoint at
# `/api/apply/v2/jobs` returns posting JSON without any auth, so we go
# straight there. No browser rendering needed.

_MICROSOFT_API = "https://apply.careers.microsoft.com/careers-home/api/apply/v2/jobs"


def microsoft(_: str = "") -> list[dict]:
    """Microsoft Careers (Eightfold SPA).

    We first probe the legacy public JSON endpoint just in case it ever
    comes back. If it returns nothing (which is the current state), we
    fall back to the isolated Playwright worker subprocess. The worker
    has a hard timeout, so a Playwright hang only costs us this one
    company on this one sweep — it cannot stall the broader run.
    """
    out: list[dict] = []
    seen: set[str] = set()
    queries = [
        "software engineer", "machine learning", "data engineer",
        "new grad", "intern", "university",
    ]
    headers = {
        **HEADERS_JSON,
        "Origin":  "https://apply.careers.microsoft.com",
        "Referer": "https://apply.careers.microsoft.com/careers",
    }
    for q in queries:
        for offset in range(0, 400, 100):  # up to 400 results per query
            params = {
                "domain": "microsoft.com",
                "query": q,
                "location": "United States",
                "start": offset,
                "num": 100,
                "pid": "",
                "Codes": "MS",
                "sort_by": "relevance",
            }
            url = f"{_MICROSOFT_API}?{urlencode(params)}"
            r = _retry_get(url, headers=headers)
            if r is None or r.status_code != 200:
                break
            try:
                data = r.json()
            except Exception:
                break
            positions = data.get("positions") or data.get("jobs") or []
            if not positions:
                break
            added = 0
            for j in positions:
                jid = str(j.get("id") or j.get("jobId") or j.get("display_job_id") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                added += 1
                title = j.get("name") or j.get("title")
                loc = (
                    j.get("location")
                    or j.get("primaryLocation")
                    or (", ".join(j.get("locations", [])) if isinstance(j.get("locations"), list) else None)
                )
                detail = j.get("canonicalPositionUrl") or j.get("ats_url") or \
                    f"https://jobs.careers.microsoft.com/global/en/job/{jid}"
                out.append({
                    "title": title,
                    "location": loc,
                    "url": detail,
                    "posting_id": jid,
                    "posted_at": _to_iso(j.get("t_create") or j.get("postingDate")),
                })
            if added == 0:
                break
    if out:
        return out
    return _run_playwright_worker("microsoft")


# ---------------------------------------------------------------------------
# Meta — their public GraphQL endpoint. The ``doc_id`` rotates frequently;
# we extract the current one from the jobs HTML on every run.

_META_DOC_ID_RE  = re.compile(r'"CareerPageJobSearchResultsPaginationQuery[^"]*"[^\{]{0,40}"id"\s*:\s*"(\d{12,20})"')
_META_DOC_ID_ALT = re.compile(r'"(\d{15,20})"[^\{]{0,200}"name"\s*:\s*"CareerPageJobSearchResultsPaginationQuery"')


def _meta_extract_doc_id(session: requests.Session) -> str | None:
    try:
        r = session.get("https://www.metacareers.com/jobs", headers=HEADERS_HTML,
                        timeout=REQUEST_TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    m = _META_DOC_ID_RE.search(r.text) or _META_DOC_ID_ALT.search(r.text)
    return m.group(1) if m else None


def meta(_: str = "") -> list[dict]:
    """Fetch Meta jobs via their public GraphQL endpoint. No browser fallback.

    The doc_id rotates so we extract it from the live HTML on each run. If
    we can't reach the API or parse the response, we return [] and let the
    outer pipeline log the empty result instead of hanging on Playwright.
    """
    out: list[dict] = []
    seen: set[str] = set()
    try:
        s = requests.Session()
        doc_id = _meta_extract_doc_id(s)
        if not doc_id:
            return out
        url = "https://www.metacareers.com/graphql"
        from urllib.parse import urlencode as _ue
        for page in range(1, 6):  # 6 pages × 100 = 600 max
            variables = {
                "search_input": {
                    "q": "",
                    "offices": [], "roles": [], "leadership_levels": [],
                    "saved_jobs": [], "saved_searches": [], "sub_teams": [],
                    "teams": [], "is_leadership": False, "is_remote_only": False,
                    "sort_by_new": True, "page": page, "results_per_page": 100,
                },
            }
            r = None
            for attempt in range(1, 4):
                try:
                    r = s.post(
                        url,
                        data=_ue({
                            "doc_id": doc_id,
                            "variables": __import__("json").dumps(variables),
                        }),
                        headers={
                            **HEADERS_JSON,
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Origin":  "https://www.metacareers.com",
                            "Referer": "https://www.metacareers.com/jobs",
                            "X-FB-Friendly-Name": "CareerPageJobSearchResultsPaginationQuery",
                        },
                        timeout=REQUEST_TIMEOUT,
                    )
                    if r.status_code < 500:
                        break
                except (requests.Timeout, requests.ConnectionError):
                    pass
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
            if r is None or r.status_code != 200:
                break
            if "application/json" not in r.headers.get("content-type", ""):
                break
            try:
                data = r.json()
            except Exception:
                break
            results = ((data.get("data") or {}).get("job_search") or [])
            if not results:
                break
            added = 0
            for j in results:
                jid = str(j.get("id") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                added += 1
                locs = j.get("locations") or []
                out.append({
                    "title":    j.get("title"),
                    "location": ", ".join(locs) if locs else None,
                    "url":      f"https://www.metacareers.com/jobs/{jid}" if jid else None,
                    "posting_id": jid or None,
                    "posted_at": _to_iso(j.get("posted_at") or j.get("created_time")),
                })
            if added == 0:
                break
    except Exception as e:
        log.warning("Meta GraphQL scrape failed: %s: %s",
                    type(e).__name__, str(e).splitlines()[0])
    if out:
        return out
    return _run_playwright_worker("meta")


# ---------------------------------------------------------------------------
# Salesforce — first-party careers site (card-based HTML + pagination).

def salesforce(_: str = "") -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    base = "https://careers.salesforce.com"
    # (fixed query params, max_pages). "New grad" matches 1000+ rows; shallow
    # pagination misses SWE AMTS / MTS / Futureforce listings that sit late
    # in the sort order. The site's jobtype facet and extra keywords surface
    # those rows with fewer pages; we still crawl deeper on key queries.
    query_runs: list[tuple[dict[str, str], int]] = [
        ({}, 10),
        ({"search": "software engineer"}, 12),
        ({"search": "machine learning"}, 10),
        ({"search": "data"}, 10),
        ({"search": "new grad"}, 28),
        ({"search": "", "jobtype": "New Grads", "pagesize": "20"}, 28),
        ({"search": "AMTS"}, 18),
        ({"search": "MTS"}, 18),
        ({"search": "college grad"}, 18),
        ({"search": "Futureforce"}, 14),
        ({"search": "intern"}, 10),
        ({"search": "summer"}, 10),
    ]

    for param_base, max_pages in query_runs:
        for page in range(1, max_pages + 1):
            params = dict(param_base)
            if page > 1:
                params["page"] = str(page)
            page_url = f"{base}/en/jobs/?{urlencode(params)}"
            r = _retry_get(page_url, headers=HEADERS_HTML)
            if r is None or r.status_code != 200 or not r.text:
                break

            soup = BeautifulSoup(r.text, "lxml")
            cards = soup.select("div.card.card-job")
            if not cards:
                break

            added_this_page = 0
            for card in cards:
                a = card.select_one("h3.card-title a[href]")
                if not a:
                    continue
                title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
                href = (a.get("href") or "").strip()
                if not title or not href:
                    continue
                url = urljoin(base, href)
                if url in seen:
                    continue
                seen.add(url)
                added_this_page += 1

                loc_lis = card.select("ul.locations li")
                if not loc_lis:
                    loc_lis = card.select(".locations li")
                loc_parts: list[str] = []
                for li in loc_lis:
                    frag = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
                    if frag:
                        loc_parts.append(frag)
                location = ", ".join(loc_parts) if loc_parts else None
                m = re.search(r"/en/jobs/(jr[0-9a-z]+)/", url, re.I)
                posting_id = m.group(1).upper() if m else None

                out.append({
                    "title": title,
                    "location": location,
                    "url": url,
                    "posting_id": posting_id,
                    "posted_at": None,
                })

            # Stop this query when pagination starts repeating.
            if added_this_page == 0:
                break
    return out


# ---------------------------------------------------------------------------
# Uber — Phenom People SPA; requires Playwright subprocess.

def uber(_: str = "") -> list[dict]:
    return _run_playwright_worker("uber")


# ---------------------------------------------------------------------------
# Dispatch registry.
# Salesforce is NOT listed here — it uses the Workday override in overrides.py
# which returns 1000+ jobs vs ~12 from the generic HTML scraper.

HANDLERS = {
    "amazon":          amazon,
    "google":          google,
    "googlealphabet":  google,
    "microsoft":       microsoft,
    "meta":            meta,
    "metafacebook":    meta,
    "apple":           apple,
    "uber":            uber,
}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def get_handler(company_name: str):
    return HANDLERS.get(normalize(company_name))
