"""Lazy job-description enrichment from ATS detail pages/APIs.

Runs only for jobs that already passed filters and lack a substantive
description. Capped per company so scrapes stay fast and polite.
"""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from config import (
    DETAIL_FETCH_DELAY_SEC,
    DETAIL_FETCH_ENABLED,
    DETAIL_FETCH_MAX_PER_COMPANY,
    DETAIL_FETCH_MIN_CHARS,
    REQUEST_TIMEOUT,
    USER_AGENT,
)
from .html_text import strip_html
from .transport import FetchStrategy, fetch as transport_fetch
from .workday import _derive_api

log = logging.getLogger(__name__)

_HTML_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
_JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _has_substantive_description(job: dict) -> bool:
    text = (job.get("description") or "").strip()
    return len(text) >= DETAIL_FETCH_MIN_CHARS


def _source_kind(source: str, url: str) -> str | None:
    s = (source or "").lower()
    u = (url or "").lower()
    if "workday" in s or "myworkdayjobs.com" in u:
        return "workday"
    if "talentbrew" in s or "tbcdn.talentbrew.com" in u:
        return "talentbrew"
    if "smartrecruiters" in s or "smartrecruiters.com" in u:
        return "smartrecruiters"
    if "greenhouse" in s or "greenhouse.io" in u:
        return "greenhouse"
    if "lever" in s or "lever.co" in u:
        return "lever"
    if "ashby" in s or "ashbyhq.com" in u:
        return "ashby"
    return None


def _workday_detail_url(job_url: str, careers_url: str | None) -> str | None:
    if not job_url or not careers_url:
        return None
    derived = _derive_api(careers_url)
    if not derived:
        return None
    base, tenant, site = derived
    m = re.search(r"/job/.+", urlparse(job_url).path)
    if not m:
        return None
    return f"{base}/wday/cxs/{tenant}/{site}{m.group(0)}"


