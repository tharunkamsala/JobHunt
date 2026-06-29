#!/usr/bin/env python3
"""Smoke-test scrapers: each returned job must look like a real posting."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import PLAYWRIGHT_ENABLED
from scraper import scrape_company
from scraper import bigtech, overrides as ats_overrides
from scraper.posting_validation import job_has_posting_identity


def _playwright_browser_installed() -> bool:
    if not PLAYWRIGHT_ENABLED:
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


def _is_bigtech_company(name: str) -> bool:
    return bigtech.get_handler(name) is not None


def _is_override_ats_company(name: str) -> bool:
    return ats_overrides.lookup(name) is not None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--companies-json", type=Path, default=Path(__file__).resolve().parent / "data" / "companies.json")
    p.add_argument("--limit", type=int, default=12, help="How many companies to sample from the file")
    p.add_argument("--names", nargs="*", help="If set, only scrape these company names (exact match)")
    p.add_argument(
        "--ats-only",
        action="store_true",
        help="Validate only override ATS companies (skip bigtech/custom handlers).",
    )
    p.add_argument(
        "--include-bigtech-without-playwright",
        action="store_true",
        help="Do not auto-skip bigtech companies when Playwright browser binaries are missing.",
    )
    args = p.parse_args()

    by_name: dict[str, dict] = {}
    if args.companies_json.exists():
        try:
            for c in json.loads(args.companies_json.read_text()):
                if isinstance(c, dict) and (nm := (c.get("name") or "").strip()):
                    by_name[nm] = c
        except Exception:
            pass

    if args.names:
        targets: list[dict] = []
        for n in args.names:
            n = n.strip()
            if n in by_name:
                targets.append(dict(by_name[n]))
            else:
                targets.append({"name": n, "url": "https://example.com", "company_source": ""})
    else:
        if not args.companies_json.exists():
            print(f"Missing {args.companies_json}", file=sys.stderr)
            return 2
        companies = json.loads(args.companies_json.read_text())
        targets = [c for c in companies if isinstance(c, dict) and c.get("name")][: args.limit]

    bigtech_enabled = _playwright_browser_installed() or args.include_bigtech_without_playwright
    bad = 0
    ok = 0
    skipped = 0
    for c in targets:
        name = c.get("name") or "?"
        if args.ats_only and not _is_override_ats_company(name):
            print(f"SKIP {name}: not in override ATS set")
            skipped += 1
            continue
        if not bigtech_enabled and _is_bigtech_company(name):
            print(f"SKIP {name}: Playwright browsers not installed (run `playwright install` to include)")
            skipped += 1
            continue
        try:
            ats, jobs = scrape_company(c)
        except Exception as exc:
            print(f"FAIL {name}: scrape raised {exc!r}")
            bad += 1
            continue
        failures = [j for j in jobs if not job_has_posting_identity(j)]
        if failures:
            print(f"FAIL {name} ({ats}): {len(failures)} job(s) without posting identity")
            for j in failures[:3]:
                print(f"   title={j.get('title')!r} url={j.get('url')!r} posting_id={j.get('posting_id')!r}")
            bad += 1
        else:
            print(f"OK   {name} ({ats}): {len(jobs)} job(s), all have posting URLs/ids")
            ok += 1
    print(f"\nSummary: {ok} ok, {bad} failed, {skipped} skipped")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
