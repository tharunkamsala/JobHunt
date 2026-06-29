"""Flask UI for the job tracker."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from datetime import timedelta
from flask import Flask, jsonify, render_template, request

try:
    from flask_socketio import SocketIO, emit
    _HAS_SOCKETIO = True
except ImportError:
    _HAS_SOCKETIO = False

from config import (
    COMPANIES_JSON,
    EXTRA_COMPANIES_JSON,
    ROLE_FILTERS,
    EXCLUDED_COMPANIES,
    DEFAULT_GRAD_COHORT_YEAR,
    SUPPORTED_GRAD_COHORT_YEARS,
)
from db import (init_db, fetch_jobs, stats, recent_runs, set_applied,
                get_enabled_scrape_categories, set_enabled_scrape_categories,
                get_watchlist_companies, set_watchlist_companies,
                get_job, create_job, update_job, delete_job,
                clear_jobs, clear_runs, count_runs, company_run_health,
                purge_stale_jobs, retention_settings, set_block_dismissed_reimports,
                coverage_alerts)
from scheduler import (run_once, run_subset, start_background_scheduler,
                       run_fast_watchlist, status as sched_status, subset_status)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.config["SECRET_KEY"] = "job-tracker-ws-key"

# Initialize SocketIO if available; gracefully degrade to polling if not.
if _HAS_SOCKETIO:
    socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*",
                        logger=False, engineio_logger=False)
else:
    socketio = None
    log.warning("flask-socketio not installed — WebSocket disabled, using polling fallback")


def notify_new_jobs(new_rows: list[dict]) -> None:
    """Push newly discovered jobs to all connected WebSocket clients."""
    if not socketio or not new_rows:
        return
    try:
        socketio.emit("new_jobs", {
            "jobs": new_rows,
            "count": len(new_rows),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except Exception as e:
        log.debug("WebSocket emit failed (non-fatal): %s", e)


def notify_scrape_progress(company: str, status: str, found: int = 0,
                           new: int = 0, progress: str = "") -> None:
    """Push scrape progress updates to connected clients."""
    if not socketio:
        return
    try:
        socketio.emit("scrape_progress", {
            "company": company,
            "status": status,
            "found": found,
            "new": new,
            "progress": progress,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
    except Exception as e:
        log.debug("WebSocket progress emit failed (non-fatal): %s", e)


def _companies() -> list[dict]:
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
                by_name[name] = {
                    "category": c.get("category") or "Extra companies",
                    "name": name,
                    "industry": c.get("industry") or "",
                    "common_roles": c.get("common_roles") or "",
                    "url": url,
                    "h1b_level": c.get("h1b_level") or "Unknown / not H1B-listed",
                    "notes": c.get("notes") or "",
                    "company_source": "extra",
                }
            companies = list(by_name.values())
    return [c for c in companies if (c.get("name") or "").strip() not in EXCLUDED_COMPANIES]


def _company_index() -> dict[str, dict]:
    return {c["name"]: c for c in _companies() if c.get("name")}


@app.route("/")
def index():
    import re as _re
    def _slug(s: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    cats = [{"name": c, "slug": _slug(c)} for c in ROLE_FILTERS.keys()]
    return render_template(
        "index.html",
        categories=cats,
        companies=sorted({c["name"] for c in _companies()}),
        default_grad_year=DEFAULT_GRAD_COHORT_YEAR,
        grad_years=list(SUPPORTED_GRAD_COHORT_YEARS),
    )


@app.get("/api/grad-cohort")
def api_grad_cohort():
    from scraper.grad_cohort import grad_cohort_config
    return jsonify(grad_cohort_config())


@app.get("/api/jobs")
def api_jobs():
    category = request.args.get("category") or None
    # Support `company=Foo`, `company=Foo&company=Bar`, and `companies=Foo,Bar`.
    multi_companies = request.args.getlist("company")
    extra = request.args.get("companies")
    if extra:
        multi_companies.extend([c for c in extra.split(",") if c])
    search = request.args.get("q") or None
    limit = int(request.args.get("limit", 2000))

    # Time window: accept either `since=<minutes>` or `window=30m|1h|24h|7d|30d`.
    since_minutes: int | None = None
    since_raw = request.args.get("since")
    window = request.args.get("window")
    if since_raw:
        try:
            since_minutes = max(0, int(since_raw))
        except ValueError:
            since_minutes = None
    elif window:
        _map = {"30m": 30, "1h": 60, "6h": 360, "24h": 1440,
                "1d": 1440, "3d": 4320, "7d": 10080, "30d": 43200}
        since_minutes = _map.get(window.lower())

    applied_only = request.args.get("applied") in ("1", "true", "yes")

    jobs = fetch_jobs(category=category, companies=multi_companies or None,
                      search=search, since_minutes=since_minutes,
                      applied_only=applied_only, limit=limit)

    grad_year_raw = request.args.get("grad_year") or request.args.get("grad_cohort")
    grad_strict = request.args.get("grad_strict") in ("1", "true", "yes")
    if grad_year_raw:
        from scraper.grad_cohort import matches_grad_cohort
        try:
            gy = int(grad_year_raw)
            jobs = [
                j for j in jobs
                if matches_grad_cohort(
                    j.get("title") or "",
                    gy,
                    strict=grad_strict,
                    primary_category=j.get("primary_category"),
                )
            ]
        except ValueError:
            pass

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    for j in jobs:
        try:
            ref = j.get("posted_at") or j.get("first_seen_at")
            j["is_new"] = datetime.fromisoformat(ref) >= cutoff
        except Exception:
            j["is_new"] = False
    return jsonify({"jobs": jobs, "count": len(jobs)})


@app.get("/api/jobs/<int:job_id>")
def api_job_detail(job_id: int):
    job = get_job(job_id)
    if not job:
        return jsonify({"ok": False, "reason": "not found"}), 404
    meta = _company_index().get(job.get("company") or "", {})
    job["company_meta"] = {
        "h1b_level": meta.get("h1b_level"),
        "careers_url": meta.get("url"),
        "industry": meta.get("industry"),
        "common_roles": meta.get("common_roles"),
    }
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    try:
        ref = job.get("posted_at") or job.get("first_seen_at")
        job["is_new"] = datetime.fromisoformat(ref) >= cutoff
    except Exception:
        job["is_new"] = False
    return jsonify({"ok": True, "job": job})


@app.get("/api/stats")
def api_stats():
    return jsonify({**stats(), "scheduler": sched_status()})


@app.get("/api/companies")
def api_companies():
    """Return every known company, annotated with the count of currently-active
       jobs matching the optional ?category=... filter. Companies with zero
       matches are included (count=0) so they're still selectable in the UI."""
    category = request.args.get("category") or None
    jobs = fetch_jobs(category=category, limit=10000)
    counts: dict[str, int] = {}
    for j in jobs:
        counts[j["company"]] = counts.get(j["company"], 0) + 1

    health = company_run_health()
    watchlist = set(get_watchlist_companies())
    meta_by_name = _company_index()
    all_names = sorted({c["name"] for c in _companies()})
    rows = [
        {
            "name": n,
            "count": counts.get(n, 0),
            "watchlist": n in watchlist,
            "h1b_level": (meta_by_name.get(n) or {}).get("h1b_level"),
            "careers_url": (meta_by_name.get(n) or {}).get("url"),
            "industry": (meta_by_name.get(n) or {}).get("industry"),
            **health.get(n, {"status": "unknown", "finished_at": None, "age_min": None,
                             "jobs_new": 0, "success": None}),
        }
        for n in all_names
    ]
    rows.sort(key=lambda r: (-r["count"], r["name"].lower()))
    return jsonify({
        "companies": rows,
        "total": sum(r["count"] for r in rows),
        "with_jobs": sum(1 for r in rows if r["count"] > 0),
        "universe": len(rows),
        "watchlist": sorted(watchlist),
    })


