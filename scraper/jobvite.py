"""Jobvite career site scraper.

Jobvite career portals are server-side rendered HTML at
``https://jobs.jobvite.com/{slug}`` (or custom domains).

No public JSON API exists — we parse the HTML listing page directly.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,*/*",
}

_MAX_PAGES = 15


def _extract_jobs_from_html(html: str, base_url: str) -> list[dict]:
    """Parse a Jobvite listing page and return job dicts."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    # Jobvite typically renders job listings in table rows or divs.
    # Job detail links follow the pattern: /job/{jobId} where jobId is
    # a short alphanumeric string (e.g., oEX1ufwP).
    job_links = soup.find_all("a", href=re.compile(r"/job/[A-Za-z0-9]+"))

    for link in job_links:
        href = link.get("href", "")
        if not href:
            continue

        # Extract the Jobvite job ID from the URL.
        m = re.search(r"/job/([A-Za-z0-9]+)", href)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        url = urljoin(base_url, href)

        # Try to find location and department in sibling/parent elements.
        location = None
        parent = link.find_parent(["tr", "div", "li", "td"])
        if parent:
            # Jobvite often uses separate cells or spans for location/dept.
            cells = parent.find_all(["td", "span", "div"])
            for cell in cells:
                text = cell.get_text(strip=True)
                if text and text != title:
                    # Heuristic: locations contain commas, state codes, or
                    # common location words.
                    if re.search(
                        r"(,\s*[A-Z]{2}\b|Remote|United States|US$|USA|\b[A-Z]{2}\s+\d{5})",
                        text,
                        re.I,
                    ):
                        location = text
                        break

        jobs.append({
            "title": title,
            "location": location,
            "url": url,
            "posting_id": f"jv-{job_id}",
            "posted_at": None,
        })

    return jobs


def _find_next_page_url(html: str, base_url: str) -> str | None:
    """Look for a 'next page' link in Jobvite pagination."""
    soup = BeautifulSoup(html, "lxml")
    # Jobvite may use "Show More" or numbered pagination links.
    next_link = soup.find("a", string=re.compile(r"next|show\s*more|›|»", re.I))
    if next_link and next_link.get("href"):
        return urljoin(base_url, next_link["href"])
    # Some sites use class-based next buttons.
    next_link = soup.find("a", class_=re.compile(r"next|jv-page-next", re.I))
    if next_link and next_link.get("href"):
        return urljoin(base_url, next_link["href"])
    return None


def fetch(slug: str) -> list[dict]:
    """Scrape all job listings from a Jobvite career site.

    Args:
        slug: Company identifier (e.g., 'twitch' for
              ``jobs.jobvite.com/twitch``). Can also be a full URL.

    Returns:
        List of job dicts: {title, location, url, posting_id, posted_at}.
    """
    if slug.startswith("http"):
        base_url = slug.rstrip("/")
    else:
        base_url = f"https://jobs.jobvite.com/{slug}"

    all_jobs: list[dict] = []
    seen_ids: set[str] = set()
    current_url: str | None = base_url

    for page in range(_MAX_PAGES):
        if current_url is None:
            break
        try:
            r = requests.get(current_url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                log.warning("Jobvite %s page %d returned %d", slug, page, r.status_code)
                break
        except Exception as e:
            log.warning("Jobvite %s page %d failed: %s", slug, page, e)
            break

        page_jobs = _extract_jobs_from_html(r.text, current_url)
        new_count = 0
        for j in page_jobs:
            pid = j.get("posting_id", "")
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_jobs.append(j)
                new_count += 1

        if new_count == 0:
            break

        current_url = _find_next_page_url(r.text, current_url)

    log.info("Jobvite [%s] scraped %d jobs across %d page(s)", slug, len(all_jobs), page + 1)
    return all_jobs
