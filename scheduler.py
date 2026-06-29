"""Periodic scrape loop. Runs full sweeps, fast watchlist sweeps, and subsets."""
from __future__ import annotations

import argparse
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from config import (
    COMPANIES_JSON,
    DEFAULT_WATCHLIST_COMPANIES,
    EXTRA_COMPANIES_JSON,
    FAST_SCRAPE_INTERVAL_MIN,
    FAST_WATCHLIST_MAX_COMPANIES,
    SCRAPE_INTERVAL_MIN,
    SCRAPE_MAX_WORKERS,
)
from db import (
    get_watchlist_companies,
    init_db,
    prioritized_company_names,
    reconcile_company_jobs,
    record_run,
    record_scrape_state,
    upsert_jobs,
)
from scraper import scrape_company


log = logging.getLogger("scheduler")
_run_lock = threading.Lock()
_fast_lock = threading.Lock()

_status: dict = {
    "running": False,
    "current": None,
    "last_full_run": None,
    "last_full_new_jobs": 0,
    "last_full_duration_sec": 0,
    "fast_running": False,
    "fast_current": None,
    "last_fast_run": None,
    "last_fast_new_jobs": 0,
    "last_fast_duration_sec": 0,
    "watchlist_size": 0,
}

# Tracks on-demand (per-company) scrapes separately from the full/fast schedulers.
_subset_lock = threading.Lock()
_subset_status: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "companies": [],
    "current": None,
    "results": [],
}


def status() -> dict:
    s = dict(_status)
    s["watchlist"] = get_watchlist_companies()
    s["watchlist_size"] = len(s["watchlist"])
    return s


def subset_status() -> dict:
    return dict(_subset_status)


def _load_companies() -> list[dict]:
    if not COMPANIES_JSON.exists():
        from load_companies import main as load_main
        load_main()
    companies = json.loads(COMPANIES_JSON.read_text())
    if EXTRA_COMPANIES_JSON.exists():
        try:
            extras = json.loads(EXTRA_COMPANIES_JSON.read_text())
        except Exception:
            extras = []
        if isinstance(extras, list):
            by_name = {c.get("name"): c for c in companies if isinstance(c, dict) and c.get("name")}
            for c in extras:
                if not isinstance(c, dict):
                    continue
                name = (c.get("name") or "").strip()
                url = (c.get("url") or "").strip()
                if not name or not url:
                    continue
                merged = {
                    "category": c.get("category") or "Extra companies",
                    "name": name,
                    "industry": c.get("industry") or "",
                    "common_roles": c.get("common_roles") or "",
                    "url": url,
                    "h1b_level": c.get("h1b_level") or "Unknown / not H1B-listed",
                    "notes": c.get("notes") or "",
                    "company_source": "extra",
                }
                by_name[name] = merged
            companies = list(by_name.values())
    return companies


def _ordered_companies(companies: list[dict], watchlist_only: bool = False) -> list[dict]:
    ordered_names = prioritized_company_names(watchlist_only=watchlist_only)
    by_name = {c["name"]: c for c in companies if c.get("name")}
    ordered: list[dict] = []
    seen: set[str] = set()
    for name in ordered_names:
        if name in by_name:
            ordered.append(by_name[name])
            seen.add(name)
    for c in sorted(companies, key=lambda x: (x.get("name") or "").lower()):
        name = c.get("name") or ""
        if name and name not in seen:
            ordered.append(c)
    return ordered


