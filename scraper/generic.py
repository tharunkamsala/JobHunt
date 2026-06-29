"""Generic fallback scraper.

This path is used when we cannot confidently identify a supported ATS.
It is intentionally broad: besides visible anchors, it also reads
structured JSON blobs that many modern careers pages embed for React/Next
apps and SEO job cards.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
_JOBISH_WORDS = re.compile(
    r"engineer|developer|scientist|sde|swe|intern|researcher|manager|analyst|architect|"
    r"sre|mlops|data|devops|security|platform|infrastructure|software|machine learning|ai",
    re.IGNORECASE,
)
_ATS_HOST_RE = re.compile(
    r"(greenhouse|lever|ashby|smartrecruiters|workday|myworkday|oraclecloud|eightfold|"
    r"icims|successfactors|talentbrew|workable)",
    re.I,
)
_JOB_DETAIL_PATH_RE = re.compile(r"/(job|jobs|position|posting|open-positions?|search-jobs)/", re.I)
_NOISY_TITLE_RE = re.compile(
    r"learn more|explore|email us|join our talent network|job alerts?|skip to main content",
    re.I,
)


def _clean_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = str(value)
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _looks_like_job_title(text: str | None) -> bool:
    if not text:
        return False
    if len(text) < 4 or len(text) > 200:
        return False
    return bool(_JOBISH_WORDS.search(text))


def _allowed_external(full: str, base: str) -> bool:
    full_host = urlparse(full).netloc.lower()
    base_host = urlparse(base).netloc.lower()
    if not full_host or full_host == base_host:
        return True
    return bool(_ATS_HOST_RE.search(full))


def _is_web_url(value: str | None) -> bool:
    if not value:
        return False
    return urlparse(value).scheme in ("http", "https")


def _join_location(parts: list[str]) -> str | None:
    clean = [_clean_text(part) for part in parts]
    clean = [part for part in clean if part]
    return ", ".join(clean) if clean else None


def _extract_location(value) -> str | None:
    if isinstance(value, str):
        return _clean_text(value)
    if isinstance(value, list):
        items: list[str] = []
        for item in value[:4]:
            loc = _extract_location(item)
            if loc:
                items.append(loc)
        return _join_location(items)
    if isinstance(value, Mapping):
        return _join_location([
            value.get("city"),
            value.get("region"),
            value.get("country"),
            value.get("display"),
            value.get("name"),
            value.get("addressLocality"),
            value.get("addressRegion"),
            value.get("addressCountry"),
        ])
    return None


def _extract_posting_id(node: Mapping[str, object]) -> str | None:
    identifier = node.get("identifier")
    if isinstance(identifier, Mapping):
        value = _clean_text(identifier.get("value"))
        if value:
            return value[:200]
    for key in ("jobPostingId", "jobId", "requisitionId", "postingId", "reqId", "id"):
        value = _clean_text(node.get(key))
        if value:
            return value[:200]
    return None


def _candidate_from_mapping(node: Mapping[str, object], base: str) -> dict | None:
    raw_url = None
    for key in ("url", "applyUrl", "jobUrl", "canonicalPositionUrl", "positionUrl", "externalPath"):
        raw_url = node.get(key)
        if raw_url:
            break
    url = _clean_text(raw_url)
    if url:
        url = urljoin(base, url)
        if not _is_web_url(url):
            return None
        if not _allowed_external(url, base):
            return None

    title = None
    for key in ("title", "name", "jobTitle", "positionTitle", "job_title"):
        title = _clean_text(node.get(key))
        if title:
            break
    node_type = _clean_text(node.get("@type") or node.get("type"))
    is_jobposting = isinstance(node_type, str) and "jobposting" in node_type.lower()
    if not _looks_like_job_title(title):
        if not is_jobposting:
            return None
        if not title:
            return None

    # Require either a URL or a strong signal that this is an embedded job object.
    if not url and not is_jobposting and not any(key in node for key in ("datePosted", "jobLocation", "identifier")):
        return None

    location = None
    for key in ("location", "locations", "locationsText", "jobLocation", "jobLocationDisplay"):
        location = _extract_location(node.get(key))
        if location:
            break

    posted_at = None
    for key in ("datePosted", "posted_at", "postedAt", "postedOn", "releasedDate", "createdOn"):
        posted_at = _clean_text(node.get(key))
        if posted_at:
            break

    return {
        "title": title,
        "location": location,
        "url": url,
        "posting_id": _extract_posting_id(node),
        "posted_at": posted_at,
    }


def _walk_json(node, base: str, jobs: list[dict]) -> None:
    if isinstance(node, Mapping):
        candidate = _candidate_from_mapping(node, base)
        if candidate:
            jobs.append(candidate)
        for value in node.values():
            _walk_json(value, base, jobs)
        return
    if isinstance(node, list):
        for item in node:
            _walk_json(item, base, jobs)


def _script_json_candidates(soup: BeautifulSoup, base: str) -> list[dict]:
    jobs: list[dict] = []
    for script in soup.find_all("script"):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        script_type = (script.get("type") or "").lower()
        blobs: list[object] = []
        if "ld+json" in script_type or "application/json" in script_type:
            try:
                blobs.append(json.loads(raw))
            except Exception:
                continue
        else:
            # Best-effort parse of inline state assignments.
            for match in re.finditer(r"=\s*(\{[\s\S]{80,}\}|\[[\s\S]{80,}\])\s*;", raw):
                try:
                    blobs.append(json.loads(match.group(1)))
                except Exception:
                    continue
        for blob in blobs:
            _walk_json(blob, base, jobs)
    return jobs


def _anchor_candidates(soup: BeautifulSoup, base: str) -> list[dict]:
    def _nearby_location(anchor: Tag) -> str | None:
        # Common card markup: location chips/list near the title link.
        card = anchor.find_parent(lambda t: isinstance(t, Tag) and ("job" in " ".join(t.get("class", [])).lower() or "card" in " ".join(t.get("class", [])).lower()))
        scope: Tag = card or anchor.parent or anchor
        for sel in (".locations li", ".location li", ".job-location", "[class*='location']"):
            try:
                node = scope.select_one(sel)
            except Exception:
                node = None
            if node:
                txt = _clean_text(node.get_text(" ", strip=True))
                if txt and len(txt) <= 120:
                    return txt
        return None

    jobs: list[dict] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if not _is_web_url(href):
            continue
        if not _allowed_external(href, base):
            continue
        text = (
            _clean_text(a.get_text(" ", strip=True))
            or _clean_text(a.get("aria-label"))
            or _clean_text(a.get("title"))
        )
        if not _looks_like_job_title(text) or _NOISY_TITLE_RE.search(text or ""):
            continue
        path = urlparse(href).path
        external_ats = urlparse(href).netloc.lower() != urlparse(base).netloc.lower()
        if not external_ats and not _JOB_DETAIL_PATH_RE.search(path):
            continue
        jobs.append({
            "title": text,
            "location": _nearby_location(a),
            "url": href,
            "posting_id": None,
            "posted_at": None,
        })
    return jobs


def fetch(url: str) -> list[dict]:
    try:
        r = transport_fetch(
            url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
            strategy=FetchStrategy.REQUESTS,
        )
    except Exception:
        return []
    if r.status_code != 200 or not r.text:
        return []

    soup = BeautifulSoup(r.text, "lxml")
    base = r.url or url
    jobs: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for candidate in _script_json_candidates(soup, base) + _anchor_candidates(soup, base):
        title = _clean_text(candidate.get("title"))
        job_url = _clean_text(candidate.get("url"))
        posting_id = _clean_text(candidate.get("posting_id"))
        if not job_url and not posting_id:
            continue
        if not _looks_like_job_title(title):
            continue
        dedupe = (job_url or f"urn:posting:{posting_id}").lower()
        key = (title.lower(), dedupe)
        if key in seen:
            continue
        seen.add(key)
        jobs.append({
            "title": title,
            "location": _clean_text(candidate.get("location")),
            "url": job_url,
            "posting_id": posting_id,
            "posted_at": _clean_text(candidate.get("posted_at")),
        })
    return jobs
