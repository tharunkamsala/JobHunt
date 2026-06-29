import os
import sqlite3
import json
from datetime import datetime, timezone
import urllib.parse
import pg8000.dbapi

# Load dotenv to get DATABASE_URL
from dotenv import load_dotenv
load_dotenv()

# Import paths from config
from config import DB_PATH, DATABASE_URL

if not DATABASE_URL:
    print("Error: DATABASE_URL not set in environment or .env file.")
    exit(1)

print(f"Source SQLite: {DB_PATH}")
print(f"Target Postgres: {DATABASE_URL.split('@')[-1]}")

# 1. Connect to SQLite
sqlite_conn = sqlite3.connect(DB_PATH)
sqlite_conn.row_factory = sqlite3.Row
sqlite_cur = sqlite_conn.cursor()

# 2. Connect to Postgres
parsed = urllib.parse.urlparse(DATABASE_URL)
username = parsed.username
password = urllib.parse.unquote(parsed.password or '')
hostname = parsed.hostname
port = parsed.port or 5432
database = parsed.path.lstrip('/')

pg_conn = pg8000.dbapi.connect(
    user=username,
    password=password,
    host=hostname,
    port=port,
    database=database
)
pg_cur = pg_conn.cursor()

# 3. Drop existing Postgres tables for a clean migration
print("Dropping existing Postgres tables for clean migration...")
pg_cur.execute("DROP TABLE IF EXISTS jobs CASCADE")
pg_cur.execute("DROP TABLE IF EXISTS runs CASCADE")
pg_cur.execute("DROP TABLE IF EXISTS app_meta CASCADE")
pg_cur.execute("DROP TABLE IF EXISTS scrape_state CASCADE")
pg_conn.commit()

# 4. Create tables in Postgres
print("Initializing Postgres schema...")
from db import init_db
init_db()

# 5. Migrate app_meta
print("Migrating app_meta...")
sqlite_cur.execute("SELECT k, v FROM app_meta")
meta_rows = sqlite_cur.fetchall()
for row in meta_rows:
    pg_cur.execute(
        "INSERT INTO app_meta (k, v) VALUES (%s, %s) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
        (row["k"], row["v"])
    )
print(f"Migrated {len(meta_rows)} rows in app_meta.")

# 6. Migrate scrape_state
print("Migrating scrape_state...")
sqlite_cur.execute("SELECT * FROM scrape_state")
ss_rows = sqlite_cur.fetchall()
if ss_rows:
    columns = [desc[0] for desc in sqlite_cur.description]
    placeholders = ", ".join(["%s"] * len(columns))
    col_names = ", ".join(columns)
    for row in ss_rows:
        vals = []
        for c in columns:
            val = row[c]
            # Clamp tiny float values that underflow float4/float8
            if c == "priority_score" and isinstance(val, float) and val < 1e-37:
                val = 0.0
            vals.append(val)
        update_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in columns if c != "company"])
        query = f"INSERT INTO scrape_state ({col_names}) VALUES ({placeholders}) ON CONFLICT (company) DO UPDATE SET {update_clause}"
        pg_cur.execute(query, vals)
print(f"Migrated {len(ss_rows)} rows in scrape_state.")

# 7. Migrate runs
print("Migrating runs...")
sqlite_cur.execute("SELECT * FROM runs")
runs_rows = sqlite_cur.fetchall()
if runs_rows:
    columns = [desc[0] for desc in sqlite_cur.description]
    placeholders = ", ".join(["%s"] * len(columns))
    col_names = ", ".join(columns)
    
    batch = [[r[c] for c in columns] for r in runs_rows]
    pg_cur.executemany(f"INSERT INTO runs ({col_names}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING", batch)
    
    # Update runs sequence
    pg_cur.execute("SELECT setval('runs_id_seq', COALESCE((SELECT MAX(id)+1 FROM runs), 1), false)")
print(f"Migrated {len(runs_rows)} rows in runs.")

# 8. Migrate jobs
print("Migrating jobs...")
sqlite_cur.execute("SELECT * FROM jobs")
jobs_rows = sqlite_cur.fetchall()
if jobs_rows:
    columns = [desc[0] for desc in sqlite_cur.description]
    placeholders = ", ".join(["%s"] * len(columns))
    col_names = ", ".join(columns)
    
    batch = [[j[c] for c in columns] for j in jobs_rows]
    pg_cur.executemany(f"INSERT INTO jobs ({col_names}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING", batch)
            
    # Update jobs sequence
    pg_cur.execute("SELECT setval('jobs_id_seq', COALESCE((SELECT MAX(id)+1 FROM jobs), 1), false)")
print(f"Migrated {len(jobs_rows)} rows in jobs.")

# 9. Commit and clean up
pg_conn.commit()
sqlite_conn.close()
pg_conn.close()
print("Migration completed successfully!")
