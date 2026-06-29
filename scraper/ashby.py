"""Ashby public posting API.
   GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=false
"""
from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


def fetch(slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    r = transport_fetch(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT,
        strategy=FetchStrategy.REQUESTS,
        auto_escalate=False,
    )
    if r.status_code != 200 or not r.text:
        return []
    try:
        data = r.json()
    except Exception:
        return []
    jobs: list[dict] = []
    for j in data.get("jobs", []):
        aid = j.get("id")
        jobs.append({
            "title": j.get("title"),
            "location": j.get("locationName") or j.get("location"),
            "url": j.get("jobUrl") or j.get("applyUrl"),
            "posting_id": str(aid) if aid is not None else None,
            "posted_at": j.get("publishedAt") or j.get("updatedAt"),
        })
    return jobs
