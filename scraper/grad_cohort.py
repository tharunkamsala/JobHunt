"""Match job titles to a graduation cohort (e.g. Class of 2027).

Recruiter intent for May 2027 CS grads:
  - Full-time university / campus / new-grad / entry-level engineering roles
  - Titles that name the class year (2027, '27) or are year-agnostic new grad
  - Exclude titles that name a different class year (2025, 2026, 2028, …)
"""
from __future__ import annotations

import re

from config import DEFAULT_GRAD_COHORT_YEAR, SUPPORTED_GRAD_COHORT_YEARS

_CLASS_OF = re.compile(r"class\s+of\s*['\-]?\s*(20)?(\d{2})\b", re.I)
_NEW_GRAD_YEAR = re.compile(
    r"new\s*grad(?:uate)?\s*['\-]?\s*(20)?(\d{2})\b", re.I
)
_GRAD_YEAR_APOSTROPHE = re.compile(
    r"(?:class\s+of|new\s*grad|grad|start|may|spring|fall|summer|january|june)\s*['\-]?(2[4-9])\b",
    re.I,
)
_FULL_YEAR_IN_TITLE = re.compile(r"\b(20)(2[4-9])\b", re.I)

# Entry / new-grad signals when category alone is not enough.
_NEW_GRAD_TITLE_SIGNALS = re.compile(
    r"\b("
    r"new\s*grad|new\s*graduate|university\s+hire|campus\s+hire|campus\s+recruit|"
    r"college\s+grad|recent\s+grad|entry[-\s]*level|early\s+career|emerging\s+talent|"
    r"university\s+(software|swe|sde|ml|ai|data|cloud|platform|engineer|developer)|"
    r"graduate\s+(software|engineer|developer|program|rotation)|"
    r"rotational\s+(engineer|program|development)|technology\s+development\s+program|"
    r"associate\s+(software|ml|machine|data|cloud|security|research)\s+engineer|"
    r"junior\s+(software|engineer|developer)|"
    r"0\s*[-–]?\s*1\s+years?|0\s+years?\s+(of\s+)?experience|"
    r"bachelor'?s?\s+(degree\s+)?required|bs\s+in\s+(cs|computer|ece|engineering)"
    r")\b",
    re.I,
)

_INTERNSHIP_CAT = frozenset({
    "Summer Intern",
    "Fall Co-op / Intern",
    "Spring Intern",
})


def _year_from_groups(g1: str | None, g2: str) -> int:
    if g1:
        return int(g1 + g2)
    y = int(g2)
    return 2000 + y if y < 100 else y


def extract_grad_years(title: str) -> set[int]:
    """Years explicitly tied to graduation / class / new-grad in the title."""
    if not title:
        return set()
    t = title.strip()
    years: set[int] = set()

    for m in _CLASS_OF.finditer(t):
        years.add(_year_from_groups(m.group(1), m.group(2)))

    for m in _NEW_GRAD_YEAR.finditer(t):
        years.add(_year_from_groups(m.group(1), m.group(2)))

    for m in _GRAD_YEAR_APOSTROPHE.finditer(t):
        years.add(2000 + int(m.group(1)))

    # Full years near grad keywords only (avoid random product years).
    for m in _FULL_YEAR_IN_TITLE.finditer(t):
        y = int(m.group(1) + m.group(2))
        if y not in SUPPORTED_GRAD_COHORT_YEARS and not (2024 <= y <= 2030):
            continue
        start = max(0, m.start() - 30)
        end = min(len(t), m.end() + 30)
        window = t[start:end].lower()
        if re.search(
            r"grad|class\s+of|university|campus|hire|start|may|spring|fall|summer|january|june|intern",
            window,
        ):
            years.add(y)

    return years


def is_new_grad_eligible(title: str, primary_category: str | None = None) -> bool:
    """Roles a 2027 CS grad would apply to (not internships unless conversion)."""
    cat = (primary_category or "").strip()
    if cat == "New Grad":
        return True
    if cat in _INTERNSHIP_CAT:
        return bool(re.search(r"conversion|return\s+offer|full[-\s]*time", title or "", re.I))
    if cat in {"SDE 1", "SDE 2", "AI / ML", "Database", "Infrastructure / DevOps"}:
        if _NEW_GRAD_TITLE_SIGNALS.search(title or ""):
            return True
        # University-titled SDE without "intern" is almost always new grad.
        if re.search(r"\buniversity\b", title or "", re.I) and not re.search(
            r"\bintern\b", title or "", re.I
        ):
            return True
    return bool(_NEW_GRAD_TITLE_SIGNALS.search(title or ""))


def matches_grad_cohort(
    title: str,
    target_year: int,
    *,
    strict: bool = False,
    primary_category: str | None = None,
) -> bool:
    """
    strict=False (default): new-grad-eligible AND (names target year OR no year stated)
                            AND NOT a different class year only.
    strict=True: title must explicitly name target_year.
    """
    if target_year not in SUPPORTED_GRAD_COHORT_YEARS:
        return True
    if not is_new_grad_eligible(title, primary_category):
        return False

    years = extract_grad_years(title)
    if strict:
        if target_year in years:
            return True
        short = str(target_year)[-2:]
        return bool(re.search(rf"['\']{short}\b", title or "", re.I))

    if years:
        if target_year in years:
            return True
        # Wrong cohort — e.g. Class of 2026 when targeting 2027.
        return False

    # No year in title — open new-grad / university hire (typical Amazon, Google).
    return True


def grad_cohort_config() -> dict:
    return {
        "default_year": DEFAULT_GRAD_COHORT_YEAR,
        "years": list(SUPPORTED_GRAD_COHORT_YEARS),
    }
