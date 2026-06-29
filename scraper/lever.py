"""Lever public API: https://api.lever.co/v0/postings/{slug}?mode=json"""
from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


def fetch(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
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
    from datetime import datetime as _dt, timezone as _tz
    for j in data:
        cats = j.get("categories") or {}
        created = j.get("createdAt")
        posted_iso = None
        if isinstance(created, (int, float)) and created > 0:
            # Lever returns ms since epoch.
            posted_iso = _dt.fromtimestamp(created / 1000, tz=_tz.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        lid = j.get("id")
        jobs.append({
            "title": j.get("text"),
            "location": cats.get("location"),
            "url": j.get("hostedUrl") or j.get("applyUrl"),
            "posting_id": str(lid) if lid is not None else None,
            "posted_at": posted_iso,
            "descriptionPlain": j.get("descriptionPlain"),
            "description": j.get("description"),
        })
    return jobs
