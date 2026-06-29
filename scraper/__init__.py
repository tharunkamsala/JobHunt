"""Scraping pipeline. Detects ATS platform, dispatches to a handler,
   filters for target roles, returns normalized job dicts."""
from __future__ import annotations

import re
import time
import logging
from urllib.parse import urljoin, urlparse

from config import (
    USER_AGENT,
    POLITE_DELAY_SEC,
    ROLE_FILTERS,
    INTERNSHIP_CATEGORIES,
)
from db import get_enabled_scrape_categories
from . import greenhouse, lever, ashby, smartrecruiters, workday, generic, bigtech, eightfold, oraclehcm, talentbrew, workable, icims, jobvite, successfactors
from . import overrides as ats_overrides
from .details import enrich_descriptions
from .filters import match_categories
from .html_text import strip_html
from .location import is_usa
from .posting_id import coalesce as _coalesce_posting_id
from .posting_validation import job_has_posting_identity
from .transport import FetchStrategy, fetch


log = logging.getLogger(__name__)
HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"}


def http_get(url: str, **kw):
    return fetch(url, headers=HEADERS, strategy=FetchStrategy.REQUESTS, **kw)


def _sniff_ats(url: str, company_name: str) -> tuple[str, str]:
    """Return (ats_name, slug_or_url). Falls back to ('generic', url)."""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    if "greenhouse.io" in host or "boards.greenhouse.io" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "greenhouse", slug
    if "lever.co" in host or "jobs.lever.co" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "lever", slug
    if "ashbyhq.com" in host or "jobs.ashbyhq.com" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "ashby", slug
    if "smartrecruiters.com" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "smartrecruiters", slug
    if "eightfold.ai" in host:
        return "eightfold", host.split(".")[0]
    if "apply.workable.com" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "workable", slug
    if "oraclecloud.com" in host and "candidateexperience" in path:
        return "oraclehcm", url
    if "myworkdayjobs.com" in host or "workday" in host:
        return "workday", url
    if "icims.com" in host:
        # Extract slug from subdomain: careers-{slug}.icims.com
        m = re.match(r"careers-?([a-z0-9_-]+)\.icims\.com", host)
        slug = m.group(1) if m else _infer_slug(company_name)
        return "icims", slug
    if "jobs.jobvite.com" in host or "jobvite.com" in host:
        slug = path.strip("/").split("/")[0] or _infer_slug(company_name)
        return "jobvite", slug
    if "successfactors" in host or "sap.com" in host:
        return "successfactors", url

    # Try fetching the page and looking for embedded ATS links.
    try:
        r = http_get(url)
        html = r.text.lower()
        if "boards.greenhouse.io" in html or "greenhouse.io/embed" in html:
            m = re.search(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)", html)
            if m:
                return "greenhouse", m.group(1)
        if "jobs.lever.co" in html:
            m = re.search(r"jobs\.lever\.co/([a-z0-9_-]+)", html)
            if m:
                return "lever", m.group(1)
        if "jobs.ashbyhq.com" in html or "api.ashbyhq.com" in html:
            m = re.search(r"(?:jobs\.ashbyhq\.com|api\.ashbyhq\.com/posting-api/job-board)/([a-z0-9_-]+)", html)
            if m:
                return "ashby", m.group(1)
        if "smartrecruiters.com" in html:
            m = re.search(r"smartrecruiters\.com/([A-Za-z0-9_-]+)", html)
            if m:
                return "smartrecruiters", m.group(1)
        if "eightfold.ai" in html:
            m = re.search(r"https?://([a-z0-9-]+)\.eightfold\.ai", html)
            if m:
                return "eightfold", m.group(1)
        if "talentbrew" in html and "/search-jobs" in html:
            m = re.search(r'href="([^"]*/search-jobs[^"]*)"', html, re.I)
            if m:
                return "talentbrew", urljoin(url, m.group(1))
        if "tbcdn.talentbrew.com" in html or 'data-ajax-url="/search-jobs/results"' in html:
            return "talentbrew", urljoin(url, "/search-jobs")
        if "careers.oracle.com/en/sites/jobsearch/jobs" in html:
            m = re.search(r'https://careers\.oracle\.com/en/sites/jobsearch/jobs[^"\']*', html, re.I)
            if m:
                return "oraclehcm", m.group(0)
        if "apply.workable.com" in html:
            m = re.search(r'https://apply\.workable\.com/([a-z0-9_-]+)/', html, re.I)
            if m:
                return "workable", m.group(1)
        if "var cx_config" in html and "candidateexperience" in html:
            return "oraclehcm", url
        if "myworkdayjobs.com" in html:
            return "workday", url
        if "icims.com" in html:
            m = re.search(r"careers-?([a-z0-9_-]+)\.icims\.com", html)
            if m:
                return "icims", m.group(1)
            slug = _infer_slug(company_name)
            return "icims", slug
        if "jobs.jobvite.com" in html:
            m = re.search(r"jobs\.jobvite\.com/([a-z0-9_-]+)", html, re.I)
            if m:
                return "jobvite", m.group(1)
        if "successfactors" in html or "career_ns=job_listing" in html:
            m = re.search(r'href="([^"]*successfactors[^"]*|[^"]*career\?[^"]*career_ns[^"]*)"', html, re.I)
            if m:
                return "successfactors", urljoin(url, m.group(1))
            return "successfactors", url
        if 'data-ph-id="ph-' in html or "phenompeople.com" in html:
            # Phenom People SPA; fall through to playwright worker
            slug = _infer_slug(company_name)
            return "playwright", slug
    except Exception:
        pass

    # Last resort: probe common ATS endpoints with the company slug.
    slug = _infer_slug(company_name)
    if slug:
        for probe_ats, probe_url in (
            ("greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"),
            ("lever",      f"https://api.lever.co/v0/postings/{slug}?mode=json"),
            ("ashby",      f"https://api.ashbyhq.com/posting-api/job-board/{slug}"),
            ("workable",   f"https://apply.workable.com/api/v1/widget/accounts/{slug}"),
        ):
            try:
                pr = fetch(
                    probe_url,
                    headers=HEADERS,
                    expect="json",
                    strategy=FetchStrategy.REQUESTS,
                    auto_escalate=True,
                )
                if pr.status_code == 200:
                    data = pr.json()
                    if probe_ats == "greenhouse" and data.get("jobs"): return probe_ats, slug
                    if probe_ats == "lever" and isinstance(data, list) and data: return probe_ats, slug
                    if probe_ats == "ashby" and data.get("jobs"): return probe_ats, slug
                    if probe_ats == "workable" and data.get("jobs"): return probe_ats, slug
            except Exception:
                continue

    return "generic", url


