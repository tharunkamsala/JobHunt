"""Oracle HCM Candidate Experience public job search.

Many enterprise career sites are backed by Oracle HCM Candidate Experience.
The public site bootstrap exposes enough config to call the JSON requisition
search endpoint directly without browser automation.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import requests

from config import REQUEST_TIMEOUT, USER_AGENT


HEADERS = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*"}
JSON_HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
FACETS = "LOCATIONS;JOB_FAMILY;POSTING_DATES;JOB_FUNCTION;ORGANIZATIONS"
PAGE_SIZE = 100


def _extract_cx_config(html: str) -> tuple[str, str, str] | None:
    m = re.search(r"var\s+CX_CONFIG\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return None
    blob = m.group(1)

    def _pick(pattern: str) -> str | None:
        mm = re.search(pattern, blob)
        return mm.group(1).strip() if mm else None

    api_base = _pick(r"apiBaseUrl:\s*'([^']+)'")
    site_number = _pick(r"siteNumber:\s*'([^']+)'")
    site_lang = _pick(r"siteLang:\s*'([^']+)'") or "en"
    if not api_base or not site_number:
        return None
    return api_base.rstrip("/"), site_number, site_lang


def _parse_posted_date(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=None).isoformat(timespec="seconds")
        except Exception:
            continue
    return None


def _job_url(page_url: str, site_lang: str, job_id: str) -> str:
    root = re.sub(r"/jobs(?:\?.*)?$", "", page_url.rstrip("/"))
    if "/sites/" not in root:
        root = root.rstrip("/")
    return f"{root}/job/{job_id}"


def fetch(page_url: str) -> list[dict]:
    try:
        html = requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT).text
    except Exception:
        return []
    cfg = _extract_cx_config(html)
    if not cfg:
        return []
    api_base, site_number, site_lang = cfg
    endpoint = (
        f"{api_base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
        "?onlyData=true"
        "&expand=requisitionList.secondaryLocations,requisitionList.requisitionFlexFields"
        "&finder=findReqs;:findParams:"
    )

    jobs: list[dict] = []
    offset = 0
    total = None
    while True:
        find_params = (
            f"siteNumber={site_number},facetsList={FACETS},limit={PAGE_SIZE},offset={offset}"
        )
        url = endpoint.replace(":findParams:", find_params)
        try:
            r = requests.get(url, headers=JSON_HEADERS, timeout=REQUEST_TIMEOUT)
        except Exception:
            break
        if r.status_code != 200:
            break
        try:
            data = r.json()
        except json.JSONDecodeError:
            break
        items = data.get("items") or []
        if not items:
            break
        item = items[0] or {}
        reqs = item.get("requisitionList") or []
        if total is None:
            try:
                total = int(item.get("TotalJobsCount"))
            except Exception:
                total = 0
        for req in reqs:
            job_id = str(req.get("Id") or "").strip()
            title = str(req.get("Title") or "").strip()
            if not job_id or not title:
                continue
            jobs.append({
                "title": title,
                "location": (req.get("PrimaryLocation") or "").strip() or None,
                "url": _job_url(page_url, site_lang, job_id),
                "posting_id": job_id,
                "posted_at": _parse_posted_date(req.get("PostedDate")),
            })
        offset += len(reqs)
        if not reqs:
            break
        if total is not None and total > 0 and offset >= total:
            break
        if len(reqs) < PAGE_SIZE:
            break
        if offset > 5000:
            break
    return jobs
