"""Eightfold AI ATS fetcher.

Eightfold hosts many enterprise career sites at
``https://<tenant>.eightfold.ai`` (e.g. ``aexp.eightfold.ai``,
``paypal.eightfold.ai``).

The public JSON search endpoint is:
    GET https://<tenant>.eightfold.ai/api/apply/v2/jobs
        ?domain=<tenant>.com
        &number=<page_size>
        &offset=<page_offset>
        &query=<free_text>
        &location=<optional>

This handler lets us stop using the opaque HTML fallback for companies
like American Express and PayPal.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import requests

from config import REQUEST_TIMEOUT, USER_AGENT


log = logging.getLogger(__name__)


HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _host_for(slug: str) -> str:
    if "." in slug:
        return slug
    return f"{slug}.eightfold.ai"


def _domain_for(slug: str) -> str:
    # Most sites use tenant.com as domain param, but a handful use custom
    # values. Support common aliases here.
    aliases = {
        "americanexpress": "aexp.com",
        "aexp":            "aexp.com",
        "paypal":          "paypal.com",
    }
    return aliases.get(slug, f"{slug}.com")


def _posted_at(v) -> str | None:
    if not v:
        return None
    if isinstance(v, (int, float)):
        try:
            # Eightfold returns millis.
            ts = v / 1000 if v > 10_000_000_000 else v
            return datetime.fromtimestamp(ts, tz=timezone.utc)\
                    .replace(tzinfo=None).isoformat(timespec="seconds")
        except Exception:
            return None
    return None


def fetch(slug: str) -> list[dict]:
    host = _host_for(slug)
    domain = _domain_for(slug)
    jobs: list[dict] = []
    seen: set[str] = set()

    queries = ["software engineer", "machine learning", "data engineer", "new grad"]
    for q in queries:
        offset = 0
        for _ in range(4):  # up to 4 pages per query
            url = (
                f"https://{host}/api/apply/v2/jobs?domain={domain}"
                f"&number=50&offset={offset}&query={requests.utils.quote(q)}"
                f"&location=United%20States"
            )
            try:
                for attempt in range(1, 4):
                    try:
                        r = requests.get(url, headers={
                            **HEADERS,
                            "Referer": f"https://{host}/careers",
                            "Origin":  f"https://{host}",
                        }, timeout=REQUEST_TIMEOUT)
                        if r.status_code < 500:
                            break
                        if attempt < 3:
                            wait = 2 ** (attempt - 1)
                            time.sleep(wait)
                    except (requests.Timeout, requests.ConnectionError):
                        if attempt == 3:
                            break
                        wait = 2 ** (attempt - 1)
                        time.sleep(wait)
            except Exception:
                break
            if r.status_code != 200:
                break
            try:
                data = r.json()
            except Exception:
                break
            positions = data.get("positions") or data.get("jobs") or []
            if not positions:
                break
            for p in positions:
                pid = str(p.get("id") or p.get("display_job_id") or "")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                loc = p.get("location") or ", ".join(p.get("locations") or []) or None
                canonical = p.get("canonicalPositionUrl") or p.get("positionUrl")
                if not canonical:
                    canonical = f"https://{host}/careers/job/{pid}?domain={domain}"
                jobs.append({
                    "title":     p.get("name") or p.get("title"),
                    "location":  loc,
                    "url":       canonical,
                    "posting_id": pid,
                    "posted_at": _posted_at(p.get("t_create") or p.get("t_update")),
                })
            total = data.get("count") or data.get("total_count") or 0
            offset += 50
            if offset >= int(total or 0) or len(positions) < 50:
                break

    return jobs
