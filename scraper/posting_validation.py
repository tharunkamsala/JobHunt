"""Require each scraped row to reference a concrete job posting (stable id or URL shape)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .posting_id import infer_from_url

_URL_HINT = re.compile(
    r"/job[s]?/|/position[s]?/|/posting[s]?/|/openings?/|/roles?/|"
    r"gh_jid=|/details/|/applications/|/opportunities/|"
    r"icims\.com/jobs/|successfactors\.com/|"
    r"apply\.workable\.com/[^/]+/j/|"
    r"oraclecloud\.com/hcmUI/CandidateExperience/|"
    r"talentbrew\.com/[^?\s]+/job/",
    re.I,
)


def url_looks_like_posting_page(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    if infer_from_url(u):
        return True
    if _URL_HINT.search(u):
        return True
    path = urlparse(u).path or ""
    segments = [s for s in path.split("/") if s]
    if any(s.isdigit() and len(s) >= 4 for s in segments[-3:]):
        return True
    return False


def job_has_posting_identity(job: dict) -> bool:
    """True if the row has a coalesced posting_id or a URL that points at a specific posting."""
    if (job.get("posting_id") or "").strip():
        return True
    u = job.get("url")
    if isinstance(u, str) and u.strip():
        return url_looks_like_posting_page(u)
    return False