def _infer_slug(company_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", company_name.lower())


def _finish_scrape(
    source: str,
    raw: list[dict],
    company: dict | None,
    careers_url: str | None = None,
) -> list[dict]:
    """Filter/normalize jobs, then optionally enrich descriptions."""
    normalized = _normalize_and_filter(raw, company)
    if normalized:
        try:
            enrich_descriptions(
                normalized,
                source=source,
                careers_url=careers_url or (company or {}).get("url") or "",
            )
        except Exception:
            log.exception("description enrichment failed for %s", source)
    return normalized


def scrape_company(company: dict) -> tuple[str, list[dict]]:
    """Returns (ats_source, list of normalized jobs).
    Each job: {title, location, url, categories}
    """
    url = company.get("url") or ""
    name = company.get("name") or ""

    # 1) Company-specific handler (Amazon, Google, Microsoft, Meta, Apple, ...).
    custom = bigtech.get_handler(name)
    if custom is not None:
        source = f"bigtech:{name.lower().split()[0]}"
        try:
            raw = custom(url)
        except Exception:
            raw = []
        normalized = _finish_scrape(source, raw, company)
        time.sleep(POLITE_DELAY_SEC)
        if normalized:
            return source, normalized
        if raw:
            return source, normalized
        # Fall through to overrides / generic detection if the custom
        # handler returned no raw jobs.

    # 2) Curated ATS override (covers ~50 companies whose real ATS the
    #    sniffer can't reliably detect from a vanity careers URL).
    override = ats_overrides.lookup(name)
    if override is not None:
        ats, handle = override
        source = f"override:{ats}"
        try:
            raw = _dispatch(ats, handle)
        except Exception:
            raw = []
        normalized = _finish_scrape(
            source, raw, company,
            careers_url=handle if ats in {"workday", "talentbrew", "smartrecruiters"} else None,
        )
        time.sleep(POLITE_DELAY_SEC)
        if normalized:
            return source, normalized
        if ats == "workday":
            try:
                generic_raw = generic.fetch(url)
                generic_norm = _finish_scrape("override:workday->generic", generic_raw, company)
                if generic_norm:
                    return "override:workday->generic", generic_norm
            except Exception:
                pass
        # If the override ATS responded with jobs but filters removed all of
        # them, still report the override source — do not re-sniff a vanity URL.
        if raw:
            return source, normalized
        # Fall back to sniffing when the override ATS returned no rows at all.

    # 3) Auto-sniff the ATS from the URL / careers page / slug probes.
    ats, handle = _sniff_ats(url, name)

    try:
        raw = _dispatch(ats, handle) if ats != "generic" else generic.fetch(url)
    finally:
        time.sleep(POLITE_DELAY_SEC)

    sniff_careers = handle if ats in {"workday", "talentbrew", "smartrecruiters"} and isinstance(handle, str) and handle.startswith("http") else url
    normalized = _finish_scrape(ats, raw, company, careers_url=sniff_careers)
    if normalized:
        return ats, normalized
    if ats == "workday":
        try:
            generic_raw = generic.fetch(url)
            generic_norm = _finish_scrape("workday->generic", generic_raw, company)
            if generic_norm:
                return "workday->generic", generic_norm
        except Exception:
            pass
    return ats, normalized


def _dispatch(ats: str, handle: str) -> list[dict]:
    if ats == "greenhouse":      return greenhouse.fetch(handle)
    if ats == "lever":           return lever.fetch(handle)
    if ats == "ashby":           return ashby.fetch(handle)
    if ats == "smartrecruiters": return smartrecruiters.fetch(handle)
    if ats == "workday":         return workday.fetch(handle)
    if ats == "eightfold":       return eightfold.fetch(handle)
    if ats == "oraclehcm":       return oraclehcm.fetch(handle)
    if ats == "talentbrew":      return talentbrew.fetch(handle)
    if ats == "workable":        return workable.fetch(handle)
    if ats == "icims":           return icims.fetch(handle)
    if ats == "jobvite":         return jobvite.fetch(handle)
    if ats == "successfactors":  return successfactors.fetch(handle)
    if ats == "playwright":      return bigtech._run_playwright_worker(handle)
    if ats == "generic":         return generic.fetch(handle)
    return []


def _job_description(raw: dict) -> str | None:
    for key in (
        "description",
        "description_plain",
        "descriptionPlain",
        "descriptionHtml",
        "content",
        "summary",
    ):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            return strip_html(val)
    return None


def _normalize_and_filter(raw: list[dict], company: dict | None = None) -> list[dict]:
    normalized: list[dict] = []
    seen_titles: set[tuple[str, str]] = set()
    try:
        enabled = set(get_enabled_scrape_categories())
    except Exception:
        enabled = set(ROLE_FILTERS.keys())
    company = company or {}
    is_extra_company = (company.get("company_source") or "").strip().lower() == "extra"
    allowed_for_company = enabled if not is_extra_company else enabled & set(INTERNSHIP_CATEGORIES)
    for j in raw:
        title = (j.get("title") or "").strip()
        if not title:
            continue
        cats = match_categories(title)
        if not cats:
            continue
        if cats[0] not in allowed_for_company:
            continue
        loc = (j.get("location") or "").strip() or None
        if not is_usa(loc):
            continue
        key = (title.lower(), (loc or "").lower())
        if key in seen_titles:
            continue
        seen_titles.add(key)
        row = {
            "title": title,
            "location": loc,
            "url": j.get("url"),
            "posted_at": j.get("posted_at"),
            "posting_id": _coalesce_posting_id(j.get("posting_id"), j.get("url")),
            "categories": cats,
            "description": _job_description(j),
        }
        if not job_has_posting_identity(row):
            continue
        normalized.append(row)
    return normalized
