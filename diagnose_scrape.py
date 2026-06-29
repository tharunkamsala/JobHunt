"""Time + verify a real subset scrape end-to-end.
Runs N companies in parallel exactly the way the production sweep does."""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from db import init_db, upsert_jobs, reconcile_company_jobs, fetch_jobs, stats
from scraper import scrape_company

SAMPLE = [
    {"name": "Stripe",        "url": "https://stripe.com/jobs"},
    {"name": "Airbnb",        "url": "https://careers.airbnb.com/"},
    {"name": "Datadog",       "url": "https://www.datadoghq.com/careers/"},
    {"name": "Cloudflare",    "url": "https://www.cloudflare.com/careers/"},
    {"name": "OpenAI",        "url": "https://openai.com/careers"},
    {"name": "NVIDIA",        "url": "https://www.nvidia.com/en-us/about-nvidia/careers/"},
    {"name": "Roblox",        "url": "https://corp.roblox.com/careers/"},
    {"name": "Coinbase",      "url": "https://www.coinbase.com/careers"},
    {"name": "Anthropic",     "url": "https://www.anthropic.com/careers"},
    {"name": "Notion",        "url": "https://www.notion.so/careers"},
    {"name": "Pinterest",     "url": "https://www.pinterestcareers.com/"},
    {"name": "Snowflake",     "url": "https://careers.snowflake.com/"},
]


def run_one(c: dict) -> dict:
    t0 = time.time()
    try:
        source, jobs = scrape_company(c)
        found, new, _, seen_fp = upsert_jobs(c["name"], source, jobs)
        deactivated = reconcile_company_jobs(c["name"], seen_fp, source=source)
        return {
            "company": c["name"], "source": source,
            "raw_kept": len(jobs), "found": found, "new": new,
            "deactivated": deactivated, "elapsed": round(time.time() - t0, 1),
            "ok": True,
        }
    except Exception as e:
        return {
            "company": c["name"], "ok": False, "error": f"{type(e).__name__}: {e}",
            "elapsed": round(time.time() - t0, 1),
        }


if __name__ == "__main__":
    init_db()
    print(f"Scraping {len(SAMPLE)} companies in parallel (12 workers)...")
    t0 = time.time()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(run_one, c): c for c in SAMPLE}
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            tag = "OK" if r.get("ok") else "ERR"
            extra = (
                f"src={r.get('source','-'):<20} kept={r.get('raw_kept','?'):<4} "
                f"found={r.get('found','?'):<4} new={r.get('new','?'):<4}"
                if r.get("ok") else r.get("error", "")
            )
            print(f"  [{tag}] {r['company']:<14} ({r['elapsed']:>5}s)  {extra}")

    elapsed = round(time.time() - t0, 1)
    total_kept = sum(int(r.get("raw_kept") or 0) for r in results if r.get("ok"))
    total_new  = sum(int(r.get("new") or 0)      for r in results if r.get("ok"))
    print(f"\nWall-clock: {elapsed}s  |  total kept: {total_kept}  |  total new: {total_new}")

    s = stats()
    print(f"DB stats now: total={s.get('total')}  by_category={s.get('by_category')}")

    print("\nSample of recent intern/new-grad rows now in DB:")
    rows = fetch_jobs(limit=12, since_minutes=60)
    for r in rows[:12]:
        print(f"  {r.get('category','?'):<22} | {r.get('company',''):<14} | {(r.get('title') or '')[:80]}")