@app.get("/api/runs")
def api_runs():
    return jsonify({"runs": recent_runs(limit=100)})


@app.post("/api/refresh")
def api_refresh():
    """Trigger an immediate full scrape in a background thread."""
    if sched_status().get("running"):
        return jsonify({"started": False, "reason": "already running"}), 409
    threading.Thread(target=run_once, daemon=True).start()
    return jsonify({"started": True})


@app.post("/api/refresh/fast")
def api_refresh_fast():
    """Trigger an immediate fast watchlist sweep in a background thread."""
    st = sched_status()
    if st.get("fast_running"):
        return jsonify({"started": False, "reason": "fast watchlist sweep already running"}), 409
    threading.Thread(target=run_fast_watchlist, daemon=True).start()
    return jsonify({"started": True, "watchlist": get_watchlist_companies()})


@app.post("/api/scrape")
def api_scrape_subset():
    """Trigger an on-demand scrape of one or more specific companies.
    Accepts either a JSON body {"companies": [...]} or query string
    `?company=Foo&company=Bar` / `?companies=Foo,Bar`. Runs alongside
    the scheduled sweep (doesn't block it)."""
    names: list[str] = []
    body = request.get_json(silent=True) or {}
    if isinstance(body, dict):
        names.extend(body.get("companies") or [])
        if body.get("company"):
            names.append(body["company"])
    names.extend(request.args.getlist("company"))
    extra = request.args.get("companies")
    if extra:
        names.extend([c for c in extra.split(",") if c])
    names = list(dict.fromkeys([n.strip() for n in names if n and n.strip()]))
    if not names:
        return jsonify({"started": False, "reason": "no companies given"}), 400
    if subset_status().get("running"):
        return jsonify({"started": False, "reason": "another on-demand scrape is running"}), 409
    return jsonify(run_subset(names))