def _scrape_one_company(c: dict, mode: str = "full") -> dict:
    """Run one company scrape + upsert + reconcile, returning a normalized payload."""
    company = c.get("name") or ""
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        source, jobs = scrape_company(c)
        found, new, _new_rows, seen_fingerprints = upsert_jobs(company, source, jobs)
        deactivated = reconcile_company_jobs(company, seen_fingerprints, source=source)
        record_run(company, source, started_at, True, found, new)
        record_scrape_state(company, mode, source, True, found, new)
        # Push new jobs to connected WebSocket clients in real time.
        if _new_rows:
            try:
                from app import notify_new_jobs
                notify_new_jobs(_new_rows)
            except Exception:
                pass  # WebSocket is best-effort; never block scraping.
        return {
            "ok": True,
            "company": company,
            "source": source,
            "found": found,
            "new": new,
            "deactivated": deactivated,
        }
    except Exception as e:
        log.exception(f"Error scraping {company}: {e}")
        record_run(company, "error", started_at, False, 0, 0, str(e)[:500])
        record_scrape_state(company, mode, "error", False, 0, 0)
        return {
            "ok": False,
            "company": company,
            "source": "error",
            "found": 0,
            "new": 0,
            "deactivated": 0,
            "error": str(e)[:300],
        }


def run_once() -> dict:
    """Scrape every company once. Safe to call repeatedly; won't overlap itself."""
    if not _run_lock.acquire(blocking=False):
        log.warning("Previous full sweep still running; skipping this trigger.")
        return {"skipped": True}
    try:
        _status["running"] = True
        start = datetime.now(timezone.utc)
        companies = _ordered_companies(_load_companies())
        total_new = 0
        total_found = 0
        total_deactivated = 0
        workers = max(1, min(int(SCRAPE_MAX_WORKERS), 16))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scrape") as pool:
            futures = {pool.submit(_scrape_one_company, c, "full"): c for c in companies}
            done = 0
            total = len(futures)
            for fut in as_completed(futures):
                res = fut.result()
                company = res["company"]
                source = res["source"]
                found = int(res.get("found") or 0)
                new = int(res.get("new") or 0)
                deactivated = int(res.get("deactivated") or 0)
                total_new += new
                total_found += found
                total_deactivated += deactivated
                done += 1
                _status["current"] = f"{company} ({done}/{total})"
                # Push scrape progress to WebSocket clients.
                try:
                    from app import notify_scrape_progress
                    notify_scrape_progress(company, "done", found, new, f"{done}/{total}")
                except Exception:
                    pass
                log.info(
                    f"[{company:<30}] {source:<14} found={found:<3} new={new:<3} inactive={deactivated}"
                )
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        _status["last_full_run"] = start.isoformat(timespec="seconds")
        _status["last_full_new_jobs"] = total_new
        _status["last_full_duration_sec"] = duration
        _status["watchlist_size"] = len(get_watchlist_companies())
        log.info(
            "Full sweep done. found=%s new=%s inactive=%s in %.1fs",
            total_found, total_new, total_deactivated, duration,
        )
        return {
            "found": total_found,
            "new": total_new,
            "deactivated": total_deactivated,
            "duration_sec": duration,
        }
    finally:
        _status["running"] = False
        _status["current"] = None
        _run_lock.release()


def run_fast_watchlist() -> dict:
    """Run a lightweight high-frequency sweep for configured watchlist companies."""
    if not _fast_lock.acquire(blocking=False):
        log.warning("Previous fast watchlist sweep still running; skipping this trigger.")
        return {"skipped": True}
    try:
        watch = set(get_watchlist_companies())
        _status["watchlist_size"] = len(watch)
        if not watch:
            return {"skipped": True, "reason": "watchlist empty"}
        companies = [c for c in _ordered_companies(_load_companies(), watchlist_only=True) if c.get("name") in watch]
        if not companies:
            return {"skipped": True, "reason": "watchlist not found"}
        if FAST_WATCHLIST_MAX_COMPANIES and len(companies) > FAST_WATCHLIST_MAX_COMPANIES:
            preferred = set(DEFAULT_WATCHLIST_COMPANIES)
            order = {c.get("name") or "": i for i, c in enumerate(companies)}
            companies = sorted(
                companies,
                key=lambda c: (
                    0 if (c.get("name") or "") in preferred else 1,
                    order.get(c.get("name") or "", 10**9),
                ),
            )[:FAST_WATCHLIST_MAX_COMPANIES]
        _status["fast_running"] = True
        start = datetime.now(timezone.utc)
        total_new = 0
        total_found = 0
        total_deactivated = 0
        for idx, c in enumerate(companies, start=1):
            _status["fast_current"] = f'{c["name"]} ({idx}/{len(companies)})'
            res = _scrape_one_company(c, "fast")
            total_new += int(res.get("new") or 0)
            total_found += int(res.get("found") or 0)
            total_deactivated += int(res.get("deactivated") or 0)
            # Push scrape progress to WebSocket clients.
            try:
                from app import notify_scrape_progress
                notify_scrape_progress(
                    c["name"], "done",
                    int(res.get("found") or 0), int(res.get("new") or 0),
                    f"{idx}/{len(companies)}",
                )
            except Exception:
                pass
            log.info(
                f'[fast {c["name"]:<25}] {res["source"]:<14} '
                f'found={int(res.get("found") or 0):<3} new={int(res.get("new") or 0):<3} '
                f'inactive={int(res.get("deactivated") or 0)}'
            )
        duration = (datetime.now(timezone.utc) - start).total_seconds()
        _status["last_fast_run"] = start.isoformat(timespec="seconds")
        _status["last_fast_new_jobs"] = total_new
        _status["last_fast_duration_sec"] = duration
        return {
            "found": total_found,
            "new": total_new,
            "deactivated": total_deactivated,
            "duration_sec": duration,
            "companies": [c["name"] for c in companies],
        }
    finally:
        _status["fast_running"] = False
        _status["fast_current"] = None
        _fast_lock.release()


