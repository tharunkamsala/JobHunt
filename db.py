"""Database data layer for jobs + scrape runs."""
from __future__ import annotations

import os
import urllib.parse
import pg8000.dbapi
import sqlite3
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from typing import Iterable, Optional

from config import (
    DB_PATH,
    DATABASE_URL,
    ROLE_FILTERS,
    JOB_MISS_DEACTIVATE_THRESHOLD,
    DEFAULT_WATCHLIST_COMPANIES,
)

IS_POSTGRES = DATABASE_URL is not None and DATABASE_URL.startswith("postgres")

class PostgresRow:
    def __init__(self, description, row_tuple):
        self._fields = [desc[0] for desc in description]
        self._row = row_tuple

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        try:
            idx = self._fields.index(key)
            return self._row[idx]
        except ValueError:
            raise KeyError(key)

    def keys(self):
        return self._fields

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __iter__(self):
        return iter(self._row)

class PostgresCursorWrapper:
    def __init__(self, cur):
        self.cur = cur

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        self.cur.execute(sql, params or ())
        return self

    def fetchone(self):
        row = self.cur.fetchone()
        if row is None:
            return None
        return PostgresRow(self.cur.description, row)

    def fetchall(self):
        rows = self.cur.fetchall()
        if not rows:
            return []
        desc = self.cur.description
        return [PostgresRow(desc, r) for r in rows]

    @property
    def rowcount(self):
        return self.cur.rowcount

    @property
    def description(self):
        return self.cur.description

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        cur = self.conn.cursor()
        sql = sql.replace("?", "%s")
        cur.execute(sql, params or ())
        return PostgresCursorWrapper(cur)

    def executescript(self, sql_script):
        cur = self.conn.cursor()
        cur.execute(sql_script)
        return PostgresCursorWrapper(cur)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

def get_postgres_connection():
    parsed = urllib.parse.urlparse(DATABASE_URL)
    username = parsed.username
    password = urllib.parse.unquote(parsed.password or '')
    hostname = parsed.hostname
    port = parsed.port or 5432
    database = parsed.path.lstrip('/')
    
    conn = pg8000.dbapi.connect(
        user=username,
        password=password,
        host=hostname,
        port=port,
        database=database
    )
    return conn

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint    TEXT NOT NULL UNIQUE,
    company        TEXT NOT NULL,
    title          TEXT NOT NULL,
    location       TEXT,
    url            TEXT,
    categories     TEXT,  -- JSON array of one primary role category, e.g. ["SDE 1"]
    primary_category TEXT,  -- normalized primary category for fast filtering
    source         TEXT,  -- ats type (greenhouse, lever, etc.)
    posted_at      TEXT,  -- ISO 8601 when the company posted the role (best-effort from ATS)
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    is_active      INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_jobs_company    ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_active     ON jobs(is_active);

CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    success         INTEGER,
    jobs_found      INTEGER DEFAULT 0,
    jobs_new        INTEGER DEFAULT 0,
    source          TEXT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    k   TEXT PRIMARY KEY,
    v   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_state (
    company               TEXT PRIMARY KEY,
    watchlist             INTEGER DEFAULT 0,
    last_fast_run_at      TEXT,
    last_full_run_at      TEXT,
    last_success_at       TEXT,
    last_source           TEXT,
    last_jobs_found       INTEGER DEFAULT 0,
    last_jobs_new         INTEGER DEFAULT 0,
    consecutive_failures  INTEGER DEFAULT 0,
    priority_score        REAL DEFAULT 0
);
"""

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id             SERIAL PRIMARY KEY,
    fingerprint    TEXT NOT NULL UNIQUE,
    company        TEXT NOT NULL,
    title          TEXT NOT NULL,
    location       TEXT,
    url            TEXT,
    categories     TEXT,
    primary_category TEXT,
    source         TEXT,
    posted_at      TEXT,
    first_seen_at  TEXT NOT NULL,
    last_seen_at   TEXT NOT NULL,
    is_active      INTEGER DEFAULT 1,
    applied_at     TEXT,
    applied_notes  TEXT,
    posting_id     TEXT,
    missed_runs    INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_jobs_company    ON jobs(company);
CREATE INDEX IF NOT EXISTS idx_jobs_first_seen ON jobs(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_active     ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_posted     ON jobs(posted_at);
CREATE INDEX IF NOT EXISTS idx_jobs_applied    ON jobs(applied_at);
CREATE INDEX IF NOT EXISTS idx_jobs_posting_id ON jobs(posting_id);
CREATE INDEX IF NOT EXISTS idx_jobs_primary_category ON jobs(primary_category);
CREATE INDEX IF NOT EXISTS idx_jobs_active_primary_category ON jobs(is_active, primary_category);
CREATE INDEX IF NOT EXISTS idx_jobs_company_posting_id ON jobs(company, posting_id);

CREATE TABLE IF NOT EXISTS runs (
    id              SERIAL PRIMARY KEY,
    company         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    success         INTEGER,
    jobs_found      INTEGER DEFAULT 0,
    jobs_new        INTEGER DEFAULT 0,
    source          TEXT,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS app_meta (
    k   TEXT PRIMARY KEY,
    v   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_state (
    company               TEXT PRIMARY KEY,
    watchlist             INTEGER DEFAULT 0,
    last_fast_run_at      TEXT,
    last_full_run_at      TEXT,
    last_success_at       TEXT,
    last_source           TEXT,
    last_jobs_found       INTEGER DEFAULT 0,
    last_jobs_new         INTEGER DEFAULT 0,
    consecutive_failures  INTEGER DEFAULT 0,
    consecutive_zero_results INTEGER DEFAULT 0,
    priority_score        DOUBLE PRECISION DEFAULT 0
);
"""

# Bump when category rules change so we re-label existing rows.
_CATEGORY_RULES_VERSION = "11"
_SCRAPE_ENABLED_CATEGORIES_KEY = "scrape_enabled_categories"
_WATCHLIST_COMPANIES_KEY = "watchlist_companies"
_CATEGORY_ALIASES = {
    "Summer 2026 Intern": "Summer Intern",
    "Fall 2026 Co-op / Intern": "Fall Co-op / Intern",
    "Spring 2027 Intern": "Spring Intern",
    "New Grad 2027": "New Grad",
}


