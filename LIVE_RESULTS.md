# Verification — October 12, 2026 (America/New_York)

Local Python 3.13.7, Playwright 1.63.0, actual downloaded Chromium.
Dependencies and Chromium installed successfully. 14 automated fixture/mock
tests pass; these do not prove live integration coverage.

Actual browser probe opened the Amazon US search UI and both real Greenhouse
employer pages. A bounded concurrent browser scan then exposed extraction
failures in the generic adapter. Greenhouse was replaced with its documented
public Job Board API, used after a real browser visit to each employer board.
A subsequent full live Greenhouse scan verified:

| Board | Source total | Validated full descriptions | Status |
|---|---:|---:|---|
| Cloudflare | 434 | 434 | Verified Complete |
| Databricks | 896 | 896 | Verified Complete |

Both launched together, with independent browsers and recovery. No Telegram
messages were sent. Matching/eligibility rules remain heuristic and require
review. Full source collection does not imply every accepted classification
is correct.

Microsoft stopped before navigation: careers.microsoft.com/robots.txt
returned an HTML error page, so access policy could not be verified.
NVIDIA stopped before navigation: its landing page was disallowed by robots.
Neither restriction was bypassed. These are **non-working mandatory sources**
until a permitted path or explicit access policy can be established.

Amazon's search UI rendered in the browser probe, including United States
filters and official job links. The first bounded adapter run did not find
links. Stronger explicit waits were added; retest result will be recorded
below. Full pagination and complete Amazon description collection remain
unverified. Microsoft/NVIDIA search, pagination and details are unverified.

Initial API/GUI extraction failures are retained in local diagnostics, which
are excluded from source control. A bounded scan uses deliberate limits and
cannot be called complete. No screenshots or credentials were captured.

Remote Actions and Telegram delivery are pending verification. No claim of
full end-to-end operation is made. The overall requested goal remains
incomplete while mandatory sources, broad search coverage and Telegram are
not verified.
