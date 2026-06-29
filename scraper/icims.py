"""iCIMS career site scraper.

iCIMS career portals are server-side rendered HTML with no public JSON API.
We scrape the search/listing page and parse with BeautifulSoup.

URL patterns:
  - Listing: https://careers-{slug}.icims.com/jobs/search?pr=25&schemaId=&o=relevance
  - Detail:  https://careers-{slug}.icims.com/jobs/{id}/{title-slug}/job
  - Sitemap: https://careers-{slug}.icims.com/sitemap.xml  (not always available)

CSS class patterns use the ``iCIMS_`` prefix for key elements.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, urlunparse

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# Maximum pages to paginate through before stopping.
_MAX_PAGES = 20
_PAGE_SIZE = 25


def _build_search_url(slug: str, page: int = 0) -> str:
    """Build the iCIMS search URL for the given slug and page offset."""
    base = f"https://careers-{slug}.icims.com/jobs/search"
    params = {
        "pr": str(_PAGE_SIZE),
        "o": "relevance",
        "schemaId": "",
    }
    if page > 0:
        params["sp"] = str(page * _PAGE_SIZE)
    return f"{base}?{urlencode(params)}"


def _extract_jobs_from_html(html: str, base_url: str) -> list[dict]:
    """Parse an iCIMS search results page and return job dicts."""
    soup = BeautifulSoup(html, "lxml")
    jobs: list[dict] = []

    # iCIMS typically lists jobs in elements with class containing
    # "iCIMS_JobsTable" or within divs wrapping individual job rows.
    # The job title link usually has class "iCIMS_Anchor" and lives
    # inside a container with class containing "Title".
    rows = soup.select(".iCIMS_JobsTable .row, .iCIMS_MainWrapper .iCIMS_ListBody tr, [class*='listRow']")
    if not rows:
        # Fallback: look for any link pointing to /jobs/{id}/
        rows = [soup]

    # Broader fallback: find all links matching the job URL pattern.
    job_links = soup.find_all("a", href=re.compile(r"/jobs/\d+/"))
    seen_ids: set[str] = set()

    for link in job_links:
        href = link.get("href", "")
        if not href:
            continue
        # Extract job ID from URL: /jobs/{id}/...
        m = re.search(r"/jobs/(\d+)/", href)
        if not m:
            continue
        job_id = m.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        title = link.get_text(strip=True)
        if not title or len(title) < 3:
            continue

        # Build full URL
        url = urljoin(base_url, href.split("?")[0])

        # Try to find location near this link.
        location = None
        parent = link.find_parent(["tr", "div", "li"])
        if parent:
            loc_el = parent.find(class_=re.compile(r"iCIMS.*Location|location", re.I))
            if loc_el:
                location = loc_el.get_text(strip=True)
            else:
                # Look for spans/divs after the title that might contain location.
                for sib in parent.find_all(["span", "div", "td"]):
                    text = sib.get_text(strip=True)
                    if text and text != title and ("," in text or "Remote" in text):
                        location = text
                        break

        jobs.append({
            "title": title,
            "location": location,
            "url": url,
            "posting_id": f"icims-{job_id}",
            "posted_at": None,
        })

    return jobs


def _has_next_page(html: str) -> bool:
    """Check if there's a next-page link in the pagination."""
    soup = BeautifulSoup(html, "lxml")
    # iCIMS pagination typically uses links with "Next" text or
    # class containing "pager" or "next".
    next_link = soup.find("a", string=re.compile(r"next|›|»", re.I))
    if next_link:
        return True
    next_link = soup.find("a", class_=re.compile(r"next|Next", re.I))
    if next_link:
        return True
    return False


def fetch(slug: str) -> list[dict]:
    """Scrape all job listings from an iCIMS career site.

    Args:
        slug: Company identifier used in the subdomain
              (e.g., 'boeing' for careers-boeing.icims.com).

    Returns:
        List of job dicts: {title, location, url, posting_id, posted_at}.
    """
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(_MAX_PAGES):
        url = _build_search_url(slug, page)
        try:
            r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                log.warning("iCIMS %s page %d returned %d", slug, page, r.status_code)
                break
        except Exception as e:
            log.warning("iCIMS %s page %d failed: %s", slug, page, e)
            break

        page_jobs = _extract_jobs_from_html(r.text, url)
        new_count = 0
        for j in page_jobs:
            pid = j.get("posting_id", "")
            if pid not in seen_ids:
                seen_ids.add(pid)
                all_jobs.append(j)
                new_count += 1

        if new_count == 0 or not _has_next_page(r.text):
            break

    log.info("iCIMS [%s] scraped %d jobs across %d page(s)", slug, len(all_jobs), page + 1)
    return all_jobs