def _extract_primary_category(categories_raw: str | None) -> str | None:
    try:
        vals = json.loads(categories_raw or "[]")
        if isinstance(vals, list) and vals:
            first = vals[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
    except Exception:
        pass
    return None


def _relabel_all_job_categories(conn) -> int:
    """Recompute `categories` from the current `match_categories` rules."""
    from scraper.filters import match_categories
    n = 0
    for row in conn.execute("SELECT id, title FROM jobs").fetchall():
        cats = match_categories(row["title"] or "")
        primary = cats[0] if cats else None
        conn.execute("UPDATE jobs SET categories = ?, primary_category = ? WHERE id = ?",
                     (json.dumps(cats), primary, row["id"]))
        n += 1
    return n


def fingerprint(company: str, title: str, location: str | None, url: str | None) -> str:
    """Stable dedup key for a job posting."""
    key = f"{company.lower().strip()}|{title.lower().strip()}|{(location or '').lower().strip()}|{(url or '').strip()}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


@contextmanager
def connect():
    if IS_POSTGRES:
        conn = get_postgres_connection()
        wrapped = PostgresConnectionWrapper(conn)
        try:
            yield wrapped
            wrapped.commit()
        except Exception:
            wrapped.rollback()
            raise
        finally:
            wrapped.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    with connect() as conn:
        if IS_POSTGRES:
            conn.executescript(POSTGRES_SCHEMA)
        else:
            conn.executescript(SCHEMA)
            # Additive migrations for older DBs.
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(jobs)").fetchall()]
            if "posted_at" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN posted_at TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at)")
            if "applied_at" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN applied_at TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_applied ON jobs(applied_at)")
            if "applied_notes" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN applied_notes TEXT")
            if "posting_id" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN posting_id TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_posting_id ON jobs(posting_id)")
            if "missed_runs" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN missed_runs INTEGER DEFAULT 0")
            if "primary_category" not in cols:
                conn.execute("ALTER TABLE jobs ADD COLUMN primary_category TEXT")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_primary_category ON jobs(primary_category)")
                rows = conn.execute("SELECT id, categories FROM jobs WHERE primary_category IS NULL").fetchall()
                for row in rows:
                    conn.execute(
                        "UPDATE jobs SET primary_category = ? WHERE id = ?",
                        (_extract_primary_category(row["categories"]), row["id"]),
                    )
            else:
                rows = conn.execute("SELECT id, categories FROM jobs WHERE primary_category IS NULL").fetchall()
                for row in rows:
                    conn.execute(
                        "UPDATE jobs SET primary_category = ? WHERE id = ?",
                        (_extract_primary_category(row["categories"]), row["id"]),
                    )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_primary_category ON jobs(primary_category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_active_primary_category ON jobs(is_active, primary_category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company_posting_id ON jobs(company, posting_id)")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scrape_state (
                    company TEXT PRIMARY KEY,
                    watchlist INTEGER DEFAULT 0,
                    last_fast_run_at TEXT,
                    last_full_run_at TEXT,
                    last_success_at TEXT,
                    last_source TEXT,
                    last_jobs_found INTEGER DEFAULT 0,
                    last_jobs_new INTEGER DEFAULT 0,
                    consecutive_failures INTEGER DEFAULT 0,
                    consecutive_zero_results INTEGER DEFAULT 0,
                    priority_score REAL DEFAULT 0
                );
                """
            )
            # Additive migration for existing DBs.
            ss_cols = [r["name"] for r in conn.execute("PRAGMA table_info(scrape_state)").fetchall()]
            if "consecutive_zero_results" not in ss_cols:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN consecutive_zero_results INTEGER DEFAULT 0")
        
        cur = conn.execute("SELECT v FROM app_meta WHERE k = 'category_rules'").fetchone()
        if not cur or (cur[0] or "") != _CATEGORY_RULES_VERSION:
            n = _relabel_all_job_categories(conn)
            sql = "INSERT INTO app_meta (k, v) VALUES ('category_rules', ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v" if IS_POSTGRES else "INSERT OR REPLACE INTO app_meta (k, v) VALUES ('category_rules', ?)"
            conn.execute(sql, (_CATEGORY_RULES_VERSION,))
            if n:
                import logging
                logging.getLogger("db").info(
                    "Relabeled %d jobs with new primary categories", n
                )
        row = conn.execute("SELECT v FROM app_meta WHERE k = ?", (_WATCHLIST_COMPANIES_KEY,)).fetchone()
        names: list[str] = []
        if row is not None:
            try:
                loaded = json.loads(row["v"] or "[]")
            except Exception:
                loaded = []
            if isinstance(loaded, list):
                names = [n.strip() for n in loaded if isinstance(n, str) and n.strip()]
        else:
            names = list(DEFAULT_WATCHLIST_COMPANIES)
            sql = "INSERT INTO app_meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v" if IS_POSTGRES else "INSERT OR REPLACE INTO app_meta (k, v) VALUES (?, ?)"
            conn.execute(sql, (_WATCHLIST_COMPANIES_KEY, json.dumps(names)))
        for name in names:
            sql = "INSERT INTO scrape_state (company, watchlist) VALUES (?, 1) ON CONFLICT(company) DO UPDATE SET watchlist = 1"
            conn.execute(sql, (name,))


def get_enabled_scrape_categories() -> list[str]:
    """Return scrape-enabled category names. Defaults to all ROLE_FILTERS keys."""
    default = list(ROLE_FILTERS.keys())
    with connect() as conn:
        row = conn.execute(
            "SELECT v FROM app_meta WHERE k = ?",
            (_SCRAPE_ENABLED_CATEGORIES_KEY,),
        ).fetchone()
        if not row:
            return default
        try:
            vals = json.loads(row["v"] or "[]")
            if not isinstance(vals, list):
                return default
            allowed = set(ROLE_FILTERS.keys())
            cleaned = []
            for x in vals:
                if not isinstance(x, str):
                    continue
                x = _CATEGORY_ALIASES.get(x, x)
                if x in allowed:
                    cleaned.append(x)
            return cleaned
        except Exception:
            return default


def set_enabled_scrape_categories(categories: list[str]) -> list[str]:
    """Persist scrape-enabled categories and return sanitized stored value."""
    allowed = set(ROLE_FILTERS.keys())
    cleaned = []
    for x in categories:
        if not isinstance(x, str):
            continue
        x = _CATEGORY_ALIASES.get(x, x)
        if x in allowed:
            cleaned.append(x)
    # Keep deterministic order as defined in ROLE_FILTERS.
    ordered = [name for name in ROLE_FILTERS.keys() if name in set(cleaned)]
    with connect() as conn:
        sql = "INSERT INTO app_meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v" if IS_POSTGRES else "INSERT OR REPLACE INTO app_meta (k, v) VALUES (?, ?)"
        conn.execute(sql, (_SCRAPE_ENABLED_CATEGORIES_KEY, json.dumps(ordered)))
    return ordered


def get_watchlist_companies() -> list[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT company FROM scrape_state WHERE watchlist = 1 ORDER BY LOWER(company)"
        ).fetchall()
    names = [r["company"] for r in rows if r["company"]]
    if names:
        return names
    with connect() as conn:
        row = conn.execute("SELECT v FROM app_meta WHERE k = ?", (_WATCHLIST_COMPANIES_KEY,)).fetchone()
    if not row:
        return []
    try:
        vals = json.loads(row["v"] or "[]")
        if not isinstance(vals, list):
            return []
        return [v for v in vals if isinstance(v, str) and v.strip()]
    except Exception:
        return []


def set_watchlist_companies(companies: list[str]) -> list[str]:
    cleaned = sorted({c.strip() for c in companies if isinstance(c, str) and c.strip()}, key=str.lower)
    with connect() as conn:
        sql = "INSERT INTO app_meta (k, v) VALUES (?, ?) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v" if IS_POSTGRES else "INSERT OR REPLACE INTO app_meta (k, v) VALUES (?, ?)"
        conn.execute(sql, (_WATCHLIST_COMPANIES_KEY, json.dumps(cleaned)))
        conn.execute("UPDATE scrape_state SET watchlist = 0")
        for name in cleaned:
            sql = "INSERT INTO scrape_state (company, watchlist) VALUES (?, 1) ON CONFLICT(company) DO UPDATE SET watchlist = 1"
            conn.execute(sql, (name,))
    return cleaned



def prioritized_company_names(limit: int | None = None,
                              watchlist_only: bool = False) -> list[str]:
    sql = """
        SELECT company, watchlist, priority_score, consecutive_failures,
               last_success_at, last_jobs_new
        FROM scrape_state
    """
    params: list[object] = []
    if watchlist_only:
        sql += " WHERE watchlist = 1"
    sql += (
        " ORDER BY watchlist DESC, priority_score DESC, last_jobs_new DESC, "
        "COALESCE(last_success_at, '') DESC, consecutive_failures ASC, LOWER(company)"
    )
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [r["company"] for r in rows if r["company"]]


def record_scrape_state(company: str, mode: str, source: str, success: bool,
                        jobs_found: int, jobs_new: int) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mode_col = "last_fast_run_at" if mode == "fast" else "last_full_run_at"
    priority_bump = min(int(jobs_new or 0) * 3 + int(jobs_found or 0), 25)
    with connect() as conn:
        conn.execute(
            "INSERT INTO scrape_state (company) VALUES (?) ON CONFLICT(company) DO NOTHING",
            (company,),
        )
        row = conn.execute(
            "SELECT priority_score, consecutive_failures, consecutive_zero_results FROM scrape_state WHERE company = ?",
            (company,),
        ).fetchone()
        old_score = float(row["priority_score"] or 0) if row else 0.0
        fail_count = int(row["consecutive_failures"] or 0) if row else 0
        zero_count = int((row["consecutive_zero_results"] or 0) if row else 0)
        if success:
            new_score = max(0.0, old_score * 0.82) + priority_bump
            fail_count = 0
            zero_count = 0 if int(jobs_found or 0) > 0 else zero_count + 1
        else:
            new_score = max(0.0, old_score * 0.65)
            fail_count += 1
        conn.execute(
            f"""
            UPDATE scrape_state
               SET {mode_col} = ?,
                   last_source = ?,
                   last_jobs_found = ?,
                   last_jobs_new = ?,
                   last_success_at = CASE WHEN ? THEN ? ELSE last_success_at END,
                   consecutive_failures = ?,
                   consecutive_zero_results = ?,
                   priority_score = ?
             WHERE company = ?
            """,
            (
                now,
                source,
                int(jobs_found or 0),
                int(jobs_new or 0),
                1 if success else 0,
                now,
                fail_count,
                zero_count,
                new_score,
                company,
            ),
        )


def reconcile_company_jobs(company: str, seen_fingerprints: set[str],
                           source: str | None = None,
                           miss_threshold: int = JOB_MISS_DEACTIVATE_THRESHOLD) -> int:
    """Increment misses for unseen active jobs after a successful scrape.

    Jobs are only deactivated after multiple successful misses to avoid
    transient API/scraper failures hiding real openings.
    """
    if miss_threshold < 1:
        miss_threshold = 1
    with connect() as conn:
        sql = "SELECT id, fingerprint, missed_runs FROM jobs WHERE company = ? AND is_active = 1"
        params: list[object] = [company]
        if source:
            sql += " AND source = ?"
            params.append(source)
        enabled_categories = get_enabled_scrape_categories()
        if enabled_categories:
            placeholders = ",".join("?" for _ in enabled_categories)
            sql += f" AND primary_category IN ({placeholders})"
            params.extend(enabled_categories)
        rows = conn.execute(sql, params).fetchall()
        deactivated = 0
        for row in rows:
            if row["fingerprint"] in seen_fingerprints:
                continue
            misses = int(row["missed_runs"] or 0) + 1
            is_active = 0 if misses >= miss_threshold else 1
            conn.execute(
                "UPDATE jobs SET missed_runs = ?, is_active = ? WHERE id = ?",
                (misses, is_active, row["id"]),
            )
            if not is_active:
                deactivated += 1
    return deactivated


def upsert_jobs(company: str, source: str, jobs: Iterable[dict]) -> tuple[int, int, list[dict], set[str]]:
    """Insert/update jobs.

    Returns (total_found, newly_added, new_job_rows, seen_fingerprints).
    Posting IDs are preferred for matching because they are more stable than
    title/location/url fingerprints across ATS refreshes.
    """
    total = 0
    new = 0
    new_rows: list[dict] = []
    seen_fingerprints: set[str] = set()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connect() as conn:
        for j in jobs:
            total += 1
            fp = fingerprint(company, j["title"], j.get("location"), j.get("url"))
            cats = json.dumps(j.get("categories", []))
            posted_at = j.get("posted_at") or None
            ext_id = (j.get("posting_id") or "").strip() or None
            row = None
            if ext_id:
                row = conn.execute(
                    "SELECT id, posted_at, fingerprint FROM jobs WHERE company = ? AND posting_id = ?",
                    (company, ext_id),
                ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT id, posted_at, fingerprint FROM jobs WHERE fingerprint = ?",
                    (fp,),
                ).fetchone()
            if row:
                # Keep existing posted_at if already set, otherwise fill it in.
                new_posted = row["posted_at"] or posted_at
                primary = (j.get("categories") or [None])[0]
                conn.execute(
                    """UPDATE jobs SET last_seen_at = ?, is_active = 1, categories = ?,
                        primary_category = ?, posted_at = ?,
                        posting_id = COALESCE(?, posting_id), source = COALESCE(?, source),
                        fingerprint = ?, missed_runs = 0, url = COALESCE(?, url),
                        location = COALESCE(?, location), title = ?
                        WHERE id = ?""",
                    (now, cats, primary, new_posted, ext_id, source, fp,
                     j.get("url"), j.get("location"), j["title"], row["id"]),
                )
                seen_fingerprints.add(fp)
            else:
                primary = (j.get("categories") or [None])[0]
                conn.execute(
                    """
                    INSERT INTO jobs (fingerprint, company, title, location, url,
                                      categories, primary_category, source, posted_at, posting_id,
                                      first_seen_at, last_seen_at, is_active, missed_runs)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0)
                    """,
                    (
                        fp,
                        company,
                        j["title"],
                        j.get("location"),
                        j.get("url"),
                        cats,
                        primary,
                        source,
                        posted_at,
                        ext_id,
                        now,
                        now,
                    ),
                )
                new += 1
                seen_fingerprints.add(fp)
                new_rows.append({
                    "company": company,
                    "title": j["title"],
                    "location": j.get("location"),
                    "url": j.get("url"),
                    "posted_at": posted_at,
                    "posting_id": ext_id,
                    "categories": j.get("categories", []),
                })
    return total, new, new_rows, seen_fingerprints


def record_run(company: str, source: str, started_at: str, success: bool,
               jobs_found: int, jobs_new: int, error: Optional[str] = None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (company, started_at, finished_at, success,
                              jobs_found, jobs_new, source, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company,
                started_at,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                1 if success else 0,
                jobs_found,
                jobs_new,
                source,
                error,
            ),
        )


def fetch_jobs(category: Optional[str] = None,
               company: Optional[str] = None,
               companies: Optional[list[str]] = None,
               search: Optional[str] = None,
               since_minutes: Optional[int] = None,
               applied_only: bool = False,
               limit: int = 1000) -> list[dict]:
    # When viewing the applied tracker we want to see the job regardless of
    # whether it's still in the live scrape — the user already applied to it
    # and may want to revisit it later.
    if applied_only:
        sql = "SELECT * FROM jobs WHERE applied_at IS NOT NULL"
    else:
        sql = "SELECT * FROM jobs WHERE is_active = 1"
    params: list = []

    # Accept either a single `company` or a list `companies`.
    co_list: list[str] = []
    if company:
        co_list.append(company)
    if companies:
        co_list.extend(companies)
    co_list = [c for c in dict.fromkeys(co_list) if c]  # dedup, preserve order
    if co_list:
        placeholders = ",".join(["?"] * len(co_list))
        sql += f" AND company IN ({placeholders})"
        params.extend(co_list)

    if search:
        s = search.strip()
        like = f"%{s}%"
        if s.isdigit():
            sql += (
                " AND (title LIKE ? OR location LIKE ? OR CAST(id AS TEXT) LIKE ?"
                " OR COALESCE(posting_id, '') LIKE ?)"
            )
            params += [like, like, like, like]
        else:
            sql += " AND (title LIKE ? OR location LIKE ? OR COALESCE(posting_id, '') LIKE ?)"
            params += [like, like, like]
    if category:
        sql += " AND primary_category = ?"
        params.append(category)
    if since_minutes is not None and since_minutes > 0:
        from datetime import timedelta as _td
        cutoff = (datetime.now(timezone.utc) - _td(minutes=since_minutes)).isoformat(timespec="seconds")
        # Window is based on when we added the role to the tracker.
        sql += " AND first_seen_at >= ?"
        params.append(cutoff)
    # Newest-added-first.
    sql += " ORDER BY first_seen_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        try:
            r["categories"] = json.loads(r["categories"] or "[]")
        except Exception:
            r["categories"] = []
    return rows


def stats() -> dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM jobs WHERE is_active = 1").fetchone()[0]
        applied = conn.execute("SELECT COUNT(*) FROM jobs WHERE applied_at IS NOT NULL").fetchone()[0]
        by_cat_rows = conn.execute(
            "SELECT primary_category, COUNT(*) AS c FROM jobs "
            "WHERE is_active = 1 AND primary_category IS NOT NULL "
            "GROUP BY primary_category"
        ).fetchall()
        last_run = conn.execute(
            "SELECT company, finished_at, success, jobs_new FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        companies_scraped = conn.execute(
            "SELECT COUNT(DISTINCT company) FROM runs"
        ).fetchone()[0]
    by_cat: dict[str, int] = {row["primary_category"]: row["c"] for row in by_cat_rows}
    return {
        "total": total,
        "applied": applied,
        "by_category": by_cat,
        "last_run": dict(last_run) if last_run else None,
        "companies_scraped": companies_scraped,
    }


def set_applied(job_id: int, applied: bool, notes: Optional[str] = None) -> Optional[dict]:
    """Mark / unmark a job as applied. Returns the updated row, or None if not found."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") if applied else None
    with connect() as conn:
        cur = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,))
        if cur.fetchone() is None:
            return None
        if applied:
            conn.execute(
                "UPDATE jobs SET applied_at = COALESCE(applied_at, ?), applied_notes = ? WHERE id = ?",
                (now, notes, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET applied_at = NULL, applied_notes = NULL WHERE id = ?",
                (job_id,),
            )
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    d = dict(row)
    try:
        d["categories"] = json.loads(d["categories"] or "[]")
    except Exception:
        d["categories"] = []
    return d


def recent_runs(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def company_run_health() -> dict[str, dict]:
    """Return latest scrape/run status per company for sidebar health badges."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.company, r.finished_at, r.success, r.jobs_new
            FROM runs r
            JOIN (
                SELECT company, MAX(id) AS max_id
                FROM runs
                GROUP BY company
            ) latest
              ON latest.company = r.company AND latest.max_id = r.id
            """
        ).fetchall()

    now = datetime.now(timezone.utc)
    health: dict[str, dict] = {}
    for row in rows:
        finished_at = row["finished_at"]
        success = bool(row["success"])
        status = "unknown"
        age_min: int | None = None
        if finished_at:
            try:
                dt = datetime.fromisoformat(str(finished_at))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_min = max(0, int((now - dt).total_seconds() // 60))
            except Exception:
                age_min = None
        if not success:
            status = "failed"
        elif age_min is None:
            status = "unknown"
        elif age_min <= 180:
            status = "fresh"
        else:
            status = "stale"
        health[row["company"]] = {
            "status": status,
            "finished_at": finished_at,
            "age_min": age_min,
            "jobs_new": int(row["jobs_new"] or 0),
            "success": success,
        }
    return health


def coverage_alerts() -> list[dict]:
    """Return companies with consecutive zero-result scrape runs (broken coverage)."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT company,
                   last_jobs_found,
                   consecutive_zero_results,
                   consecutive_failures,
                   last_source,
                   last_full_run_at
              FROM scrape_state
             WHERE consecutive_zero_results >= 2 OR consecutive_failures >= 2
             ORDER BY (consecutive_zero_results + consecutive_failures) DESC, LOWER(company)
            """
        ).fetchall()
    alerts = []
    for r in rows:
        zero = int(r["consecutive_zero_results"] or 0)
        fail = int(r["consecutive_failures"] or 0)
        if zero >= 3 or fail >= 3:
            risk = "high"
        elif zero >= 2 or fail >= 2:
            risk = "medium"
        else:
            risk = "low"
        alerts.append({
            "company": r["company"],
            "last_jobs_found": int(r["last_jobs_found"] or 0),
            "consecutive_zeros": zero,
            "consecutive_failures": fail,
            "last_source": r["last_source"],
            "last_run_at": r["last_full_run_at"],
            "risk": risk,
        })
    return alerts


def get_job(job_id: int) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    try:
        d["categories"] = json.loads(d.get("categories") or "[]")
    except Exception:
        d["categories"] = []
    return d


def create_job(payload: dict) -> dict:
    """Create a manual job row (or upsert by fingerprint) and return the saved row."""
    company = str(payload.get("company") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not company or not title:
        raise ValueError("company and title are required")

    location = (payload.get("location") or None)
    url = (payload.get("url") or None)
    source = str(payload.get("source") or "manual")
    posted_at = payload.get("posted_at") or None
    posting_id = (payload.get("posting_id") or None)
    is_active = 1 if payload.get("is_active", True) else 0
    categories = payload.get("categories") or []
    if not isinstance(categories, list):
        raise ValueError("categories must be a list")
    categories = [c for c in categories if isinstance(c, str) and c.strip()]
    primary = categories[0] if categories else None

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fp = fingerprint(company, title, location, url)
    with connect() as conn:
        row = conn.execute("SELECT id FROM jobs WHERE fingerprint = ?", (fp,)).fetchone()
        if row:
            conn.execute(
                """UPDATE jobs
                   SET company = ?, title = ?, location = ?, url = ?, source = ?,
                       posted_at = ?, posting_id = ?, categories = ?, primary_category = ?,
                       last_seen_at = ?, is_active = ?
                   WHERE id = ?""",
                (
                    company,
                    title,
                    location,
                    url,
                    source,
                    posted_at,
                    posting_id,
                    json.dumps(categories),
                    primary,
                    now,
                    is_active,
                    row["id"],
                ),
            )
            job_id = row["id"]
        else:
            if IS_POSTGRES:
                cur = conn.execute(
                    """INSERT INTO jobs (
                           fingerprint, company, title, location, url, categories,
                           primary_category, source, posted_at, posting_id,
                           first_seen_at, last_seen_at, is_active
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                    (
                        fp,
                        company,
                        title,
                        location,
                        url,
                        json.dumps(categories),
                        primary,
                        source,
                        posted_at,
                        posting_id,
                        now,
                        now,
                        is_active,
                    ),
                )
                job_id = cur.fetchone()["id"]
            else:
                conn.execute(
                    """INSERT INTO jobs (
                           fingerprint, company, title, location, url, categories,
                           primary_category, source, posted_at, posting_id,
                           first_seen_at, last_seen_at, is_active
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fp,
                        company,
                        title,
                        location,
                        url,
                        json.dumps(categories),
                        primary,
                        source,
                        posted_at,
                        posting_id,
                        now,
                        now,
                        is_active,
                    ),
                )
                job_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    row = get_job(job_id)
    if row is None:
        raise ValueError("failed to create job")
    return row


def update_job(job_id: int, payload: dict) -> Optional[dict]:
    """Update mutable job fields and return updated row."""
    allowed = {
        "company", "title", "location", "url", "source", "posted_at",
        "posting_id", "is_active", "applied_at", "applied_notes",
    }
    updates: dict[str, object] = {k: payload[k] for k in allowed if k in payload}

    if "categories" in payload:
        cats = payload.get("categories") or []
        if not isinstance(cats, list):
            raise ValueError("categories must be a list")
        cats = [c for c in cats if isinstance(c, str) and c.strip()]
        updates["categories"] = json.dumps(cats)
        updates["primary_category"] = cats[0] if cats else None

    if not updates:
        return get_job(job_id)

    if "is_active" in updates:
        updates["is_active"] = 1 if bool(updates["is_active"]) else 0

    updates["last_seen_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    fields = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [job_id]

    with connect() as conn:
        cur = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if cur is None:
            return None
        conn.execute(f"UPDATE jobs SET {fields} WHERE id = ?", values)
    return get_job(job_id)


def delete_job(job_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        return cur.rowcount > 0


def clear_jobs(category: str | None = None,
               companies: list[str] | None = None,
               active_only: bool | None = None) -> int:
    sql = "DELETE FROM jobs WHERE 1=1"
    params: list[object] = []
    if category:
        sql += " AND primary_category = ?"
        params.append(category)
    if companies:
        vals = [c for c in companies if c]
        if vals:
            placeholders = ",".join(["?"] * len(vals))
            sql += f" AND company IN ({placeholders})"
            params.extend(vals)
    if active_only is True:
        sql += " AND is_active = 1"
    elif active_only is False:
        sql += " AND is_active = 0"
    with connect() as conn:
        cur = conn.execute(sql, params)
        return cur.rowcount


def clear_runs() -> int:
    with connect() as conn:
        cur = conn.execute("DELETE FROM runs")
        return cur.rowcount


def count_runs() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
