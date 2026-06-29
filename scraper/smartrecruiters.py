"""SmartRecruiters public API:
   https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=0

List rows expose ``ref`` as an *API* URL (api.smartrecruiters.com/...), not the
public apply link. Use ``applyUrl`` from detail responses, or build
https://jobs.smartrecruiters.com/{company}/{id} for the list endpoint.
"""
from __future__ import annotations

import re

import requests

from config import REQUEST_TIMEOUT, USER_AGENT

_API_HOST = "api.smartrecruiters.com"
_JOBS_HOST = "jobs.smartrecruiters.com"


def _company_slug(slug: str, job: dict) -> str:
    company = job.get("company") or {}
    if isinstance(company, dict):
        for key in ("identifier", "name"):
            val = (company.get(key) or "").strip()
            if val:
                return val
    return slug


def _clean_public_url(url: str | None) -> str | None:
    if not url or not isinstance(url, str):
        return None
    val = url.strip()
    if not val.startswith("http"):
        return None
    low = val.lower()
    if _API_HOST in low:
        return None
    if _JOBS_HOST not in low:
        return None
    return val.split("?")[0].rstrip("/")


def _public_job_url(slug: str, job: dict) -> str | None:
    for key in ("applyUrl", "postingUrl", "jobUrl"):
        url = _clean_public_url(job.get(key))
        if url:
            return url
    ref = _clean_public_url(job.get("ref"))
    if ref:
        return ref
    sr_id = job.get("id")
    if sr_id is None:
        return None
    company_slug = _company_slug(slug, job)
    return f"https://{_JOBS_HOST}/{company_slug}/{sr_id}"


def posting_id_from_url(url: str | None) -> str | None:
    """Numeric SmartRecruiters posting id from a public or API URL."""
    if not url:
        return None
    m = re.search(
        rf"{re.escape(_JOBS_HOST)}/[^/]+/(\d+)",
        url,
        re.I,
    )
    if m:
        return m.group(1)
    m = re.search(
        rf"{re.escape(_API_HOST)}/v1/companies/[^/]+/postings/(\d+)",
        url,
        re.I,
    )
    if m:
        return m.group(1)
    return None


def fetch(slug: str) -> list[dict]:
    jobs: list[dict] = []
    offset = 0
    limit = 100
    while True:
        url = (
            f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
            f"?limit={limit}&offset={offset}"
        )
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            break
        data = r.json()
        content = data.get("content", []) or []
        for j in content:
            loc = j.get("location") or {}
            loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
            sr_id = j.get("id")
            job_url = _public_job_url(slug, j)
            pid = str(sr_id) if sr_id is not None else posting_id_from_url(job_url)
            jobs.append({
                "title": j.get("name"),
                "location": loc_str or None,
                "url": job_url,
                "posting_id": pid,
                "posted_at": j.get("releasedDate") or j.get("createdOn"),
            })
        if len(content) < limit:
            break
        offset += limit
        if offset > 2000:
            break
    return jobs
