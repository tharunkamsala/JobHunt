"""Role matching + seniority filter.

Each job is assigned exactly **one** primary category (the first match in
``CATEGORY_PRIORITY``). This keeps filters strict: e.g. "Fall 2026" roles
land only under Fall, SDE I only under SDE 1, without cross-listing in
other buckets.
"""
import re

from config import (
    ROLE_FILTERS,
    SENIORITY_EXCLUDES,
    NON_ENGINEERING_EXCLUDES,
    NON_CS_FIELD_EXCLUDES,
    INTERNSHIP_ONLY_MODE,
    INTERNSHIP_TITLE_PATTERNS,
    CS_DOMAIN_PATTERNS,
    SEASONAL_TECH_INTERNSHIP_PATTERNS,
)

_COMPILED = {
    name: [re.compile(p, re.IGNORECASE) for p in patterns]
    for name, patterns in ROLE_FILTERS.items()
}
_EXCLUDES = [re.compile(p, re.IGNORECASE) for p in SENIORITY_EXCLUDES]
_NON_ENG = [re.compile(p, re.IGNORECASE) for p in NON_ENGINEERING_EXCLUDES]
_NON_CS_FIELD = [re.compile(p, re.IGNORECASE) for p in NON_CS_FIELD_EXCLUDES]
_INTERNSHIP = [re.compile(p, re.IGNORECASE) for p in INTERNSHIP_TITLE_PATTERNS]
_CS_DOMAIN = [re.compile(p, re.IGNORECASE) for p in CS_DOMAIN_PATTERNS]
_SEASONAL_TECH = [re.compile(p, re.IGNORECASE) for p in SEASONAL_TECH_INTERNSHIP_PATTERNS]

# First matching category wins (most specific / seasonal first).
CATEGORY_PRIORITY: tuple[str, ...] = (
    "Summer Intern",
    "Fall Co-op / Intern",
    "Spring Intern",
    "New Grad",
    "SDE 2",
    "SDE 1",
    "AI / ML",
    "Database",
    "Infrastructure / DevOps",
)


def is_internship_like(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _INTERNSHIP)


def is_cs_domain(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _CS_DOMAIN)


def is_seasonal_tech_internship(title: str) -> bool:
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _SEASONAL_TECH)


def is_too_senior(title: str) -> bool:
    """Return True if the title indicates >3 YoE (senior / staff / etc.)."""
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _EXCLUDES)


def is_non_engineering(title: str) -> bool:
    """Return True if the title is clearly a non-engineering role that
    happens to share keywords with our target categories (AE, Sales, TPM,
    Recruiter, UX Designer, etc.)."""
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _NON_ENG)


def is_non_cs_field(title: str) -> bool:
    """Return True for engineering/science disciplines outside CS/CSE."""
    if not title:
        return False
    t = title.strip()
    return any(rx.search(t) for rx in _NON_CS_FIELD)


def _first_matching_category(title: str) -> str | None:
    t = title.strip()
    for cat in CATEGORY_PRIORITY:
        for r in _COMPILED.get(cat, []):
            if r.search(t):
                return cat
    return None


def primary_category(title: str) -> str | None:
    """Return a single best-fit category name, or None."""
    if not title:
        return None
    if is_too_senior(title) or is_non_engineering(title) or is_non_cs_field(title):
        return None
    t = title.strip()

    # Intern-like titles ("Intern", "Internship", "Co-op", "Student Worker",
    # "Apprentice", ...) always belong in an intern bucket — even if the title
    # also mentions "data engineer" or "ML" which would otherwise route to
    # Database / AI-ML and then get dropped when those categories are off.
    # We pick the most specific season the title names; otherwise default to
    # Summer Intern as the catch-all bucket for season-less internships.
    if is_internship_like(t):
        # Require a tech-domain keyword (or seasonal-tech pattern) so we
        # don't pull in HR / marketing / legal internships that share the
        # word "intern".
        if not (is_cs_domain(t) or is_seasonal_tech_internship(t)):
            return None
        # Season detection — explicit season name OR adjacent year hint.
        # Fall and co-op programs are typically autumn/year-long, so any
        # "co-op" with no other season specified routes to Fall Co-op.
        is_fall   = bool(re.search(r"\b(fall|autumn)\b",   t, re.IGNORECASE))
        is_spring = bool(re.search(r"\b(spring|winter)\b", t, re.IGNORECASE))
        is_summer = bool(re.search(r"\bsummer\b",          t, re.IGNORECASE))
        is_coop   = bool(re.search(r"\bco[-\s]?op\b|\bcoop\b", t, re.IGNORECASE))
        if is_fall:
            return "Fall Co-op / Intern"
        if is_spring:
            return "Spring Intern"
        if is_summer:
            return "Summer Intern"
        if is_coop:
            return "Fall Co-op / Intern"
        # Plain "Intern" / "Internship" / "Student Worker" with no season
        # named — default to the Summer bucket which is the largest cohort.
        return "Summer Intern"

    matched = _first_matching_category(t)
    if matched in {"Summer Intern", "Fall Co-op / Intern", "Spring Intern"}:
        # Reached here only via non-intern-like titles like "Fall 2026
        # Software Engineer". Still require a tech keyword.
        if not is_seasonal_tech_internship(title):
            return None
    if INTERNSHIP_ONLY_MODE:
        # Keep explicit New Grad roles even when internship mode is enabled.
        if matched != "New Grad" and not is_internship_like(title):
            return None
    # All kept roles must be CS/CSE-related (not just internships).
    if matched and not is_cs_domain(t):
        return None
    return matched


def match_categories(title: str) -> list[str]:
    """Return [primary_category] or []. Kept as a one-element list for JSON storage."""
    p = primary_category(title)
    return [p] if p else []


def matches_target(title: str) -> bool:
    return bool(match_categories(title))