@app.get("/api/scrape/categories")
def api_scrape_categories_get():
    all_categories = list(ROLE_FILTERS.keys())
    enabled = get_enabled_scrape_categories()
    return jsonify({"all": all_categories, "enabled": enabled})


@app.post("/api/scrape/categories")
def api_scrape_categories_set():
    body = request.get_json(silent=True) or {}
    enabled = body.get("enabled")
    if not isinstance(enabled, list):
        return jsonify({"ok": False, "reason": "expected JSON body with enabled: []"}), 400
    stored = set_enabled_scrape_categories(enabled)
    return jsonify({"ok": True, "enabled": stored, "all": list(ROLE_FILTERS.keys())})


@app.get("/api/scrape/status")
def api_scrape_status():
    return jsonify(subset_status())


@app.get("/api/watchlist")
def api_watchlist_get():
    names = get_watchlist_companies()
    return jsonify({"companies": names, "count": len(names)})


@app.post("/api/watchlist")
def api_watchlist_set():
    body = request.get_json(silent=True) or {}
    companies = body.get("companies")
    if not isinstance(companies, list):
        return jsonify({"ok": False, "reason": "expected JSON body with companies: []"}), 400
    stored = set_watchlist_companies(companies)
    return jsonify({"ok": True, "companies": stored, "count": len(stored)})


@app.post("/api/jobs/<int:job_id>/apply")
def api_job_apply(job_id: int):
    body = request.get_json(silent=True) or {}
    applied = body.get("applied")
    if applied is None:
        applied = True  # default: mark as applied
    notes = body.get("notes")
    row = set_applied(job_id, bool(applied), notes=notes)
    if row is None:
        return jsonify({"ok": False, "reason": "not found"}), 404
    return jsonify({"ok": True, "job": row})


@app.post("/api/jobs")
def api_jobs_create():
    body = request.get_json(silent=True) or {}
    try:
        row = create_job(body)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    return jsonify({"ok": True, "job": row})


