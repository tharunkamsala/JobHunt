"""SmartRecruiters public API:
   https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=0
"""
import requests

from config import REQUEST_TIMEOUT, USER_AGENT


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
            jobs.append({
                "title": j.get("name"),
                "location": loc_str or None,
                "url": (j.get("ref") and f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}") or None,
                "posting_id": str(sr_id) if sr_id is not None else None,
                "posted_at": j.get("releasedDate") or j.get("createdOn"),
            })
        if len(content) < limit:
            break
        offset += limit
        if offset > 2000:
            break
    return jobs