def run_subset(names: list[str]) -> dict:
    """Scrape only the named companies. Can run alongside the background scheduler."""
    companies = _load_companies()
    by_name = {c["name"]: c for c in companies}
    wanted = [by_name[n] for n in names if n in by_name]
    missing = [n for n in names if n not in by_name]
    if not wanted:
        return {"started": False, "error": "no matching companies", "missing": missing}

    def _worker():
        if not _subset_lock.acquire(blocking=False):
            log.warning("Previous subset scrape still running; skipping new trigger.")
            return
        try:
            _subset_status["running"] = True
            _subset_status["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            _subset_status["finished_at"] = None
            _subset_status["companies"] = [c["name"] for c in wanted]
            _subset_status["current"] = None
            results = []
            for c in wanted:
                _subset_status["current"] = c["name"]
                res = _scrape_one_company(c, "subset")
                results.append(res)
                if res.get("ok"):
                    log.info(
                        f'[subset {c["name"]:<30}] {res["source"]:<14} '
                        f'found={int(res.get("found") or 0):<3} new={int(res.get("new") or 0):<3} '
                        f'inactive={int(res.get("deactivated") or 0)}'
                    )
            _subset_status["results"] = results
            _subset_status["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        finally:
            _subset_status["running"] = False
            _subset_status["current"] = None
            _subset_lock.release()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return {"started": True, "companies": [c["name"] for c in wanted], "missing": missing}


_scheduler: BackgroundScheduler | None = None


def start_background_scheduler() -> None:
    """Start APScheduler. Called by the Flask app at boot."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    init_db()
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_once,
        "interval",
        minutes=SCRAPE_INTERVAL_MIN,
        id="scrape_all",
        next_run_time=datetime.utcnow(),
    )
    _scheduler.add_job(
        run_fast_watchlist,
        "interval",
        minutes=FAST_SCRAPE_INTERVAL_MIN,
        id="scrape_watchlist",
        next_run_time=datetime.utcnow(),
    )
    _scheduler.start()
    log.info(
        "Scheduler started; full_interval=%smin fast_interval=%smin",
        SCRAPE_INTERVAL_MIN,
        FAST_SCRAPE_INTERVAL_MIN,
    )


def stop_background_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="Run one full sweep and exit")
    ap.add_argument("--fast", action="store_true", help="Run one fast watchlist sweep and exit")
    args = ap.parse_args()
    init_db()
    if args.once:
        print(json.dumps(run_once(), indent=2))
    elif args.fast:
        print(json.dumps(run_fast_watchlist(), indent=2))
    else:
        start_background_scheduler()
        print("Scheduler running. Ctrl+C to stop.")
        try:
            import time
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            stop_background_scheduler()
