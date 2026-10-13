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
Microsoft, NVIDIA and Amazon each passed: 10 result cards on page one and
10 different cards on page two, with United States visible in the location
input and the configured keyword submitted through the real search field.
Amazon required Escape/Tab to dismiss its search-edit overlay, then rejecting
optional cookies before clicking Next page. Full pagination of all available
jobs and broad keyword/category coverage have NOT been demonstrated.

No Telegram messages have been sent. The public repository was uploaded and
remote Actions run 38335537326 completed on standard Ubuntu, Python 3.12.15.
Dependencies, Chromium and all 18 tests passed. Each of the five sources
extracted two descriptions. Its configured two-detail limit produced expected
Incomplete statuses, so the overall workflow deliberately failed. Persistence
succeeded and created bot-state commit d0983e52c8ac24872c50d4c4d0237c4bd58e1244.
The remote run exposed an Amazon facet-count ambiguity; only dedicated
source total selectors are now accepted, leaving Amazon total unspecified.
The later four-page detail concurrency/pacing changes received local
regression tests; this precise revision has not yet had a remote full scan.
Schedules are intentionally gated by MONITOR_ENABLED=true until setup is
finished. This is a development build with verified live extraction, not a
claim that the complete requested monitoring service is operational.

Local diagnostics contain public page HTML and scan reports; these are ignored
by git. No credentials or personal applications were captured.

Final local regression after parallel-detail and pacing changes extracted two
validated jobs from every configured source in the same concurrent cycle.
Microsoft total was 790; NVIDIA total was 1146; Amazon total was correctly
unspecified. All results were intentionally Incomplete due to max_details=2.
All 18 tests passed again. Telegram setup helpers are available; delivery and
scheduled monitoring remain unverified/inactive pending setup.
