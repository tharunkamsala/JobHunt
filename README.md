# New Grad Job Hunter

Python 3.12+ personal job monitor using Playwright Chromium, asyncio, HTTPX,
BeautifulSoup, JSON history, Telegram and GitHub Actions. **Development build:
mandatory sources have bounded live extraction tests; full pagination is not yet verified. Do not treat this as a
complete or deployed monitoring service.** See LIVE_RESULTS.md.

## Local use

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
python -m pytest -q
python main.py --dry-run
```

Run from this folder. `--company Amazon --max-pages 1 --max-details 2` is a
bounded live diagnostic, deliberately incomplete. Default scans start all
configured sources concurrently, using separate browser processes/contexts.
`--graduation-year 2027` sets optional graduation criteria; omit to disable.
`--alert-existing` enables baseline alerts. Default initial baseline is silent. The baseline covers jobs actually collected in the first live scan, even if that scan is incomplete; previously unseen jobs found on later recovery scans may alert regardless of their original posting date. Dry runs do not initialize the live baseline.
`--dry-run` never sends messages but DOES update local history; use a separate
`--state /tmp/hunter-test.json` for experiments.

## Deployment (requires account authorization)

1. Authenticate locally using `gh auth login -h github.com`. Never share tokens
   in chat. Choose/authorize a **public** repository and upload the contents of
   this folder as its root, excluding .venv, state, diagnostics and .env.
2. In Telegram, use the official @BotFather to create a bot. Start a private
   conversation with your bot. Obtain your chat ID using the official Bot API
   locally, keeping the bot token out of shell history and logs. Run `.venv/bin/python scripts/telegram_chat_id.py` for a hidden-token prompt after sending your bot a message.
3. In GitHub repository Settings → Secrets and variables → Actions, add
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository secrets. Do not
   place them in files or repository variables. Optional variables:
   `GRADUATION_YEAR` and `ALERT_EXISTING` (`true` to alert the baseline).
4. Ensure Actions is enabled and repository Actions can write contents. The
   workflow uses only contents:write to maintain the dedicated bot-state branch.
   Protect the main branch if desired; bot-state must permit workflow writes.
5. Actions → New Grad Job Hunter → Run workflow is the manual Run Now button.
   Inspect the logs and scan-diagnostics artifact. Confirm a real Telegram
   message and state/history.json on bot-state before relying on the system.
6. Resolve the source limitations below, configure Telegram, then set repository variable `MONITOR_ENABLED=true` to activate scheduled scans. Manual runs work before activation; use dry_run and max_details=2 for a bounded remote diagnostic.

Cron runs at UTC minutes 13 and 43. GitHub may delay/drop scheduled runs; this
is not an exact timer. Public schedules may be disabled after 60 days without
repository activity. Inspect Actions periodically. The MacBook is unnecessary
once remotely deployed. The repository and manual workflow are deployed; a bounded remote dry run verified installation, tests, extraction and bot-state persistence. Scheduled monitoring is not active and no Telegram message has been sent.

## Free usage and security

The workflow refuses private repositories and uses standard ubuntu-latest,
with a 28-minute timeout and serialized execution. No paid resources, paid AI,
paid broadcast options or paid runners are configured. Current GitHub policy:
https://docs.github.com/en/billing/concepts/product-billing/github-actions
Scheduling limitations:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
Telegram API: https://core.telegram.org/bots/api#sendmessage

Public bot-state contains only public job descriptions, timestamps and alert
status, never chat IDs or tokens. Logs suppress HTTPX request URLs because
Telegram embeds tokens in URLs. Diagnostic reports retain seven days; no
screenshots or personal application data are collected.

## Behavior and limits

- Configured official boards: Microsoft, Amazon, NVIDIA, Cloudflare Greenhouse,
  Databricks Greenhouse. Additional ATS integrations are deferred.
- Browser adapters navigate official landing/search pages using URL parameters.
  They validate the initialized US location input and execute the actual keyword input, but do not cover every requested keyword.
  Site-specific selectors and broad category coverage need live validation.
- Greenhouse uses its documented public Job Board API after opening the employer board: https://docs.greenhouse.io/job-board.html. Counts verify the entire configured board. Microsoft/NVIDIA accept JSON-LD JobPosting detail pages. Amazon uses its verified visible description and qualification sections. Portals without these validated fields
  fail extraction; no invented fields or silent HTML guesses.
- Pagination handles accessible Next/Load more controls with repeated-page
  detection and safety limits. Numeric-only/infinite-scroll pages need adapters.
- Missing totals, zero links, failed details and limits yield incomplete status.
  Count comparison alone does not prove all CS roles across the employer were
  searched. “Verified Complete” refers only to the configured query.
- Robots failures, disallow rules, HTML robots responses and access challenges
  stop the worker. No CAPTCHA bypass. A readable robots file is not permission
  under website terms; review each portal's terms before scheduled use.
- Retries use new browsers with exponential backoff. Recovery pending is stored;
  next scheduled run retries. No last-good scan is overwritten with empty jobs.
- US eligibility uses explicit country or US state abbreviations. Full state
  names without country and ambiguous remote regions are withheld for review.
  Rules cannot reliably interpret every qualification sentence, experience
  alternative, degree offset or graduation range. Inspect Needs Review matches.
- Descriptions provide experience and sponsorship evidence; silence stays
  unspecified. Preferred requirements are not automatically required.
- History is saved atomically locally and pushed to bot-state even after an
  incomplete scan. IDs deduplicate; content changes trigger update alerts.
  Content hashing is conservative and can flag formatting-only changes.
- Telegram uses plain text chunks under 3500 characters, with bounded retries.
  Delivery is at least once: a crash after send but before durable branch push
  can cause a duplicate. Exactly-once delivery cannot be guaranteed with the
  Telegram API and git commits. A timeout can likewise lose an acknowledgement.
- Failure warnings currently repeat each unsuccessful scan; notification
  failures leave jobs pending and mark the overall result incomplete.
- Long scans use up to four concurrent detail pages per source, paced by
  robots rules. Attempts have a 20-minute limit within a total 25-minute
  recovery budget per source, with at most three attempts. Broad careers inventories may exceed this and remain incomplete.

## Tests

`python -m pytest -q` tests rules, state reload/deduplication and updates,
structured detail parsing, retry recovery, notification formatting/missing
credentials and workflow structure. These use fixtures and mocks, not live
coverage. Live evidence is documented separately. Python 3.13 was used locally;
the workflow requests Python 3.12, which has not yet been remotely tested.

### Immediate Telegram delivery

Validated matching details now go to Telegram as each finishes, while other source workers continue. Messages share a rate limit (about one per second for the same chat). A full scan does not need to finish before alerts arrive. A manual run defaults to sending existing matching jobs too; successful delivery records prevent repeat alerts for unchanged postings. Previously silent baseline records are released when this option is enabled.

Live GitHub runs checkpoint delivery history to `bot-state` during the scan, with subsequent checkpoints about every 30 seconds, plus the final save. An abrupt failure between Telegram acknowledgement and a checkpoint can still cause a repeat after recovery.

The bot sends no email. GitHub Actions email delivery is an account preference: Settings → Notifications → System → Actions → Don't notify.

### Current role preferences

Microsoft, Amazon, and NVIDIA alerts are limited to software engineering / software development titles (including SDE and SWE). SDE II / Software Engineer II, higher numbered levels, senior roles, internships, and other job families are excluded. Unspecified-level software roles need clear entry-level evidence in the JD. Roles requiring more than two years are excluded; a minimum of zero, one, or two years may qualify. Missing experience and entry-level evidence are excluded.

Cloudflare and Databricks Greenhouse boards are also monitored for technical new-graduate roles explicitly accepting the 2027 graduating class. Missing graduation years, other graduating classes, internships, and level II or senior roles do not generate alerts. An unrelated 2027 date (for example copyright or a project date) does not establish graduation eligibility.

Across every source, postings explicitly requiring U.S. citizenship are excluded before Telegram delivery (for example, “U.S. citizens only” or “must be a U.S. citizen”). A generic U.S. work-authorization requirement, citizenship preference, explicitly optional citizenship, or a citizen/permanent-resident alternative does not by itself trigger this citizen-only exclusion.

The experience cutoff is at most two years of required experience across all sources. Explicit two-year minimums and “2+ years” can qualify because an applicant with exactly two years meets that minimum. Requirements above two years are excluded even when a title says new graduate. Preferred experience is distinguished from mandatory requirements. Ranges such as 0–2 years can qualify because applicants with zero, one, or two years are eligible.
