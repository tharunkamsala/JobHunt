# Job Tracker

A local job scraper that pulls listings directly from the career pages of **99 top H1B-sponsor tech companies**, filters for early-career roles (intern, new grad, SDE 1/2, ML, DevOps), deduplicates everything, and shows it on a live-updating website at `http://127.0.0.1:5055`.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [First-Time Setup](#2-first-time-setup)
3. [Running the App](#3-running-the-app)
4. [Using the Website](#4-using-the-website)
5. [Running a Manual Scrape](#5-running-a-manual-scrape)
6. [Adding Companies](#6-adding-companies)
7. [Customizing Role Filters](#7-customizing-role-filters)
8. [Project Structure](#8-project-structure)
9. [How Scraping Works](#9-how-scraping-works)
10. [Coverage Alerts](#10-coverage-alerts)
11. [API Reference](#11-api-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Requirement | Version | Check |
|---|---|---|
| Python | 3.11 or 3.12+ | `python3 --version` |
| pip | bundled with Python | `pip3 --version` |
| Internet connection | — | needed for scraping |

No Docker, no database server, no cloud account needed. Everything runs locally with SQLite.

---

## 2. First-Time Setup

Run these commands once. After that, you only need step [3](#3-running-the-app).

```bash
# 1. Enter the project folder
cd job_tracker

# 2. Create a Python virtual environment
python3 -m venv .venv

# 3. Activate it
#    macOS / Linux:
source .venv/bin/activate
#    Windows (Command Prompt):
.venv\Scripts\activate.bat
#    Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Install Playwright's browser binaries (needed for JS-heavy career sites)
playwright install chromium

# 6. Load the 99 companies from the Excel file into data/companies.json
python load_companies.py
```

After step 6 you should see `data/companies.json` with 99 entries.

---

## 3. Running the App

```bash
# Make sure the virtual environment is active first
source .venv/bin/activate   # macOS/Linux
# or .venv\Scripts\activate.bat on Windows

python app.py
```

Then open your browser to **http://127.0.0.1:5055**

The app does two things at once:
- Serves the website
- Runs a background scheduler that scrapes all 99 companies every **15 minutes**

The **first scrape starts automatically** when the server launches. It takes 5–15 minutes to complete the full sweep depending on your internet connection.

To stop the server, press `Ctrl + C` in the terminal.

---

## 4. Using the Website

### Main job list
- Jobs are sorted **newest-added first** by default
- Each card shows: company, title, location, category badge, and how long ago it was found
- **NEW** badge appears on jobs added in the last 24 hours
- Click any job title to open the original posting in a new tab

### Filtering
Use the **left sidebar** (click the filter icon in the top bar) to filter by:
- **Role category** — SDE 1, SDE 2, New Grad, Summer Intern, Fall Co-op, Spring Intern, AI/ML, Database, Infrastructure/DevOps
- **Company** — search and select specific companies
- **Time window** — Past 1 hr / 6 hrs / 24 hrs / 3 days / 7 days / Any time
- **Applied** — toggle to see only jobs you've marked as applied

### Marking applications
Click the **checkmark** on any job card to mark it as applied. Applied jobs are tracked with a timestamp.

### Scraping controls
- **Refresh All** button in the top bar — triggers a full sweep of all 99 companies immediately
- **Fast Refresh** — scrapes only your watchlist companies (fastest way to check top targets)
- **Per-company ↻ button** in the sidebar — re-scrapes a single company on demand

---

## 5. Running a Manual Scrape

### Full sweep (no web server, terminal only)
```bash
source .venv/bin/activate
python scheduler.py --once
```
Useful for testing or running on a schedule via cron.

### Scrape a specific company
```bash
python scheduler.py --companies "Google (Alphabet)" "Stripe" "OpenAI"
```

### Test the scraper for one company
```bash
python3 -c "
from scraper import scrape_company
ats, jobs = scrape_company({'name': 'Stripe', 'url': 'https://stripe.com/jobs'})
print(f'ATS: {ats}, Jobs found: {len(jobs)}')
for j in jobs[:3]:
    print(f'  {j[\"title\"]} | {j[\"location\"]}')
"
```

---

## 6. Adding Companies

### Option A — Add to the H1B spreadsheet
Edit `../H1B_Visa_Sponsor_Companies_CS.xlsx`, then re-run:
```bash
python load_companies.py
```

### Option B — Add directly to `data/extra_companies.json`
Open `data/extra_companies.json` and add entries (the file starts as `[]`):

```json
[
  {
    "name": "Figma",
    "url": "https://www.figma.com/careers/",
    "category": "Extra companies",
    "industry": "Design tools",
    "common_roles": "SWE, Infra, ML",
    "notes": "Added manually"
  },
  {
    "name": "Notion",
    "url": "https://www.notion.so/careers",
    "category": "Extra companies",
    "industry": "Productivity software"
  }
]
```

Extra companies are **internship/co-op only** by design — the SDE 1, SDE 2, AI/ML, New Grad, Database, and DevOps categories only apply to the base H1B list.

> **Tip:** The scraper auto-detects the ATS (Greenhouse, Lever, Ashby, Workday, etc.) from the URL, so you just need a valid career page URL.

---

## 7. Customizing Role Filters

All filters live in **`config.py`**.

### Enable/disable role categories
You can toggle which categories to scrape from the website UI (Settings tab in the sidebar), or permanently in the DB via the API.

### Add a new role pattern
Open `config.py` and find `ROLE_FILTERS`. Each key is a category name, and the value is a list of regex patterns:

```python
ROLE_FILTERS = {
    "SDE 1": [
        r"\bsoftware engineer\b",
        r"\bSDE\s*I\b",
        # add more patterns here
    ],
    "AI / ML": [
        r"\bmachine learning\b",
        r"\bLLM\b",
        # add your pattern:
        r"\bAI research\b",
    ],
    ...
}
```

After editing, restart `app.py` for changes to take effect.

### Seniority filter
Roles with these words in the title are automatically excluded (to focus on 0–3 YoE):
`Senior`, `Staff`, `Principal`, `Lead`, `Manager`, `Director`, `VP`, `Architect`, `L5+`…

Edit `SENIORITY_EXCLUDES` in `config.py` to loosen or tighten this.

---

## 8. Project Structure

```
job_tracker/
├── app.py                  — Flask web server + all API routes
├── scheduler.py            — Background scrape loop (APScheduler)
├── config.py               — All configuration (intervals, filters, paths)
├── db.py                   — SQLite data layer (jobs, runs, scrape state)
├── load_companies.py       — Parses Excel → data/companies.json
├── requirements.txt        — Python dependencies
│
├── scraper/
│   ├── __init__.py         — Main pipeline: ATS detection → dispatch → filter
│   ├── overrides.py        — Curated company → (ATS, handle) map (99 entries)
│   ├── filters.py          — Role matching + seniority filtering
│   ├── location.py         — US-only location filter
│   ├── playwright_worker.py— Playwright scrapers for JS-heavy/blocked sites
│   ├── bigtech.py          — Custom handlers: Amazon, Google, Microsoft, Meta, Apple, Uber
│   ├── greenhouse.py       — Greenhouse ATS scraper
│   ├── lever.py            — Lever ATS scraper
│   ├── ashby.py            — Ashby ATS scraper
│   ├── workday.py          — Workday ATS scraper (parallel pagination)
│   ├── smartrecruiters.py  — SmartRecruiters ATS scraper
│   ├── eightfold.py        — Eightfold ATS scraper
│   ├── oraclehcm.py        — Oracle HCM scraper
│   ├── talentbrew.py       — TalentBrew scraper
│   ├── workable.py         — Workable scraper
│   └── generic.py          — HTML fallback scraper (BeautifulSoup)
│
├── data/
│   ├── companies.json      — Auto-generated from Excel (99 companies)
│   ├── extra_companies.json— Your additional companies (edit this)
│   └── jobs.db             — SQLite database (auto-created on first run)
│
├── templates/
│   └── index.html          — Single-page web UI
└── static/
    └── style.css           — UI styles
```

---

## 9. How Scraping Works

For each company, the pipeline runs in this order:

```
1. bigtech handler?      → Amazon, Google, Microsoft, Meta, Apple, Uber get custom scrapers
        ↓ no
2. overrides.py lookup?  → 93 companies have a curated (ATS, handle) entry
        ↓ no
3. auto-sniff the ATS    → fetch the careers page, detect Greenhouse/Lever/Workday/etc. from HTML signals
        ↓
4. dispatch to ATS scraper → call the right API and return raw job dicts
        ↓
5. filter                → US-only location, role category match, seniority check
        ↓
6. upsert to SQLite      → dedup by (company, title, location, url) hash
```

**ATS platforms supported:**

| Platform | How it's scraped | Example companies |
|---|---|---|
| Greenhouse | Public REST API | Stripe, Airbnb, Databricks, Anthropic |
| Lever | Public REST API | Palantir, Spotify, Plaid |
| Ashby | Public REST API | OpenAI, Snowflake, Confluent, Notion |
| Workday | Public CXS JSON API (parallel) | Intel, NVIDIA, Salesforce, Adobe |
| SmartRecruiters | Public REST API | Canva, ServiceNow, Visa |
| Eightfold | Public REST API | Netflix |
| Oracle HCM | Public OData API | JP Morgan, Oracle |
| TalentBrew | HTML + JSON feed | Intuit, Palo Alto Networks, Capital One |
| Workable | Public widget API | Hugging Face |
| Playwright (browser) | Headless Chromium | Cisco, GitHub, DoorDash, Goldman Sachs, Bloomberg, + 20 others |
| Custom (bigtech.py) | Company-specific APIs | Amazon (`amazon.jobs/en/search.json`), Google (SSR HTML), Microsoft (Eightfold API + Playwright) |

---

## 10. Coverage Alerts

The sidebar shows a **Coverage Alerts** section that surfaces companies whose scraper has returned 0 jobs for 2+ consecutive runs — meaning something may be broken (the site changed, the ATS migrated, or the company paused hiring).

| Badge | Meaning |
|---|---|
| 🔴 | 3+ consecutive zero-result or failed runs — likely broken |
| 🟡 | 2 consecutive zero-result runs — watch list |

Click **Refresh All** to trigger a new sweep and update the alerts. Alerts clear automatically once a company returns jobs again.

You can also query the alerts via the API:
```bash
curl http://127.0.0.1:5055/api/coverage-alerts
```

---

## 11. API Reference

All endpoints return JSON. The web UI uses these internally.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/jobs` | List jobs (supports `?category=`, `?company=`, `?since=<minutes>`, `?applied=1`) |
| `GET` | `/api/stats` | Job counts by category + scheduler status |
| `GET` | `/api/companies` | All companies with job counts + scrape health |
| `GET` | `/api/runs` | Recent scrape run history |
| `GET` | `/api/scrape/status` | On-demand scrape progress |
| `GET` | `/api/coverage-alerts` | Companies with consecutive zero-result runs |
| `POST` | `/api/refresh` | Trigger a full sweep of all companies |
| `POST` | `/api/refresh/fast` | Trigger a fast sweep of watchlist companies only |
| `POST` | `/api/scrape` | Body: `{"companies": ["Stripe", "OpenAI"]}` — scrape specific companies |
| `GET` | `/api/scrape-categories` | Which role categories are enabled |
| `POST` | `/api/scrape-categories` | Body: `{"categories": ["New Grad", "Summer Intern"]}` — enable/disable categories |
| `GET` | `/api/watchlist` | Your watchlist companies |
| `POST` | `/api/watchlist` | Body: `{"companies": ["Google (Alphabet)", "Stripe"]}` — set watchlist |
| `POST` | `/api/jobs/<id>/apply` | Mark a job as applied |

---

## 12. Troubleshooting

### "No module named playwright"
```bash
source .venv/bin/activate
pip install playwright
playwright install chromium
```

### Port 5055 already in use
```bash
# Find and kill whatever is using the port
lsof -ti:5055 | xargs kill -9
# Then restart
python app.py
```

### Jobs not showing up for a company
1. Check the coverage alerts in the sidebar for that company.
2. Run a manual test scrape:
   ```bash
   python3 -c "
   from scraper import scrape_company
   import json
   ats, jobs = scrape_company({'name': 'COMPANY NAME HERE', 'url': 'https://careers.example.com'})
   print(f'ATS: {ats}')
   print(f'Jobs after filter: {len(jobs)}')
   "
   ```
3. If `Jobs after filter: 0` but you know the company is hiring, the role categories you want may be disabled. Check **Settings → Role categories** in the sidebar.

### Playwright scraper times out
Playwright scrapers for JS-heavy sites (Cisco, GitHub, DoorDash, etc.) have a 3-minute timeout. On slow connections they may occasionally fail. This is handled gracefully — the scraper logs a warning and moves on. It will retry on the next scheduled sweep.

To increase the timeout:
```bash
PLAYWRIGHT_WORKER_TIMEOUT=300 python app.py
```

### Database reset
To start fresh with an empty database:
```bash
rm data/jobs.db
python app.py   # re-creates the DB on startup
```

### Scrape is very slow
The default `SCRAPE_MAX_WORKERS` is `1` (sequential). To speed it up, edit `config.py`:
```python
SCRAPE_MAX_WORKERS = 6   # scrape 6 companies in parallel
```
Playwright-based scrapers always run sequentially (they're already parallelized internally).

---

## Quick Reference

```bash
# Start everything
source .venv/bin/activate && python app.py

# One-shot scrape (no web server)
source .venv/bin/activate && python scheduler.py --once

# Scrape specific companies
source .venv/bin/activate && python scheduler.py --companies "Stripe" "OpenAI"

# Check coverage
curl http://127.0.0.1:5055/api/coverage-alerts | python3 -m json.tool

# Reset database
rm data/jobs.db && python app.py
```
