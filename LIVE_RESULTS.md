# Verification — October 12, 2026 (America/New_York)

Local Python 3.13.7, Playwright 1.63.0, actual downloaded Chromium.
Dependencies and Chromium installed successfully. 18 automated fixture/mock
tests pass. They cover rules, persistence, structured details, recovery,
Telegram formatting, API count validation, robots precedence and workflow
structure; they do not replace live integration tests.

## Real job extraction

| Source | Validated descriptions | Scope and status |
|---|---:|---|
| Microsoft | 2 | Actual official application portal; deliberately bounded, Incomplete |
| Amazon | 2 | Actual official careers UI; deliberately bounded, Incomplete |
| NVIDIA | 2 | Actual official jobs portal; deliberately bounded, Incomplete |
| Cloudflare Greenhouse | 434 of 434 | Full documented public API board after real browser visit, Verified Complete |
| Databricks Greenhouse | 896 of 896 | Full documented public API board after real browser visit, Verified Complete |

Microsoft/NVIDIA detail pages supply JSON-LD JobPosting data. Amazon's page
uses validated visible title, job ID, US job-details location, Description,
Basic Qualifications and Preferred Qualifications sections. Dates missing
from the source remain unspecified; Greenhouse updated_at is not mislabelled
as a posting date. Both Greenhouse checks launched together with isolated
browsers. The initial mandatory bounded scan also launched concurrently.

## Access policy and repairs

The original Microsoft marketing site's robots endpoint returned HTML and
was conservatively blocked. Python's standard robots parser also falsely
rejected NVIDIA paths because it did not resolve explicit Allow rules against
Disallow: /. The monitor now uses Protego's RFC 9309 matching and the actual
official portals apply.careers.microsoft.com/careers and jobs.nvidia.com/careers,
which explicitly allow /careers paths. Private routes remain forbidden.
No restriction or challenge was bypassed. A regression test covers precedence.

Initial generic Amazon and Greenhouse extraction failed. The Amazon DOM
adapter and documented Greenhouse Job Board API repaired those cases and
passed subsequent live tests. Result-card selectors exclude similar-job
recommendations from pagination counts.

## Remaining verification

A separate bounded two-page test exercises the actual keyword input,
initialized US location and Next page/jobs buttons on the mandatory portals.
Its result is recorded below when complete. Full pagination of all available
jobs and broad keyword/category coverage have NOT been demonstrated.

No Telegram messages have been sent. Remote Actions verification is pending.
Schedules are intentionally gated by MONITOR_ENABLED=true until setup is
finished. This is a development build with verified live extraction, not a
claim that the complete requested monitoring service is operational.

Local diagnostics contain public page HTML and scan reports; these are ignored
by git. No credentials or personal applications were captured.
