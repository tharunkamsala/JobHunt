"""Workable public widget API scraper.

Many Workable-hosted careers pages expose their jobs through:
    https://apply.workable.com/api/v1/widget/accounts/{slug}
"""
from __future__ import annotations

from datetime import datetime

from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
}


def _to_iso(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, fmt).isoformat(timespec="seconds")
        except Exception:
            continue
    return None


def fetch(slug: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{slug}"
    r = transport_fetch(
        url,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        expect="json",
        strategy=FetchStrategy.REQUESTS,
        referer_url=f"https://apply.workable.com/{slug}/",
    )
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except Exception:
        return []

    jobs: list[dict] = []
    for job in data.get("jobs", []) or []:
        locations = job.get("locations") or []
        loc = None
        if locations:
            first = locations[0] or {}
            parts = [first.get("city"), first.get("region"), first.get("country")]
            loc = ", ".join(p for p in parts if p) or None
        if not loc:
            parts = [job.get("city"), job.get("state"), job.get("country")]
            loc = ", ".join(p for p in parts if p) or None
        jobs.append({
            "title": job.get("title"),
            "location": loc,
            "url": job.get("url") or job.get("shortlink") or job.get("application_url"),
            "posting_id": job.get("shortcode"),
            "posted_at": _to_iso(job.get("published_on") or job.get("created_at")),
        })
    return jobs
