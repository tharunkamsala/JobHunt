#!/usr/bin/env python3
"""Deactivate jobs that no longer pass CSE/CS filters (run after filter updates)."""
from __future__ import annotations

import json

from config import EXCLUDED_COMPANIES, DEFAULT_SCRAPE_CATEGORIES
from db import connect, init_db, set_enabled_scrape_categories
from scraper.filters import match_categories
from scraper.html_text import strip_html


def main() -> None:
    init_db()
    # Keep all CS role buckets enabled for scraping (SDE, intern, ML, etc.).
    set_enabled_scrape_categories(list(DEFAULT_SCRAPE_CATEGORIES))
    deactivated = 0
    excluded = 0
    updated = 0
    desc_cleaned = 0
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, title, company, categories, description FROM jobs WHERE is_active = 1"
        ).fetchall()
        for row in rows:
            company = (row["company"] or "").strip()
            if company in EXCLUDED_COMPANIES:
                conn.execute("UPDATE jobs SET is_active = 0 WHERE id = ?", (row["id"],))
                excluded += 1
                continue
            title = row["title"] or ""
            cats = match_categories(title)
            if not cats:
                conn.execute("UPDATE jobs SET is_active = 0 WHERE id = ?", (row["id"],))
                deactivated += 1
                continue
            old = []
            try:
                old = json.loads(row["categories"] or "[]")
            except Exception:
                pass
            if old != cats:
                conn.execute(
                    "UPDATE jobs SET categories = ?, primary_category = ? WHERE id = ?",
                    (json.dumps(cats), cats[0], row["id"]),
                )
                updated += 1
            raw_desc = row["description"] or ""
            if raw_desc and ("<" in raw_desc or "&lt;" in raw_desc):
                clean = strip_html(raw_desc)
                if clean != raw_desc:
                    conn.execute(
                        "UPDATE jobs SET description = ? WHERE id = ?",
                        (clean, row["id"]),
                    )
                    desc_cleaned += 1
    print(
        f"Done. Deactivated {deactivated} non-CSE jobs, {excluded} excluded companies, "
        f"recategorized {updated}, cleaned {desc_cleaned} descriptions."
    )


if __name__ == "__main__":
    main()
