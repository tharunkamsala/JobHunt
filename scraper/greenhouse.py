"""Greenhouse public Job Board API: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs

Uses `?content=true` to get the richer response that includes `offices[]`
with real city/state data. When the primary `location.name` field is a
vague placeholder like "In-Office" or "Hybrid", we fall back to the first
office entry so the outer location filter can correctly identify US roles.
"""
from __future__ import annotations

from config import REQUEST_TIMEOUT, USER_AGENT
from .transport import FetchStrategy, fetch as transport_fetch


# Vague location strings that Greenhouse sometimes emits when a company
# hasn't filled in a proper city.  For these we prefer the offices[] data.
_VAGUE_LOCATIONS = {
    "in-office", "on-site", "onsite", "on site", "hybrid",
    "in office", "office", "on-site/remote", "hybrid remote",
    "flexible", "tbd", "n/a", "",
}


def _resolve_location(j: dict) -> str | None:
    """Return the best location string for a Greenhouse job dict.

    Priority:
    1. job.location.name  — if it's a real city/state (not a vague placeholder)
    2. offices[0].name    — first office listed (present when ?content=true used)
    3. None               — unknown; outer filter will drop this job
    """
    loc: str | None = (j.get("location") or {}).get("name")
    if loc and loc.strip().lower() not in _VAGUE_LOCATIONS:
        return loc.strip()

    # Fall back to offices data (only present with ?content=true).
    offices: list[dict] = j.get("offices") or []
    if offices:
        # Collect all office names so we expose multi-office strings like
        # "Austin, TX; Washington, DC" which the US filter can evaluate.
        names = [o.get("name", "").strip() for o in offices if o.get("name", "").strip()]
        if names:
            # If the vague location was present but we have offices, prefer offices.
            return "; ".join(names)

    # Return original location even if vague — better than None for display.
    return loc.strip() if loc else None


def fetch(slug: str) -> list[dict]:
    """Fetch all jobs for a Greenhouse board slug.

    Attempts the richer `?content=true` endpoint first (returns offices[],
    departments[], etc.). Falls back to the plain endpoint on any failure.
    """
    base_url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}

    # Try the rich endpoint first.
    data: dict | None = None
    for url in (f"{base_url}?content=true", base_url):
        r = transport_fetch(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            strategy=FetchStrategy.REQUESTS,
            auto_escalate=False,
        )
        if r.status_code != 200 or not r.text:
            continue
        try:
            data = r.json()
            break  # success
        except Exception:
            continue

    if not data:
        return []

    jobs: list[dict] = []
    for j in data.get("jobs", []):
        jid = j.get("id")
        jobs.append({
            "title":      j.get("title"),
            "location":   _resolve_location(j),
            "url":        j.get("absolute_url"),
            "posting_id": str(jid) if jid is not None else None,
            # Greenhouse gives an ISO string directly.
            "posted_at":  j.get("first_published") or j.get("updated_at"),
        })
    return jobs