def _fetch_workday(job_url: str, careers_url: str | None) -> str | None:
    api = _workday_detail_url(job_url, careers_url)
    if not api:
        return None
    try:
        r = transport_fetch(
            api,
            headers=_JSON_HEADERS,
            timeout=REQUEST_TIMEOUT,
            expect="json",
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        info = data.get("jobPostingInfo") or {}
        html = info.get("jobDescription") or ""
        return strip_html(html) if html else None
    except Exception:
        log.debug("workday detail fetch failed for %s", job_url, exc_info=True)
        return None


def _fetch_talentbrew(job_url: str) -> str | None:
    try:
        r = transport_fetch(
            job_url,
            headers=_HTML_HEADERS,
            timeout=REQUEST_TIMEOUT,
            strategy=FetchStrategy.REQUESTS,
            allow_redirects=True,
            auto_escalate=False,
        )
        if r.status_code != 200 or not r.text:
            return None
        soup = BeautifulSoup(r.text, "lxml")
        for sel in (
            ".job-description",
            "#job-description",
            ".job-details",
            ".job-description-body",
            "[data-job-description]",
        ):
            el = soup.select_one(sel)
            if el:
                text = strip_html(str(el))
                text = re.sub(r"\s*Apply Now\s*Share Job.*", "", text, flags=re.I | re.S).strip()
                if text and len(text) >= DETAIL_FETCH_MIN_CHARS:
                    return text
        main = soup.select_one("main") or soup.select_one("#content")
        if main:
            text = strip_html(str(main))
            text = re.sub(r"\s*Apply Now\s*Share Job.*", "", text, flags=re.I | re.S).strip()
            if text and len(text) >= DETAIL_FETCH_MIN_CHARS:
                return text
    except Exception:
        log.debug("talentbrew detail fetch failed for %s", job_url, exc_info=True)
    return None


def _fetch_smartrecruiters(job_url: str) -> str | None:
    m = re.search(r"smartrecruiters\.com/([^/]+)/([^/?#]+)", job_url, re.I)
    if not m:
        return None
    slug, posting_id = m.group(1), m.group(2)
    api = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"
    try:
        r = transport_fetch(
            api,
            headers=_JSON_HEADERS,
            timeout=REQUEST_TIMEOUT,
            expect="json",
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        sections = (data.get("jobAd") or {}).get("sections") or {}
        parts: list[str] = []
        for sec in sections.values():
            if not isinstance(sec, dict):
                continue
            title = (sec.get("title") or "").strip()
            body = strip_html(sec.get("text") or "")
            if not body:
                continue
            parts.append(f"{title}\n{body}" if title else body)
        if not parts:
            return None
        return "\n\n".join(parts)
    except Exception:
        log.debug("smartrecruiters detail fetch failed for %s", job_url, exc_info=True)
        return None


def _fetch_greenhouse(job_url: str) -> str | None:
    m = re.search(r"(?:boards|job-boards)\.greenhouse\.io/([^/]+)/jobs/(\d+)", job_url, re.I)
    if not m:
        return None
    slug, jid = m.group(1), m.group(2)
    api = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}"
    try:
        r = transport_fetch(
            api,
            headers=_JSON_HEADERS,
            timeout=REQUEST_TIMEOUT,
            expect="json",
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200:
            return None
        html = (r.json() or {}).get("content") or ""
        return strip_html(html) if html else None
    except Exception:
        log.debug("greenhouse detail fetch failed for %s", job_url, exc_info=True)
        return None


def _fetch_lever(job_url: str) -> str | None:
    m = re.search(r"jobs\.lever\.co/([^/]+)/([^/?#]+)", job_url, re.I)
    if not m:
        return None
    slug, posting = m.group(1), m.group(2)
    api = f"https://api.lever.co/v0/postings/{slug}/{posting}?mode=json"
    try:
        r = transport_fetch(
            api,
            headers=_JSON_HEADERS,
            timeout=REQUEST_TIMEOUT,
            expect="json",
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200:
            return None
        data = r.json() or {}
        plain = (data.get("descriptionPlain") or "").strip()
        if plain:
            return plain
        html = data.get("description") or ""
        return strip_html(html) if html else None
    except Exception:
        log.debug("lever detail fetch failed for %s", job_url, exc_info=True)
        return None


def _fetch_ashby(job_url: str) -> str | None:
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([a-f0-9-]+)", job_url, re.I)
    if not m:
        return None
    slug, jid = m.group(1), m.group(2)
    api = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        r = transport_fetch(
            api,
            headers=_JSON_HEADERS,
            timeout=REQUEST_TIMEOUT,
            expect="json",
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200:
            return None
        for job in (r.json() or {}).get("jobs") or []:
            if str(job.get("id")) == jid or (job.get("jobUrl") or "") == job_url:
                html = job.get("descriptionHtml") or ""
                return strip_html(html) if html else None
    except Exception:
        log.debug("ashby detail fetch failed for %s", job_url, exc_info=True)
    return None


def enrich_descriptions(
    jobs: list[dict],
    *,
    source: str = "",
    careers_url: str | None = None,
) -> None:
    """Fill missing descriptions in-place for filtered job rows."""
    if not DETAIL_FETCH_ENABLED or not jobs:
        return

    fetched = 0
    for job in jobs:
        if fetched >= DETAIL_FETCH_MAX_PER_COMPANY:
            break
        if _has_substantive_description(job):
            continue
        url = (job.get("url") or "").strip()
        if not url:
            continue

        kind = _source_kind(source, url)
        if not kind:
            continue

        desc: str | None = None
        if kind == "workday":
            desc = _fetch_workday(url, careers_url)
        elif kind == "talentbrew":
            desc = _fetch_talentbrew(url)
        elif kind == "smartrecruiters":
            desc = _fetch_smartrecruiters(url)
        elif kind == "greenhouse":
            desc = _fetch_greenhouse(url)
        elif kind == "lever":
            desc = _fetch_lever(url)
        elif kind == "ashby":
            desc = _fetch_ashby(url)

        if desc and len(desc) >= DETAIL_FETCH_MIN_CHARS:
            job["description"] = desc
            fetched += 1
            if DETAIL_FETCH_DELAY_SEC > 0:
                time.sleep(DETAIL_FETCH_DELAY_SEC)

    if fetched:
        log.info("Enriched %d job descriptions (%s)", fetched, source or careers_url or "?")
