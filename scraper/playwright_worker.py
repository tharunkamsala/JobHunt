"""Standalone Playwright worker for sites that require browser rendering.

Run as a subprocess so a Playwright hang or sandbox failure can't take
down the main scrape sweep. Usage:

    python -m scraper.playwright_worker <target>

Where ``<target>`` is one of: ``microsoft``, ``meta``.

The worker prints a single JSON object to stdout::

    {"target": "microsoft", "ok": true, "jobs": [{...}, ...]}

On any internal failure we still exit 0 and emit ``ok: false`` so the
caller can distinguish "site returned nothing" from "subprocess crashed".
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode


BASE_DIR = Path(__file__).resolve().parent.parent

_PW_BROWSERS = BASE_DIR / ".venv" / "playwright-browsers"
if _PW_BROWSERS.exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_PW_BROWSERS)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
PAGE_TIMEOUT_MS = 30_000
WAIT_AFTER_LOAD_MS = 4_000


def _scrape_cards(page, link_selector: str) -> list[dict]:
    """Scroll the page a few times and collect anchor cards."""
    seen: set[str] = set()
    cards: list[dict] = []
    try:
        page.wait_for_selector(link_selector, timeout=WAIT_AFTER_LOAD_MS)
    except Exception:
        page.wait_for_timeout(min(WAIT_AFTER_LOAD_MS, 3000))
    for _ in range(5):
        rows = page.eval_on_selector_all(
            link_selector,
            """els => els.map(e => ({
                href: e.href || e.getAttribute('href') || '',
                text: e.innerText || '',
                aria: e.getAttribute('aria-label') || ''
            }))""",
        )
        for row in rows:
            href = (row.get("href") or "").strip()
            text = (row.get("text") or "").strip()
            if not href or href in seen or not text:
                continue
            seen.add(href)
            cards.append({"href": href, "text": text, "aria": row.get("aria") or ""})
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(1200)
    return cards


def scrape_microsoft() -> list[dict]:
    """Microsoft Careers — Eightfold SPA. Iterates a few search queries."""
    from playwright.sync_api import sync_playwright

    queries = [
        "software engineer",
        "machine learning",
        "data engineer",
        "intern",
        "university graduate",
        "new grad",
    ]
    out: list[dict] = []
    seen: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            for q in queries:
                params = {"query": q, "location": "United States"}
                page_url = f"https://apply.careers.microsoft.com/careers?{urlencode(params)}"
                try:
                    page.goto(page_url, wait_until="domcontentloaded",
                              timeout=PAGE_TIMEOUT_MS)
                except Exception:
                    continue
                cards = _scrape_cards(page, 'a[href*="/careers/job/"]')
                for c in cards:
                    href = c["href"]
                    m = re.search(r"/job/(\d+)", href)
                    pid = m.group(1) if m else None
                    if pid and pid in seen:
                        continue
                    if pid:
                        seen.add(pid)
                    lines = [x.strip() for x in c["text"].splitlines() if x.strip()]
                    if len(lines) < 2:
                        continue
                    title = re.sub(r"\s+", " ", lines[0]).strip()
                    loc = lines[1]
                    out.append({
                        "title": title,
                        "location": loc,
                        "url": href,
                        "posting_id": pid,
                        "posted_at": None,
                    })
            context.close()
        finally:
            browser.close()
    return out


def scrape_meta() -> list[dict]:
    """Meta Careers — React SPA at metacareers.com/jobsearch."""
    from playwright.sync_api import sync_playwright

    queries = [
        "software engineer",
        "machine learning",
        "data engineer",
        "intern",
        "new grad",
        "university",
    ]
    out: list[dict] = []
    seen: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()
            for q in queries:
                page_url = f"https://www.metacareers.com/jobsearch?{urlencode({'q': q})}"
                try:
                    page.goto(page_url, wait_until="domcontentloaded",
                              timeout=PAGE_TIMEOUT_MS)
                except Exception:
                    continue
                cards = _scrape_cards(page, 'a[href*="/profile/job_details/"]')
                for c in cards:
                    href = c["href"]
                    m = re.search(r"/job_details/(\d+)", href)
                    pid = m.group(1) if m else None
                    if pid and pid in seen:
                        continue
                    if pid:
                        seen.add(pid)
                    lines = [x.strip() for x in c["text"].splitlines()
                             if x.strip() and x.strip() != "·" and x.strip() != "⋅"]
                    if len(lines) < 2:
                        continue
                    out.append({
                        "title": re.sub(r"\s+", " ", lines[0]).strip(),
                        "location": lines[1],
                        "url": href,
                        "posting_id": pid,
                        "posted_at": None,
                    })
            context.close()
        finally:
            browser.close()
    return out


def scrape_uber() -> list[dict]:
    """Uber Careers (uber.com/careers/list).

    The listing page calls a session-gated JSON API. We load the page in a
    browser, capture the initial API response, then click "Show more openings"
    repeatedly until the button disappears or no new jobs are added.
    """
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    seen: set[str] = set()

    def _loc_str(j: dict) -> str | None:
        all_locs = j.get("allLocations") or []
        if all_locs and isinstance(all_locs, list):
            parts = []
            for loc in all_locs[:3]:
                city = loc.get("city") or ""
                region = loc.get("region") or ""
                country = loc.get("countryName") or loc.get("country") or ""
                fragment = ", ".join(x for x in [city, region, country] if x)
                if fragment:
                    parts.append(fragment)
            return "; ".join(parts) if parts else None
        loc = j.get("location")
        if isinstance(loc, dict):
            city = loc.get("city") or ""
            region = loc.get("region") or ""
            country = loc.get("countryName") or loc.get("country") or ""
            return ", ".join(x for x in [city, region, country] if x) or None
        return str(loc) if loc else None

    def _ingest(body: dict) -> int:
        results = body.get("data", {}).get("results") or []
        added = 0
        for j in results:
            jid = str(j.get("id") or "")
            title = j.get("title")
            if not jid or not title or jid in seen:
                continue
            seen.add(jid)
            added += 1
            out.append({
                "title": title,
                "location": _loc_str(j),
                "url": f"https://www.uber.com/careers/list/job-{jid}/",
                "posting_id": jid,
                "posted_at": j.get("creationDate") or j.get("updatedDate"),
            })
        return added

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()

            captured: list[dict] = []

            def on_response(r):
                if "loadSearchJobsResults" in r.url and r.status == 200:
                    try:
                        captured.append(r.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto("https://www.uber.com/careers/list/", wait_until="domcontentloaded",
                      timeout=PAGE_TIMEOUT_MS)
            page.wait_for_timeout(4000)

            # Ingest first batch from initial page load
            for body in captured:
                _ingest(body)

            # Click "Show more openings" until it disappears or stops adding jobs
            show_more = 'button:has-text("Show more openings"), button:has-text("Load more")'
            no_progress = 0
            for _ in range(50):  # cap at 50 clicks = ~500 total jobs
                btn = page.locator(show_more).first
                if btn.count() == 0 or not btn.is_visible():
                    break
                before = len(out)
                captured.clear()
                btn.click()
                page.wait_for_timeout(2500)
                for body in captured:
                    _ingest(body)
                if len(out) == before:
                    no_progress += 1
                    if no_progress >= 3:
                        break
                else:
                    no_progress = 0

            context.close()
        finally:
            browser.close()
    return out


def _generic_scroll_scrape(
    url: str,
    card_selector: str,
    *,
    wait_selector: str | None = None,
    next_btn_selector: str | None = None,
    max_pages: int = 20,
    scroll_rounds: int = 6,
    wait_ms: int = 2500,
) -> list[dict]:
    """Generic Playwright scraper: load URL, scroll, collect all job-card anchors.
    If next_btn_selector is provided, also click through paginated pages."""
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    seen: set[str] = set()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=USER_AGENT)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            except Exception:
                return out

            for page_num in range(max_pages):
                try:
                    if wait_selector:
                        try:
                            page.wait_for_selector(wait_selector, timeout=WAIT_AFTER_LOAD_MS)
                        except Exception:
                            page.wait_for_timeout(min(WAIT_AFTER_LOAD_MS, 3000))
                    else:
                        page.wait_for_timeout(2000)
                except Exception:
                    pass

                for _ in range(scroll_rounds):
                    cards = page.eval_on_selector_all(
                        card_selector,
                        """els => els.map(e => ({
                            href: e.href || e.getAttribute('href') || '',
                            text: (e.innerText || e.textContent || '').trim(),
                            aria: e.getAttribute('aria-label') || ''
                        }))""",
                    )
                    for c in cards:
                        href = (c.get("href") or "").strip()
                        text = re.sub(r"\s+", " ", (c.get("text") or c.get("aria") or "")).strip()
                        if not href or href in seen or not text:
                            continue
                        seen.add(href)
                        lines = [l.strip() for l in text.splitlines() if l.strip()]
                        title = lines[0] if lines else text[:120]
                        loc = lines[1] if len(lines) > 1 else None
                        m = re.search(r"/(?:job|position|opening|role|req)s?[-/](\w[\w-]{2,40})", href, re.I)
                        pid = m.group(1) if m else None
                        out.append({
                            "title": title,
                            "location": loc,
                            "url": href,
                            "posting_id": pid,
                            "posted_at": None,
                        })
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(1000)

                if not next_btn_selector:
                    break
                btn = page.locator(next_btn_selector).first
                if not btn.count() or not btn.is_visible():
                    break
                btn.click()
                page.wait_for_timeout(wait_ms)

            ctx.close()
        finally:
            browser.close()
    return out


def _intercept_json_scrape(
    url: str,
    api_pattern: str,
    parse_fn,
    *,
    extra_actions=None,
    max_responses: int = 30,
) -> list[dict]:
    """Navigate to url, intercept XHR/fetch calls matching api_pattern, parse each response."""
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    seen: set[str] = set()
    captured: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            ctx = browser.new_context(user_agent=USER_AGENT)
            page = ctx.new_page()

            def on_response(r):
                if len(captured) >= max_responses:
                    return
                if api_pattern in r.url and r.status == 200:
                    try:
                        captured.append(r.json())
                    except Exception:
                        pass

            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            except Exception:
                return out
            page.wait_for_timeout(4000)

            if extra_actions:
                extra_actions(page)

            for body in captured:
                for job in parse_fn(body):
                    jid = job.get("posting_id") or job.get("url") or ""
                    if jid and jid in seen:
                        continue
                    if jid:
                        seen.add(jid)
                    out.append(job)
            ctx.close()
        finally:
            browser.close()
    return out


# ---------------------------------------------------------------------------
# Cisco — Phenom People SPA at jobs.cisco.com

def scrape_cisco() -> list[dict]:
    return _generic_scroll_scrape(
        "https://jobs.cisco.com/jobs/SearchJobs/?locationStr=United+States&%3Atags5=LoaCon_US",
        "a[href*='/jobs/ProjectDetail/']",
        wait_selector="a[href*='/jobs/ProjectDetail/']",
        next_btn_selector="a[class*='next'], button[aria-label='Next page'], a[aria-label='Next']",
        max_pages=15,
        scroll_rounds=3,
    )


# ---------------------------------------------------------------------------
# GitHub — iCIMS SPA at github.careers

def scrape_github() -> list[dict]:
    return _generic_scroll_scrape(
        "https://github.careers/careers-home",
        "a[href*='/careers-home/job/']",
        wait_selector="a[href*='/careers-home/job/']",
        next_btn_selector="a[aria-label='Next page'], button[aria-label='Next page']",
        max_pages=20,
    )


# ---------------------------------------------------------------------------
# DoorDash — custom site (blocks raw HTTP requests)

def scrape_doordash() -> list[dict]:
    return _generic_scroll_scrape(
        "https://careersatdoordash.com/jobs/?department=Engineering&location=United+States",
        "a[href*='/jobs/']",
        wait_selector="a[href*='/jobs/']",
        next_btn_selector="a[aria-label='Next'], button[aria-label='Next page']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# Snap Inc. — custom SPA at careers.snap.com

def scrape_snap() -> list[dict]:
    return _generic_scroll_scrape(
        "https://careers.snap.com/jobs?category=Engineering&location=United+States",
        "a[href*='/jobs/']",
        wait_selector="a[href*='/jobs/']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# Atlassian — custom careers SPA

def scrape_atlassian() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.atlassian.com/company/careers/all-jobs?team=Engineering&location=United+States",
        "a[href*='/careers/detail/']",
        wait_selector="a[href*='/careers/detail/']",
        next_btn_selector="button[aria-label='Next page'], a[aria-label='Next']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# Rippling — own HR platform

def scrape_rippling() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.rippling.com/careers",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# Miro — custom careers SPA

def scrape_miro() -> list[dict]:
    return _generic_scroll_scrape(
        "https://miro.com/careers/open-positions/",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# Retool — custom careers page

def scrape_retool() -> list[dict]:
    return _generic_scroll_scrape(
        "https://retool.com/careers",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=8,
    )


# ---------------------------------------------------------------------------
# Snyk — custom careers page

def scrape_snyk() -> list[dict]:
    return _generic_scroll_scrape(
        "https://snyk.io/careers/open-positions/",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# SpaceX — custom careers

def scrape_spacex() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.spacex.com/careers/jobs/?department=Engineering",
        "a[href*='/careers/jobs/']",
        wait_selector="a[href*='/careers/jobs/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# Bloomberg — careers.bloomberg.com

def scrape_bloomberg() -> list[dict]:
    return _generic_scroll_scrape(
        "https://careers.bloomberg.com/job/search?el=Engineering",
        "a[href*='/job/detail/']",
        wait_selector="a[href*='/job/detail/']",
        next_btn_selector="a[aria-label='Next page'], button[aria-label='Next']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# Goldman Sachs

def scrape_goldman() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.goldmansachs.com/careers/students-and-graduates/our-programs/",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=12,
    )


# ---------------------------------------------------------------------------
# Citadel / Citadel Securities

def scrape_citadel() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.citadel.com/careers/open-positions/",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# Two Sigma

def scrape_twosigma() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.twosigma.com/careers/job-listings/",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# D. E. Shaw

def scrape_deshaw() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.deshaw.com/careers/opportunities",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


# ---------------------------------------------------------------------------
# Morgan Stanley

def scrape_morganstanley() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.morganstanley.com/careers/students-graduates",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        next_btn_selector="a[aria-label='Next page'], button[aria-label='Next page']",
        max_pages=12,
    )


# ---------------------------------------------------------------------------
# PayPal — Eightfold with auth; fall back to careers page

def scrape_paypal() -> list[dict]:
    return _generic_scroll_scrape(
        "https://careers.pypl.com/home/",
        "a[href*='/jobs/']",
        wait_selector="a[href*='/jobs/']",
        next_btn_selector="a[aria-label='Next page'], button[aria-label='Next page']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# American Express — Eightfold with auth; careers.americanexpress.com

def scrape_amex() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.americanexpress.com/en-us/careers/job-search/",
        "a[href*='/careers/job-details/']",
        wait_selector="a[href*='/careers/job-details/']",
        next_btn_selector="button[aria-label='Next page']",
        max_pages=15,
    )


# ---------------------------------------------------------------------------
# Deloitte

def scrape_deloitte() -> list[dict]:
    return _generic_scroll_scrape(
        "https://apply.deloitte.com/careers/SearchJobs/?orgIds=&alp=6252001&alt=2",
        "a[href*='/careers/JobDetail/']",
        wait_selector="a[href*='/careers/JobDetail/']",
        next_btn_selector="a[class*='next'], a[aria-label='Next']",
        max_pages=20,
    )


# ---------------------------------------------------------------------------
# Accenture

def scrape_accenture() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.accenture.com/us-en/careers/jobsearch?jk=software%20engineer&country=United+States",
        "a[href*='/careers/jobdetails/']",
        wait_selector="a[href*='/careers/jobdetails/']",
        next_btn_selector="button[aria-label='Next page'], a[aria-label='Next page']",
        max_pages=20,
    )


# ---------------------------------------------------------------------------
# IBM

def scrape_ibm() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.ibm.com/careers/search?field_keyword_08[0]=Software%20Engineering&field_country_tok=United+States",
        "a[href*='/careers/details/']",
        wait_selector="a[href*='/careers/details/']",
        next_btn_selector="button[aria-label='Next page'], a[aria-label='Next page']",
        max_pages=20,
    )


# ---------------------------------------------------------------------------
# Qualcomm

def scrape_qualcomm() -> list[dict]:
    return _generic_scroll_scrape(
        "https://careers.qualcomm.com/careers/job?domain=qualcomm.com&pid=398309899&sort_by=relevance&job_index=0",
        "a[href*='/careers/job']",
        wait_selector="a[href*='/careers/job']",
        next_btn_selector="button[aria-label='Next page'], a[aria-label='Next page']",
        max_pages=20,
    )


# ---------------------------------------------------------------------------
# Hashicorp (now part of IBM)

def scrape_hashicorp() -> list[dict]:
    return _generic_scroll_scrape(
        "https://www.hashicorp.com/en/careers",
        "a[href*='/careers/']",
        wait_selector="a[href*='/careers/']",
        max_pages=10,
    )


def scrape_twitterx() -> list[dict]:
    """Twitter/X careers — best-effort scrape; full listings require login."""
    return _generic_scroll_scrape(
        "https://careers.x.com/en",
        "a[href*='/en/jobs/']",
        wait_selector="a[href*='/en/jobs/']",
        max_pages=10,
    )


TARGETS = {
    "microsoft":    scrape_microsoft,
    "meta":         scrape_meta,
    "uber":         scrape_uber,
    "cisco":        scrape_cisco,
    "github":       scrape_github,
    "doordash":     scrape_doordash,
    "snap":         scrape_snap,
    "atlassian":    scrape_atlassian,
    "rippling":     scrape_rippling,
    "miro":         scrape_miro,
    "retool":       scrape_retool,
    "snyk":         scrape_snyk,
    "spacex":       scrape_spacex,
    "bloomberg":    scrape_bloomberg,
    "goldman":      scrape_goldman,
    "citadel":      scrape_citadel,
    "twosigma":     scrape_twosigma,
    "deshaw":       scrape_deshaw,
    "morganstanley": scrape_morganstanley,
    "paypal":       scrape_paypal,
    "amex":         scrape_amex,
    "deloitte":     scrape_deloitte,
    "accenture":    scrape_accenture,
    "ibm":          scrape_ibm,
    "qualcomm":     scrape_qualcomm,
    "hashicorp":    scrape_hashicorp,
    "twitterx":     scrape_twitterx,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target")
    args = ap.parse_args()
    if args.target not in TARGETS:
        json.dump({"target": args.target, "ok": False,
                   "error": f"Unknown target '{args.target}'", "jobs": []}, sys.stdout)
        sys.stdout.flush()
        return 0
    fn = TARGETS[args.target]
    try:
        jobs = fn()
        json.dump({"target": args.target, "ok": True, "jobs": jobs}, sys.stdout)
    except Exception as e:
        json.dump(
            {
                "target": args.target,
                "ok": False,
                "error": f"{type(e).__name__}: {str(e).splitlines()[0]}",
                "jobs": [],
            },
            sys.stdout,
        )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
