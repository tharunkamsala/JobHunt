#!/usr/bin/env python3
"""Diagnose why new grad roles from specific companies aren't being captured.

Probes the raw ATS APIs for Uber, Anthropic, Airbnb (and others) and shows:
1. Total raw jobs returned from the API
2. Which titles look like new-grad/entry-level roles
3. Which of those pass the current filters
4. Which get rejected and WHY (seniority, non-eng, no category, location)
"""
import json
import re
import sys

# Make sure we can import project modules
sys.path.insert(0, ".")

from config import ROLE_FILTERS, SENIORITY_EXCLUDES, NON_ENGINEERING_EXCLUDES
from scraper import greenhouse, lever, ashby, smartrecruiters
from scraper.filters import (
    match_categories, primary_category, is_too_senior,
    is_non_engineering, is_internship_like, is_cs_domain,
)
from scraper.location import is_usa
from scraper.overrides import OVERRIDES, normalize

# --- New-grad-ish keywords to look for in raw titles ---
NEWGRAD_KEYWORDS = re.compile(
    r"new\s*grad|entry.?level|early\s*career|junior|university|"
    r"graduate|class\s+of|campus|associate\s+(software|engineer)|"
    r"rotational|fresh|recent\s+grad|sde\s*[i1]|swe\s*[i1]|"
    r"software\s+engineer\s+[i1]|software\s+engineer\b|"
    r"software\s+developer|engineer\s+[i1]",
    re.IGNORECASE,
)

# Companies to check
TARGETS = {
    "Uber":      ("smartrecruiters", "uber"),
    "Anthropic": ("greenhouse",      "anthropic"),
    "Airbnb":    ("greenhouse",      "airbnb"),
    "Stripe":    ("greenhouse",      "stripe"),
    "Coinbase":  ("greenhouse",      "coinbase"),
    "Databricks":("greenhouse",      "databricks"),
    "Discord":   ("greenhouse",      "discord"),
    "Lyft":      ("greenhouse",      "lyft"),
    "Pinterest": ("greenhouse",      "pinterest"),
    "Reddit":    ("greenhouse",      "reddit"),
    "Roblox":    ("greenhouse",      "roblox"),
    "OpenAI":    ("ashby",           "openai"),
}


def fetch_raw(ats: str, handle: str) -> list[dict]:
    if ats == "greenhouse":
        return greenhouse.fetch(handle)
    if ats == "lever":
        return lever.fetch(handle)
    if ats == "ashby":
        return ashby.fetch(handle)
    if ats == "smartrecruiters":
        return smartrecruiters.fetch(handle)
    return []


def diagnose_title(title: str) -> dict:
    """Return a diagnosis of why a title does or doesn't pass filters."""
    cats = match_categories(title)
    cat = primary_category(title)
    senior = is_too_senior(title)
    non_eng = is_non_engineering(title)
    intern = is_internship_like(title)
    cs = is_cs_domain(title)

    # Find which seniority pattern matched
    senior_match = None
    if senior:
        for p in SENIORITY_EXCLUDES:
            if re.search(p, title, re.IGNORECASE):
                senior_match = p
                break

    return {
        "category": cat,
        "categories": cats,
        "is_senior": senior,
        "senior_pattern": senior_match,
        "is_non_eng": non_eng,
        "is_intern": intern,
        "is_cs": cs,
    }


def main():
    for company, (ats, handle) in TARGETS.items():
        print(f"\n{'='*80}")
        print(f"  {company}  (ATS: {ats}, handle: {handle})")
        print(f"{'='*80}")

        raw = fetch_raw(ats, handle)
        print(f"  Total raw jobs from API: {len(raw)}")

        if not raw:
            print("  ⚠️  NO JOBS RETURNED FROM API!")
            continue

        # Separate into potential new-grad and everything else
        potential_ng = []
        passed_filter = []
        rejected = []

        for j in raw:
            title = (j.get("title") or "").strip()
            loc = (j.get("location") or "").strip()
            if not title:
                continue

            diag = diagnose_title(title)
            usa = is_usa(loc) if loc else False

            entry = {
                "title": title,
                "location": loc,
                "url": j.get("url", ""),
                **diag,
                "is_usa": usa,
            }

            if diag["categories"]:
                if usa or not loc:
                    passed_filter.append(entry)
                else:
                    entry["reject_reason"] = "non-US location"
                    rejected.append(entry)
            else:
                reasons = []
                if diag["is_senior"]:
                    reasons.append(f"seniority ({diag['senior_pattern']})")
                if diag["is_non_eng"]:
                    reasons.append("non-engineering")
                if not diag["is_cs"]:
                    reasons.append("not CS domain")
                if not reasons:
                    reasons.append("no category match")
                entry["reject_reason"] = "; ".join(reasons)
                rejected.append(entry)

            if NEWGRAD_KEYWORDS.search(title):
                potential_ng.append(entry)

        # --- Report ---
        print(f"\n  📊 Potential new-grad/entry-level titles (keyword match): {len(potential_ng)}")
        for e in potential_ng:
            status = "✅" if e["categories"] else "❌"
            cat = e["category"] or "NONE"
            reasons = e.get("reject_reason", "")
            loc_flag = "🇺🇸" if e["is_usa"] else "🌍"
            print(f"    {status} [{cat:20s}] {loc_flag} {e['title']}")
            if reasons:
                print(f"       └─ REJECTED: {reasons}")

        print(f"\n  ✅ Jobs that PASS all filters (category + US): {len(passed_filter)}")
        # Show category breakdown
        cat_counts: dict[str, int] = {}
        for e in passed_filter:
            c = e["category"] or "?"
            cat_counts[c] = cat_counts.get(c, 0) + 1
        for c, n in sorted(cat_counts.items()):
            print(f"      {c}: {n}")

        # Show sample new-grad roles that pass
        ng_passed = [e for e in passed_filter if e.get("category") == "New Grad"]
        if ng_passed:
            print(f"\n  🎓 New Grad roles that PASS ({len(ng_passed)}):")
            for e in ng_passed[:15]:
                print(f"      • {e['title']}  [{e['location']}]")

        # Show titles that look new-grad-ish but got rejected
        ng_rejected = [e for e in potential_ng if not e["categories"]]
        if ng_rejected:
            print(f"\n  ❌ Potential new-grad titles REJECTED ({len(ng_rejected)}):")
            for e in ng_rejected[:15]:
                print(f"      • {e['title']}  [{e['location']}]")
                print(f"        Reason: {e.get('reject_reason', '?')}")

        # Show some SWE/engineer titles that got rejected (might be entry-level)
        swe_rejected = [
            e for e in rejected
            if re.search(r"software\s+engineer|swe|sde", e["title"], re.IGNORECASE)
            and not e.get("is_senior")
            and not e.get("is_non_eng")
            and e.get("is_usa", True)
        ][:10]
        if swe_rejected:
            print(f"\n  ⚠️ SWE titles rejected (potential false negatives):")
            for e in swe_rejected:
                print(f"      • {e['title']}  [{e['location']}]")
                print(f"        Reason: {e.get('reject_reason', '?')}")


if __name__ == "__main__":
    main()
