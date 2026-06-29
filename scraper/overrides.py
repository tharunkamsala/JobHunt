"""Curated company → (ats, handle) overrides.

The auto-sniffer can't reliably detect the ATS for most companies that
put a vanity careers site in front of their real ATS (Greenhouse, Lever,
Ashby, SmartRecruiters, Workday, Eightfold).

This map was populated by directly probing each ATS API with the most
likely slugs for every company in ``data/companies.json``. Adding a new
company is as simple as probing the same way.

Each entry maps the *normalized* company name
(``re.sub(r"[^a-z0-9]+", "", name.lower())``) to a tuple of
``(ats_name, handle)``.

Supported ``ats_name`` values are the same modules used by the scraper:
``greenhouse``, ``lever``, ``ashby``, ``smartrecruiters``, ``workday``,
``eightfold``, ``oraclehcm``, ``talentbrew``, ``workable``, ``icims``,
``jobvite``, ``successfactors``.
"""
from __future__ import annotations

import re


OVERRIDES: dict[str, tuple[str, str]] = {
    # ---------- Greenhouse ----------
    "affirm":                ("greenhouse", "affirm"),
    "airbnb":                ("greenhouse", "airbnb"),
    "airtable":              ("greenhouse", "airtable"),
    "anduril":               ("greenhouse", "andurilindustries"),
    "anthropic":             ("greenhouse", "anthropic"),
    "blocksquarecashapp":    ("greenhouse", "block"),
    "brex":                  ("greenhouse", "brex"),
    "chime":                 ("greenhouse", "chime"),
    "cloudflare":            ("greenhouse", "cloudflare"),
    "coinbase":              ("greenhouse", "coinbase"),
    "databricks":            ("greenhouse", "databricks"),
    "datadog":               ("greenhouse", "datadog"),
    "discord":               ("greenhouse", "discord"),
    "dropbox":               ("greenhouse", "dropbox"),
    "elastic":               ("greenhouse", "elastic"),
    "figma":                 ("greenhouse", "figma"),
    "gitlab":                ("greenhouse", "gitlab"),
    "grafanalabs":           ("greenhouse", "grafanalabs"),
    "instacart":             ("greenhouse", "instacart"),
    "linkedin":              ("greenhouse", "linkedin"),
    "lyft":                  ("greenhouse", "lyft"),
    "mongodb":               ("greenhouse", "mongodb"),
    "nuro":                  ("greenhouse", "nuro"),
    "pinterest":             ("greenhouse", "pinterest"),
    "reddit":                ("greenhouse", "reddit"),
    "robinhood":             ("greenhouse", "robinhood"),
    "roblox":                ("greenhouse", "roblox"),
    "scaleai":               ("greenhouse", "scaleai"),
    "stripe":                ("greenhouse", "stripe"),
    "twilio":                ("greenhouse", "twilio"),
    "vercel":                ("greenhouse", "vercel"),
    "waymo":                 ("greenhouse", "waymo"),
    "wiz":                   ("greenhouse", "wizinc"),

    # ---------- Lever ----------
    "capitalone":            ("talentbrew", "https://www.capitalonecareers.com/search-jobs"),
    "mistralai":             ("lever", "mistral"),
    "plaid":                 ("lever", "plaid"),
    "shieldai":              ("lever", "shieldai"),
    "spotify":               ("lever", "spotify"),

    # ---------- Ashby ----------
    "cohere":                ("ashby", "cohere"),
    "confluent":             ("ashby", "confluent"),
    "notion":                ("ashby", "notion"),
    "openai":                ("ashby", "openai"),
    "perplexityai":          ("ashby", "perplexity"),
    "ramp":                  ("ashby", "ramp"),
    "snowflake":             ("ashby", "snowflake"),
    "supabase":              ("ashby", "supabase"),
    "zapier":                ("ashby", "zapier"),

    # ---------- SmartRecruiters ----------
    "canva":                 ("smartrecruiters", "canva"),
    "servicenow":            ("smartrecruiters", "servicenow"),
    # Uber migrated from SmartRecruiters to Phenom People (jobs.uber.com) — JS-rendered,
    # no public REST API. Removed override so it falls through to the generic sniffer.
    "visainc":               ("smartrecruiters", "visa"),

    # ---------- Workday (enterprise) ----------
    # URL must start from the job search site (myworkdayjobs.com/<lang>/<site>).
    "crowdstrike":           ("workday", "https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers"),
    "mastercard":            ("workday", "https://mastercard.wd1.myworkdayjobs.com/en-US/CorporateCareers"),
    "paloaltonetworks":      ("talentbrew", "https://jobs.paloaltonetworks.com/en/search-jobs"),
    "samsungusrd":           ("workday", "https://sec.wd3.myworkdayjobs.com/en-US/Samsung_Careers"),
    "tempusai":              ("workday", "https://tempus.wd5.myworkdayjobs.com/en-US/Tempus_Careers"),
    "workday":               ("workday", "https://workday.wd5.myworkdayjobs.com/en-US/Workday"),
    "vmwarebroadcom":        ("workday", "https://broadcom.wd1.myworkdayjobs.com/en-US/External_Career"),
    "salesforce":            ("workday", "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site"),
    "jpmorganchase":         ("oraclehcm", "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/"),
    "mckinseycompany":       ("workday", "https://mckinsey.wd5.myworkdayjobs.com/en-US/Experienced_Hires"),
    "nvidia":                ("workday", "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"),
    "oracle":                ("oraclehcm", "https://careers.oracle.com/en/sites/jobsearch/jobs?location=United%20States&locationId=300000000149325"),
    "intuit":                ("talentbrew", "https://jobs.intuit.com/search-jobs"),
    "adobe":                 ("workday", "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced"),

    # ---------- Eightfold ----------
    "netflix":               ("eightfold", "netflix"),
    # American Express & PayPal host with Eightfold but reject unauth API
    # calls (aexp returns positions=[], paypal returns 403). Both use
    # playwright workers as fallback.

    # ---------- Workday (additional confirmed URLs) ----------
    "intel":                 ("workday", "https://intel.wd1.myworkdayjobs.com/en-US/External"),

    # ---------- Workable ----------
    "huggingface":           ("workable", "huggingface"),

    # ---------- Playwright (JS-heavy / blocked / custom sites) ----------
    "cisco":                 ("playwright", "cisco"),
    "ciscosystems":          ("playwright", "cisco"),
    "github":                ("playwright", "github"),
    "twitterx":              ("playwright", "twitterx"),
    "doordash":              ("playwright", "doordash"),
    "snapinc":               ("playwright", "snap"),
    "atlassian":             ("playwright", "atlassian"),
    "rippling":              ("playwright", "rippling"),
    "miro":                  ("playwright", "miro"),
    "retool":                ("playwright", "retool"),
    "snyk":                  ("playwright", "snyk"),
    "spacex":                ("playwright", "spacex"),
    "bloomberglp":           ("playwright", "bloomberg"),
    "goldmansachs":          ("playwright", "goldman"),
    "citadelcitadelsecurities": ("playwright", "citadel"),
    "twosigma":              ("playwright", "twosigma"),
    "deshaw":                ("playwright", "deshaw"),
    "morganstanley":         ("playwright", "morganstanley"),
    "paypal":                ("playwright", "paypal"),
    "americanexpress":       ("playwright", "amex"),
    "deloitte":              ("playwright", "deloitte"),
    "accenture":             ("playwright", "accenture"),
    "ibm":                   ("playwright", "ibm"),
    "qualcomm":              ("playwright", "qualcomm"),
    "hashicorpibm":          ("playwright", "hashicorp"),
}


def normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def lookup(company_name: str) -> tuple[str, str] | None:
    return OVERRIDES.get(normalize(company_name))
