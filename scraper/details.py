"""Lazy job-description enrichment from ATS detail pages/APIs.

Runs only for jobs that already passed filters and lack a substantive
description and/or company posting date. Capped per company so scrapes
stay fast and polite.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any
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
from .workday import _derive_api, _parse_workday_posted

log = logging.getLogger(__name__)

_HTML_HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
_JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _has_substantive_description(job: dict) -> bool:
    text = (job.get("description") or "").strip()
    return len(text) >= DETAIL_FETCH_MIN_CHARS


def _has_posted_at(job: dict) -> bool:
    return bool((job.get("posted_at") or "").strip())


def _needs_enrichment(job: dict) -> bool:
    return not _has_substantive_description(job) or not _has_posted_at(job)


def _normalize_posted(value: Any) -> str | None:
    """Best-effort ISO8601 UTC string from ATS date fields."""
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 0:
        # Lever uses ms since epoch.
        sec = value / 1000 if value > 1_000_000_000_000 else value
        try:
            return (
                datetime.fromtimestamp(sec, tz=timezone.utc)
                .replace(tzinfo=None)
                .isoformat(timespec="seconds")
            )
        except (OSError, OverflowError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.lower().startswith("posted"):
        return _parse_workday_posted(raw)
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat(timespec="seconds")
    except ValueError:
        pass
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).isoformat(timespec="seconds")
        except ValueError:
            continue
    return None


def _detail_result(description: str | None = None, posted_at: Any = None) -> dict[str, str | None]:
    return {
        "description": description,
        "posted_at": _normalize_posted(posted_at),
    }


def _merge_detail(job: dict, detail: dict[str, str | None]) -> bool:
    changed = False
    desc = (detail.get("description") or "").strip()
    if desc and len(desc) >= DETAIL_FETCH_MIN_CHARS and not _has_substantive_description(job):
        job["description"] = desc
        changed = True
    posted = detail.get("posted_at")
    if posted and not _has_posted_at(job):
        job["posted_at"] = posted
        changed = True
    return changed


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


def _fetch_workday(job_url: str, careers_url: str | None) -> dict[str, str | None]:
    api = _workday_detail_url(job_url, careers_url)
    if not api:
        return _detail_result()
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
            return _detail_result()
        data = r.json()
        info = data.get("jobPostingInfo") or {}
        html = info.get("jobDescription") or ""
        posted = (
            info.get("postedOn")
            or info.get("postedOnDate")
            or info.get("startDate")
            or data.get("postedOn")
        )
        return _detail_result(
            strip_html(html) if html else None,
            posted,
        )
    except Exception:
        log.debug("workday detail fetch failed for %s", job_url, exc_info=True)
        return _detail_result()


def _posted_from_html(soup: BeautifulSoup) -> str | None:
    for sel in ("time[datetime]", "meta[property='article:published_time']", "meta[name='date']"):
        el = soup.select_one(sel)
        if not el:
            continue
        val = el.get("datetime") or el.get("content")
        posted = _normalize_posted(val)
        if posted:
            return posted
    text = soup.get_text(" ", strip=True)[:8000]
    for pat in (
        r"posted\s+(?:on\s+)?([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"date\s+posted[:\s]+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
        r"posted\s+(\d+\s+days?\s+ago)",
    ):
        m = re.search(pat, text, re.I)
        if m:
            posted = _normalize_posted(m.group(1))
            if posted:
                return posted
    return None


def _fetch_talentbrew(job_url: str) -> dict[str, str | None]:
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
            return _detail_result()
        soup = BeautifulSoup(r.text, "lxml")
        posted = _posted_from_html(soup)
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
                    return _detail_result(text, posted)
        main = soup.select_one("main") or soup.select_one("#content")
        if main:
            text = strip_html(str(main))
            text = re.sub(r"\s*Apply Now\s*Share Job.*", "", text, flags=re.I | re.S).strip()
            if text and len(text) >= DETAIL_FETCH_MIN_CHARS:
                return _detail_result(text, posted)
    except Exception:
        log.debug("talentbrew detail fetch failed for %s", job_url, exc_info=True)
    return _detail_result()


def _fetch_smartrecruiters(job_url: str) -> dict[str, str | None]:
    from .smartrecruiters import posting_id_from_url

    m = re.search(r"smartrecruiters\.com/([^/]+)/([^/?#]+)", job_url, re.I)
    if not m:
        return _detail_result()
    slug = m.group(1)
    posting_id = posting_id_from_url(job_url) or m.group(2).split("-")[0]
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
            return _detail_result()
        data = r.json()
        posted = data.get("releasedDate") or data.get("createdOn") or data.get("postingDate")
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
            return _detail_result(posted_at=posted)
        return _detail_result("\n\n".join(parts), posted)
    except Exception:
        log.debug("smartrecruiters detail fetch failed for %s", job_url, exc_info=True)
        return _detail_result()


def _fetch_greenhouse(job_url: str) -> dict[str, str | None]:
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
            return _detail_result()
        payload = r.json() or {}
        html = payload.get("content") or ""
        posted = payload.get("first_published") or payload.get("updated_at")
        return _detail_result(strip_html(html) if html else None, posted)
    except Exception:
        log.debug("greenhouse detail fetch failed for %s", job_url, exc_info=True)
        return _detail_result()


def _fetch_lever(job_url: str) -> dict[str, str | None]:
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
            return _detail_result()
        data = r.json() or {}
        plain = (data.get("descriptionPlain") or "").strip()
        desc = plain or (strip_html(data.get("description") or "") if data.get("description") else None)
        posted = data.get("createdAt")
        return _detail_result(desc, posted)
    except Exception:
        log.debug("lever detail fetch failed for %s", job_url, exc_info=True)
        return _detail_result()


def _fetch_ashby(job_url: str) -> dict[str, str | None]:
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
            return _detail_result()
        for job in (r.json() or {}).get("jobs") or []:
            if str(job.get("id")) == jid or (job.get("jobUrl") or "") == job_url:
                html = job.get("descriptionHtml") or ""
                posted = job.get("publishedAt") or job.get("updatedAt")
                return _detail_result(strip_html(html) if html else None, posted)
    except Exception:
        log.debug("ashby detail fetch failed for %s", job_url, exc_info=True)
    return _detail_result()


def _fetch_detail(kind: str, url: str, careers_url: str | None) -> dict[str, str | None]:
    if kind == "workday":
        return _fetch_workday(url, careers_url)
    if kind == "talentbrew":
        return _fetch_talentbrew(url)
    if kind == "smartrecruiters":
        return _fetch_smartrecruiters(url)
    if kind == "greenhouse":
        return _fetch_greenhouse(url)
    if kind == "lever":
        return _fetch_lever(url)
    if kind == "ashby":
        return _fetch_ashby(url)
    return _detail_result()


def enrich_descriptions(
    jobs: list[dict],
    *,
    source: str = "",
    careers_url: str | None = None,
) -> None:
    """Fill missing descriptions and/or posting dates in-place for filtered rows."""
    if not DETAIL_FETCH_ENABLED or not jobs:
        return

    fetched = 0
    for job in jobs:
        if fetched >= DETAIL_FETCH_MAX_PER_COMPANY:
            break
        if not _needs_enrichment(job):
            continue
        url = (job.get("url") or "").strip()
        if not url:
            continue

        kind = _source_kind(source, url)
        if not kind:
            continue

        detail = _fetch_detail(kind, url, careers_url)
        if _merge_detail(job, detail):
            fetched += 1
            if DETAIL_FETCH_DELAY_SEC > 0:
                time.sleep(DETAIL_FETCH_DELAY_SEC)

    if fetched:
        log.info("Enriched %d job detail rows (%s)", fetched, source or careers_url or "?")