@app.put("/api/jobs/<int:job_id>")
def api_jobs_update(job_id: int):
    body = request.get_json(silent=True) or {}
    try:
        row = update_job(job_id, body)
    except ValueError as e:
        return jsonify({"ok": False, "reason": str(e)}), 400
    if row is None:
        return jsonify({"ok": False, "reason": "not found"}), 404
    return jsonify({"ok": True, "job": row})


@app.delete("/api/jobs/<int:job_id>")
def api_jobs_delete(job_id: int):
    ok = delete_job(job_id)
    if not ok:
        return jsonify({"ok": False, "reason": "not found"}), 404
    return jsonify({"ok": True})


@app.get("/api/retention")
def api_retention_get():
    return jsonify(retention_settings())


@app.post("/api/retention")
def api_retention_set():
    body = request.get_json(silent=True) or {}
    if "block_dismissed_reimports" in body:
        set_block_dismissed_reimports(bool(body.get("block_dismissed_reimports")))
    return jsonify({"ok": True, **retention_settings()})


@app.post("/api/db/purge")
def api_db_purge():
    """Manually run the same stale-job cleanup as the weekly scheduler."""
    result = purge_stale_jobs()
    return jsonify({"ok": True, **result})


@app.get("/api/db/summary")
def api_db_summary():
    s = stats()
    return jsonify({
        "jobs_total": s.get("total", 0),
        "applied": s.get("applied", 0),
        "runs_total": count_runs(),
    })


@app.post("/api/db/clear")
def api_db_clear():
    """Clear data on demand.
    Body examples:
      {"scope":"jobs"}
      {"scope":"jobs", "category":"SDE 1"}
      {"scope":"jobs", "companies":["NVIDIA", "Apple"]}
      {"scope":"runs"}
      {"scope":"all"}
    """
    body = request.get_json(silent=True) or {}
    scope = (body.get("scope") or "jobs").strip().lower()
    deleted_jobs = 0
    deleted_runs = 0

    if scope in ("jobs", "all"):
        companies = body.get("companies") if isinstance(body.get("companies"), list) else None
        category = body.get("category") if isinstance(body.get("category"), str) else None
        active_only = body.get("active_only") if isinstance(body.get("active_only"), bool) else None
        deleted_jobs = clear_jobs(category=category, companies=companies, active_only=active_only)

    if scope in ("runs", "all"):
        deleted_runs = clear_runs()

    if scope not in ("jobs", "runs", "all"):
        return jsonify({"ok": False, "reason": "scope must be one of: jobs, runs, all"}), 400

    return jsonify({
        "ok": True,
        "scope": scope,
        "deleted_jobs": deleted_jobs,
        "deleted_runs": deleted_runs,
    })


@app.get("/api/coverage-alerts")
def api_coverage_alerts():
    """Companies with consecutive zero-result or failed scrape runs."""
    return jsonify(coverage_alerts())


@app.get("/api/ws-status")
def api_ws_status():
    """Check WebSocket availability."""
    return jsonify({
        "websocket_enabled": _HAS_SOCKETIO and socketio is not None,
        "async_mode": socketio.async_mode if socketio else None,
    })


if _HAS_SOCKETIO and socketio:
    @socketio.on("connect")
    def _ws_connect():
        log.info("WebSocket client connected")
        emit("connected", {"status": "ok"})

    @socketio.on("disconnect")
    def _ws_disconnect():
        log.info("WebSocket client disconnected")

    @socketio.on("ping_server")
    def _ws_ping():
        emit("pong_server", {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds")})


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5055"))
    init_db()
    start_background_scheduler()
    if socketio:
        socketio.run(app, host=host, port=port, debug=False,
                     use_reloader=False, allow_unsafe_werkzeug=True)
    else:
        app.run(host=host, port=port, debug=False, use_reloader=False)
