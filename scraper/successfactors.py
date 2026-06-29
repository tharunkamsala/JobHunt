"""SAP SuccessFactors career site scraper.

SAP SuccessFactors (SF) powers enterprise career sites. There is no standard
public JSON API, but many SF deployments expose an XML job feed at a
predictable URL:

    {base_url}?career_ns=job_listing_summary&resultType=XML

When the XML feed is unavailable we fall back to HTML parsing of the Career
Site Builder (CSB) page.

Because SuccessFactors deployments are heavily customised, this scraper is
best-effort.  It handles the most common configurations but may not cover
every tenant.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse, urlencode
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT, USER_AGENT

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml,*/*",
}

_MAX_PAGES = 15
_PAGE_SIZE = 50


# ---------------------------------------------------------------------------
# XML feed parsing
# ---------------------------------------------------------------------------

def _try_xml_feed(base_url: str) -> list[dict] | None:
    """Attempt to fetch the SF XML job feed.  Returns None if unavailable."""
    # Build the XML feed URL.
    sep = "&" if "?" in base_url else "?"
    xml_url = f"{base_url}{sep}career_ns=job_listing_summary&resultType=XML"

    try:
        r = requests.get(xml_url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        if "xml" not in r.headers.get("Content-Type", "").lower() and "<job" not in r.text[:500].lower():
            return None
    except Exception:
        return None

    return _parse_xml(r.text, base_url)


def _parse_xml(xml_text: str, base_url: str) -> list[dict]:
    """Parse SF XML feed into normalised job dicts."""
    jobs: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return jobs

    # SuccessFactors XML feeds vary in namespace usage.  Strip namespaces for
    # simpler access.
    ns_re = re.compile(r"\{[^}]+\}")

    for elem in root.iter():
        elem.tag = ns_re.sub("", elem.tag)

    for job_elem in root.iter("job"):
        title = ""
        location = ""
        url = ""
        job_id = ""
        posted_at = None

        for child in job_elem:
            tag = ns_re.sub("", child.tag).lower()
            text = (child.text or "").strip()
            if tag in ("title", "jobtitle", "job_title"):
                title = text
            elif tag in ("location", "joblocation", "job_location"):
                location = text
            elif tag in ("url", "joburl", "job_url", "applyurl", "detail_url"):
                url = text
            elif tag in ("id", "jobid", "job_id", "job_req_id", "requisitionid"):
                job_id = text
            elif tag in ("posted", "posteddate", "posted_date", "postingdate"):
                posted_at = text or None

        if not title:
            continue
        if url and not url.startswith("http"):
            url = urljoin(base_url, url)
        jobs.append({
            "title": title,
            "location": location or None,
            "url": url or None,
            "posting_id": f"sf-{job_id}" if job_id else None,
            "posted_at": posted_at,
        })

    return jobs


# ---------------------------------------------------------------------------
# HTML fallback
# ---------------------------------------------------------------------------

def _scrape_html(base_url: str) -> list[dict]:
    """Fallback: scrape the Career Site Builder HTML page."""
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(_MAX_PAGES):
        url = base_url
        if page > 0:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}start={page * _PAGE_SIZE}"

        try:
            r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                break
        except Exception as e:
            log.warning("SuccessFactors HTML scrape page %d failed: %s", page, e)
            break

        soup = BeautifulSoup(r.text, "lxml")

        # SF CSB pages often render jobs in table rows or list items.
        # Common patterns:
        #   - <a> links matching /career?...job_req_id=...
        #   - <a> links matching /jobs/{id}
        #   - <tr> rows with class containing "jobResult"
        job_links = soup.find_all(
            "a",
            href=re.compile(r"(job_req_id=|/jobs/\d+|/career\?.*career_job_req_id)", re.I),
        )

        if not job_links:
            # Broader: any link whose text looks like a job title (>5 chars,
            # not navigation).
            for link in soup.find_all("a", href=True):
                href = link.get("href", "")
                text = link.get_text(strip=True)
                if (
                    text
                    and len(text) > 5
                    and ("career" in href or "job" in href)
                    and not re.match(r"(home|about|contact|sign|log|apply|search|back)", text, re.I)
                ):
                    job_links.append(link)

        page_new = 0
        for link in job_links:
            href = link.get("href", "")
            title = link.get_text(strip=True)
            if not title or len(title) < 4:
                continue

            # Extract some kind of ID.
            m = re.search(r"job_req_id=(\d+)", href) or re.search(r"/jobs/(\d+)", href)
            job_id = m.group(1) if m else href
            dedup_key = f"sf-{job_id}"
            if dedup_key in seen_ids:
                continue
            seen_ids.add(dedup_key)

            full_url = urljoin(base_url, href)

            # Try to find location near the link.
            location = None
            parent = link.find_parent(["tr", "div", "li"])
            if parent:
                for el in parent.find_all(["td", "span", "div"]):
                    text = el.get_text(strip=True)
                    if text and text != title and re.search(
                        r"(,\s*[A-Z]{2}\b|Remote|United States|US$|USA)", text, re.I
                    ):
                        location = text
                        break

            jobs.append({
                "title": title,
                "location": location,
                "url": full_url,
                "posting_id": dedup_key if m else None,
                "posted_at": None,
            })
            page_new += 1

        if page_new == 0:
            break

    return jobs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch(base_url: str) -> list[dict]:
    """Scrape job listings from a SAP SuccessFactors career site.

    Args:
        base_url: Full URL of the career site landing page (varies by tenant).

    Returns:
        List of job dicts: {title, location, url, posting_id, posted_at}.
    """
    # Try the structured XML feed first — it's the most reliable when present.
    xml_jobs = _try_xml_feed(base_url)
    if xml_jobs is not None and len(xml_jobs) > 0:
        log.info("SuccessFactors [%s] XML feed: %d jobs", base_url[:60], len(xml_jobs))
        return xml_jobs

    # Fall back to HTML scraping.
    html_jobs = _scrape_html(base_url)
    log.info("SuccessFactors [%s] HTML scrape: %d jobs", base_url[:60], len(html_jobs))
    return html_jobs
