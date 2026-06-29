"""Best-effort employer / ATS job posting id (requisition id), not our DB id."""
from __future__ import annotations

import re
from typing import Any, Optional

# Extract from public job URLs when the API did not give a clean id.
_URL_PATTERNS: list[re.Pattern[str]] = [
    # Greenhouse vanity sites (e.g. stripe.com/jobs/search?gh_jid=…)
    re.compile(r"[\?&]gh_jid=(\d+)", re.I),
    re.compile(r"metacareers\.com/jobs/(\d+)", re.I),
    re.compile(r"careers\.microsoft\.com/[^#]*/job/(\d+)", re.I),
    re.compile(r"jobs\.apple\.com/[^#]*/details/([0-9]+-[0-9]+)", re.I),
    re.compile(
        r"google\.com/about/careers/applications/jobs/results/(\d+)(?:/|[\"'\s])", re.I
    ),
    re.compile(r"boards\.greenhouse\.io/[^#]+/jobs/(\d+)", re.I),
    re.compile(
        r"job-boards\.greenhouse\.io/[^#]+/jobs/(\d+)", re.I
    ),  # some boards
    re.compile(
        r"jobs\.lever\.co/[^/]+/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.I,
    ),
    re.compile(
        r"ashbyhq\.com/[^#]*/(?:jobs/)?[a-f0-9-]{8}-[a-f0-9-]{4}-[a-f0-9-]{4}-[a-f0-9-]{4}-[a-f0-9-]{12}/([a-f0-9-]{8})",
        re.I,
    ),
    re.compile(r"myworkdayjobs\.com/[^#]+/job/[^/]*/([A-Z0-9][A-Z0-9_\-/+]{4,80})", re.I),
    re.compile(
        r"wd\d+\.myworkdayjobs\.com/[^#]+/job/[^/]*/([A-Z0-9_\-/+]{2,100})", re.I
    ),
    re.compile(
        r"smartrecruiters\.com/[^#]+/(\d+)", re.I
    ),
    re.compile(
        r"careers\.amazon\.(com|in)/[^#]*/(job/)?(\d{4,20})", re.I
    ),
    re.compile(
        r"amazon\.jobs/[^#]*/jobs/(\d{3,20})", re.I
    ),
]


def _norm(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    return s[:256]


def infer_from_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    u = url.strip()
    for rx in _URL_PATTERNS:
        m = rx.search(u)
        if m:
            g = m.group(m.lastindex or 1) if m.lastindex else m.group(1)
            g = (g or "").strip()
            if 2 <= len(g) <= 200:
                return g
    return None


def coalesce(raw: Any, url: str | None) -> str | None:
    """Use explicit id from the ATS response, else parse the listing URL."""
    n = _norm(raw)
    if n:
        return n
    return infer_from_url(url)
