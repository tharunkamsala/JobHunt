"""Central configuration for the job tracker."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Pin Playwright's browser cache to the project so it survives across shells
# and machines that mount the workspace (avoids "Executable doesn't exist"
# errors when the per-process temp dir gets recycled). Importing config.py
# anywhere in the app forces this before any Playwright launch — we
# intentionally override any pre-existing value, because some sandboxed
# shells inject an ephemeral temp path that won't have the binaries.
_PW_BROWSERS = BASE_DIR / ".venv" / "playwright-browsers"
if _PW_BROWSERS.exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_PW_BROWSERS)

DB_PATH = DATA_DIR / "jobs.db"
DATABASE_URL = os.environ.get("DATABASE_URL")

COMPANIES_JSON = DATA_DIR / "companies.json"
EXTRA_COMPANIES_JSON = DATA_DIR / "extra_companies.json"
EXCEL_PATH = BASE_DIR.parent / "H1B_Visa_Sponsor_Companies_CS.xlsx"

# Companies to skip entirely (no scrape, hidden from UI company list).
EXCLUDED_COMPANIES = frozenset({"SpaceX"})

# How often (minutes) the scheduler re-scrapes every company's career page.
SCRAPE_INTERVAL_MIN = 15

# Fast watchlist refresh cadence for near-real-time checking of selected
# companies. Empty / disabled watchlists simply skip these runs.
FAST_SCRAPE_INTERVAL_MIN = 5
FAST_WATCHLIST_MAX_COMPANIES = 25

# Seed a sensible early-cycle watchlist if the user has not chosen one yet.
# These are large or historically early-opening employers for new-grad /
# internship CS roles. Users can still override this list from the UI.
DEFAULT_WATCHLIST_COMPANIES = (
    "Adobe",
    "Amazon",
    "Apple",
    "Capital One",
    "Goldman Sachs",
    "Google (Alphabet)",
    "JPMorgan Chase",
    "Meta (Facebook)",
    "Microsoft",
    "NVIDIA",
    "OpenAI",
    "Oracle",
    "Pinterest",
    "Roblox",
    "ServiceNow",
    "Snowflake",
    "Stripe",
    "Waymo",
)

INTERNSHIP_CATEGORIES = (
    "Summer Intern",
    "Fall Co-op / Intern",
    "Spring Intern",
)

# Full-sweep concurrency. We deliberately run sequentially (1 worker) because
# parallel sweeps were causing Playwright-based scrapers (Microsoft, Meta) to
# step on each other and hang the entire run. Reliability > speed: a sequential
# sweep takes ~15 min but actually finishes and returns jobs from every source.
SCRAPE_MAX_WORKERS = 1

# Only deactivate a job after it has been missed in multiple successful
# company scrapes. This avoids transient scraper/API failures hiding real jobs.
JOB_MISS_DEACTIVATE_THRESHOLD = 2

# Per-request timeout (seconds) and polite delay between requests to the same host.
# POLITE_DELAY_SEC is applied per-company (after each scrape), but each worker
# is on a different host, so a long delay here just slows wall-clock without
# any politeness benefit. 0.3s is a safe nudge that still spaces out bursts.
REQUEST_TIMEOUT = 20
POLITE_DELAY_SEC = 0.3

PLAYWRIGHT_ENABLED = True
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT_MS = 30_000
PLAYWRIGHT_WAIT_UNTIL = "domcontentloaded"
PLAYWRIGHT_ESCALATE_ON_BLOCK = False
PLAYWRIGHT_USE_STEALTH = False
PLAYWRIGHT_USE_PROXY = False
PLAYWRIGHT_PROXY_URL = os.getenv("JOB_SCRAPER_PROXY_URL", "").strip() or None

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Keep internships and co-ops broadly, but also allow non-internship H1B roles
# that match the configured early-career / CS categories.
INTERNSHIP_ONLY_MODE = False

# Graduation cohort filter (UI + API). May 2027 is the primary student audience.
DEFAULT_GRAD_COHORT_YEAR = 2027
SUPPORTED_GRAD_COHORT_YEARS = (2026, 2027, 2028, 2029)

INTERNSHIP_TITLE_PATTERNS = [
    r"\bintern(ship)?s?\b",
    r"\bco[-\s]?op\b",
    r"\bcoop\b",
    r"\buniversity\s+intern\b",
    r"\bstudent\s+(intern|program|worker|trainee|associate|assistant)\b",
    r"\bstudent\s+software\b",
    r"\bapprentice(ship)?\b",
    r"\bsummer\s+associate\b",
    r"\bsummer\s+analyst\b",
    r"\bworking\s+student\b",
]

CS_DOMAIN_PATTERNS = [
    r"\bsoftware\b",
    r"\b(sde|swe)\b",
    r"\bdeveloper\b",
    r"\bprogrammer\b",
    r"\bcomputer\s+science\b",
    r"\bcomputational\b",
    r"\bbackend\b",
    r"\bfrontend\b",
    r"\bfront[-\s]?end\b",
    r"\bback[-\s]?end\b",
    r"\bfull\s*stack\b",
    r"\bplatform\b",
    r"\bdev[\s-]?ops\b",
    r"\binfrastructure\b",
    r"\bcloud\b",
    r"\bdatabase\b",
    r"\bdata\s+(engineer|scientist|analyst|architect|platform|infrastructure|developer)\b",
    r"machine\s+learning",
    r"\b(?:ai|ml)\s+intern\b",
    r"\bintern\b.{0,50}\b(?:ai|ml|machine\s+learning)\b",
    r"\bsecurity\b",
    r"\bcyber(security)?\b",
    r"\bsite\s+reliability\b",
    r"\bsre\b",
    r"\bqa\b",
    r"\btest\s+automation\b",
    r"\bsoftware\s+(engineer|developer|architect|intern)\b",
    r"\bcomputer\s+(engineer|scientist|engineering)\b",
    r"\b(?:machine\s+learning|ml|ai)\s+(engineer|scientist|intern|researcher|platform)\b",
    r"\b(?:cloud|platform|security|network|infrastructure|devops|sre)\s+(engineer|architect|developer|intern)\b",
    r"\b(?:site\s+reliability|software\s+development)\s+engineer\b",
    r"\b(?:embedded|firmware|systems?\s+software|software\s+systems)\s+engineer\b",
    r"\bresearch\s+(engineer|scientist)\b",
    r"\bapplied\s+scientist\b",
    # Hardware / systems / silicon (NVIDIA, Intel, AMD, Apple, Qualcomm, etc.)
    r"\balgorithms?\b",
    r"\bfpga\b",
    r"\basic\b",
    r"\bsoc\b",
    r"\bvlsi\b",
    r"\bverification\b",
    r"\bvalidation\b",
    r"\bfirmware\b",
    r"\bembedded\b",
    r"\bgpu\b",
    r"\bcompiler\b",
    r"\brobotics\b",
    r"\bperception\b",
    r"\bcomputer\s+vision\b",
    r"\bsignal\s+processing\b",
    r"\bnetworking\b",
    r"\b(it|tech)\s+(intern|associate|analyst)\b",
    r"\binformation\s+technology\b",
    r"\btechnology\s+(analyst|development\s+program)\b",
    r"\btechnology\s+engineer\b",
    r"\bapplication\s+developer\b",
    r"\bcloud\s+developer\b",
    r"\bweb\s+developer\b",
    r"\bsystems?\s+engineer\b",
    r"\bnetwork\s+engineer\b",
    r"\bplatform\s+engineer\b",
    r"\bmobile\s+(developer|engineer)\b",
    r"\bios\s+engineer\b",
    r"\bandroid\s+(developer|engineer)\b",
]

SEASONAL_TECH_INTERNSHIP_PATTERNS = [
    # Do not use bare "engineer" / "engineering" — that admits mechanical, electrical, etc.
    r"\b(software|sde|swe|developer|programmer|computer\s+science|computational)\b",
    r"\b(technology|tech|data|database|machine\s+learning|artificial\s+intelligence)\b",
    r"\b(?:ai|ml)\s+(engineer|scientist|intern|researcher|platform)\b",
    r"\b(platform|cloud|security|cyber|infrastructure|devops|sre|networking)\b",
    r"\b(systems?\s+software|software\s+systems|embedded|firmware|computer\s+engineering)\b",
    r"\b(research|scientist|applied\s+scientist|robotics|perception|visualization|analytics)\b",
]

# Non-engineering roles that sometimes match our keywords (e.g. "Account
# Executive - Observability", "Recruiter, ML Platform"). A title that trips
# ANY of these is dropped before we even check role categories.
NON_ENGINEERING_EXCLUDES = [
    # "Exective" is a typo that appears in real postings (e.g. Snowflake).
    r"\baccount\s+(executive|exective|manager|director|representative)\b",
    r"\bsales(\s+(engineer|manager|director|representative))?\b",
    r"\bcustomer\s+success\b",
    r"\brecruit(er|ing)\b",
    r"\bmarketing\b",
    r"\b(business|partner)\s+development\b",
    r"\b(product|program|project)\s+manager\b",  # PM, TPM, etc.
    r"\bux\s+(designer|researcher)\b",
    r"\bgraphic\s+designer\b",
    r"\bcontent\s+(writer|strategist)\b",
    r"\btechnical\s+writer\b",
    r"\blegal\s+counsel\b",
    r"\bfinance\s+analyst\b",
    r"\b(solutions|sales)\s+engineer\b",  # pre-sales, not building
    r"\bgo[-\s]?to[-\s]?market\b",        # GTM / strategy-ops interns
    r"\b(community|communications|comms)\s+manager\b",
    r"\bbusiness\s+analyst\b",
    r"\boperations\s+analyst\b",
    r"\bstrategy\s+(analyst|consultant|associate)\b",
    r"\bmanagement\s+consultant\b",
    r"\bsupply\s+chain\b",
    r"\blogistics\b",
    r"\bwarehouse\b",
    r"\bhuman\s+resources\b",
    r"\bhr\s+(intern|analyst|coordinator|generalist|operations?|business\s+partner|bp)\b",
    r"\bhr\s+operations?\b",
    r"\bpeople\s+team\b",
    r"\bpeople\s+intern\b",
    r"\bpeople\s+(operations|partner|analyst|team)\b",
    r"\btalent\s+(acquisition|partner|growth)\b",
    r"\bbenefits\s+(analyst|coordinator|intern|specialist)\b",
    r"\bemployee\s+experience\b",
    r"\bworkplace\s+(operations|experience)\b",
    r"\borganizational\s+development\b",
    r"\blearning\s+(and\s+)?development\b",
    r"\bcompensation\s+(analyst|intern)\b",
    r"\brecruiting\s+intern\b",
    r"\baccounting\b",
    r"\bauditor\b",
    r"\btax\s+(analyst|associate|intern)\b",
    r"\bfinancial\s+(analyst|advisor|planner)\b",
    r"\binvestment\s+banking\b",
    r"\bclinical\b",
    r"\bnurs(e|ing)\b",
    r"\bpharmac(y|ist)\b",
    r"\bteacher\b",
    r"\bprofessor\b",
    r"\binstructor\b",
    r"\bparalegal\b",
    r"\battorney\b",
    r"\breal\s+estate\b",
    r"\binsurance\s+(agent|sales)\b",
    r"\bcustomer\s+support\b",
    r"\bcall\s+center\b",
    r"\badministrative\s+assistant\b",
    r"\boffice\s+manager\b",
    r"\bevent\s+(planner|coordinator)\b",
    r"\bgraphic\s+design\b",
    r"\bcopywriter\b",
    r"\bpublic\s+relations\b",
    r"\bbrand\s+(manager|marketing)\b",
]

# Non-CS engineering / science fields (mechanical, civil, etc.) — not CSE roles.
NON_CS_FIELD_EXCLUDES = [
    r"\bmechanical\b",
    r"\belectrical\b",
    r"\belectronics?\b",
    r"\bee\s+(intern|co[-\s]?op|engineer|student|analyst)\b",
    r"\bpower\s+systems?\b",
    r"\brf\s+engineer",
    r"\banalog\s+(design|engineer)",
    r"\boptical\s+engineer",
    r"\bcivil\b",
    r"\bchemical\b",
    r"\bbiomedical\b",
    r"\bindustrial\s+engineer",
    r"\bindustrial\s+engineering\b",
    r"\bmanufacturing\b",
    r"\baerospace\b",
    r"\bautomotive\b",
    r"\bstructural\b",
    r"\bgeotechnical\b",
    r"\benvironmental\s+engineer",
    r"\bmaterials\s+science\b",
    r"\bpetroleum\b",
    r"\bmining\b",
    r"\bagricultural\b",
    r"\bfood\s+science\b",
    r"\bchemistry\b",
    r"\bphysics\b",
    r"\bconstruction\b",
    r"\bhvac\b",
    r"\bplumbing\b",
    r"\belectrician\b",
    r"\bwelding\b",
    r"\bcarpenter\b",
]

# Experience filter: reject titles that clearly imply >3 years of experience.
# A job is only kept if it matches a category AND does NOT match any of these.
SENIORITY_EXCLUDES = [
    # Senior/lead/staff/principal/fellow/etc.
    r"\b(senior|sr\.?)\b",
    r"\b(staff|principal|lead|leader|distinguished|fellow|expert)\b",
    # Management / executive
    r"\b(manager|director|head\s+of|vp|vice\s+president|chief|cto|ceo|cio|founding)\b",
    r"\btechnical\s+leadership\b",
    # Architect-level titles (almost always senior).
    r"\b(architect|solutions\s+architect)\b",
    # Roman-numeral seniority: III, IV, V, VI, VII (avoid matching II).
    r"\b(iii|iv|vi|vii|viii|ix)\b",
    r"[-\s,]\s*(iii|iv|v|vi|vii|viii|ix)\s*$",
    r"\b(engineer|scientist|developer|researcher|programmer|analyst)\s+(iii|iv|v|vi|vii|viii|ix|3|4|5|6|7|8)\b",
    # Internal level codes: L5+ / E5+ / P5+ / SDE-3+.
    r"\bl(5|6|7|8|9|10|11|12)\b",
    r"\be(5|6|7|8|9)\b",
    r"\bp(5|6|7|8|9)\b",
    r"\bsde\s*[-\s]?\s*(3|4|5|iii|iv|v)\b",
    r"\bswe\s*[-\s]?\s*(3|4|5|iii|iv|v)\b",
    r"\blevel\s*[5-9]\b",
    # Year requirements embedded in the title (rare but appears).
    r"\b([4-9]|1[0-9])\s*\+?\s*(years|yrs)\b",
    r"\b([4-9]|1[0-9])\s*\+\s*(years|yrs)\s+of\s+experience\b",
    # Tenure / grade keywords.
    r"\b(experienced|seasoned|tenured)\b",
]

# Role filter definitions. Each category has a list of regex patterns (case-insensitive).
# A job title is considered matching a category if ANY pattern matches.
ROLE_FILTERS = {
    "Summer Intern": [
        r"summer.{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}summer\b",
        r"(software|technology|tech|data|ml|machine\s+learning|ai|platform|cloud|security|cyber).{0,80}summer\s+analyst\b",
        r"summer\s+analyst.{0,80}(software|technology|tech|data|ml|machine\s+learning|ai|platform|cloud|security|cyber)\b",
    ],
    "SDE 1": [
        r"\bsde\b",
        r"\bswe\b",
        r"\bsde\s*[i1]\b",
        r"\bsde\s*-?\s*1\b",
        r"software\s+(development\s+)?engineer\s+(i|1|l3)\b",
        r"software\s+(development\s+)?engineer\b",
        r"software\s+developer\b",
        r"\bapplication\s+developer\b",
        r"\bcloud\s+developer\b",
        r"\bweb\s+developer\b",
        r"\bmobile\s+(developer|engineer)\b",
        r"\bios\s+engineer\b",
        r"\bandroid\s+(developer|engineer)\b",
        r"\b(backend|frontend|front[-\s]?end|back[-\s]?end|full[\s-]?stack)\s+(engineer|developer)\b",
        r"\bswe\s*[i1]\b",
        r"software\s+engineer\s+i\b",
        r"\blevel\s*3\s+engineer\b",
        r"\bsdet\b",
        r"\bsoftware\s+test\s+engineer\b",
        r"\btest\s+automation\s+engineer\b",
        r"\bautomation\s+engineer\b",
        r"\bintegration\s+engineer\b",
        r"\bmember\s+of\s+technical\s+staff\b",
        r"\bmts\b",
    ],
    "SDE 2": [
        r"\bsde\s*ii\b",
        r"\bsde\s*-?\s*2\b",
        r"software\s+(development\s+)?engineer\s+(ii|2|l4)\b",
        r"\bswe\s*ii\b",
        r"software\s+engineer\s+ii\b",
        r"\blevel\s*4\s+engineer\b",
    ],
    "New Grad": [
        r"new\s*grad",
        r"new\s*graduate",
        r"university\s*grad",
        r"university\s+graduate",
        r"university\s+hire",
        r"college\s+(grad(uate)?|hire)",
        r"early\s*career",
        r"early\s+careers",
        r"emerging\s+talent",
        r"entry[-\s]*level",
        r"\bgraduate\s+(software|engineer|program|developer|rotation)",
        r"\bgraduate\s+software\s+engineer\b",
        r"\bgraduate\s+engineer\b",
        r"class\s+of\s+20(25|26|27|28|29)",
        r"\b20(26|27|28|29)\s+new\s*grad",
        r"\bnew\s*grad\w*\s*['\-]?\s*20(26|27|28|29)\b",
        r"\b20(26|27|28|29)\s+graduate",
        r"\bgraduate\s+['\-]?\s*20(26|27|28|29)\b",
        r"\bmay\s*['\-]?\s*20(26|27|28|29)\b",
        r"\bspring\s*['\-]?\s*20(26|27|28|29)\s+grad",
        r"\bstart\s+(date\s+)?['\-]?(january|february|march|april|may|june|july|august|september|fall|summer)\s*['\-]?\s*20(26|27|28|29)\b",
        r"\b(january|june|july|august|september|fall|summer)\s*['\-]?\s*20(26|27|28|29)\s+start\b",
        r"\bcampus\s+(hire|recruit|recruiting|recruitment)\b",
        r"\buniversity\s+recruit",
        r"\brecent\s+graduate\b",
        r"\b0\s*[-–]?\s*1\s+years?\b",
        r"\b0\s+years?\s+(of\s+)?experience\b",
        r"\bfte\s+university\b",
        r"\bfull[-\s]?time\s+university\b",
        r"\buniversity\s+programs?\b",
        r"\bengineering\s+university\b",
        r"\b(university|campus)\s+software\b",
        r"\b(software|swe|sde|ml|data|cloud|platform|security)\s+engineer.{0,35}\b(2027|'27|2028|'28)\b",
        r"\b(2027|'27|2028|'28).{0,35}\b(software|swe|sde|engineer|developer)\b",
        r"\b(ignite|accelerate|propel|emerging|futureforce|ascend)\s+program\b",
        r"\bdevelopment\s+program\b",
        r"\buniversity\s+relations\b",
        r"\bcollege\s+relations\b",
        r"campus\s+hire",
        r"intern.*full[-\s]*time\s+conversion",
        r"\bassociate,?\s+(software|ml|machine|data|cloud|security|research)\s+engineer",
        r"\bassociate\s+(software|ml|machine|data|cloud|security|research)\s+engineer",
        r"\bjunior\s+(software|ml|machine|data|cloud|security|engineer|developer)\b",
        r"\b(graduate|grad)\s+(engineer|developer|program)",
        r"rotational\s+(engineer|program|development)",
        r"\bsoftware\s+engineer\s+program\b",
        r"\btechnology\s+analyst\b",
        r"\bnew\s+analyst\b.{0,40}(software|technology|engineering|data|platform|cloud|security|ml|ai)\b",
        r"(software|technology|engineering|data|platform|cloud|security|ml|ai).{0,40}\bnew\s+analyst\b",
        r"\btechnology\s+development\s+program\b",
        r"\binnovation\s+development\b",
        r"\bsoftware\s+engineer.{0,25}(new\s*grad|new\s*graduate|university|graduate|early\s*career)\b",
        r"\b(engineer|developer).{0,25}(new\s*grad|new\s*graduate|university|graduate|early\s*career)\b",
        # "University Software Engineer" / "University ML Engineer" — Uber, Google, etc.
        r"\buniversity\s+(software|ml|ai|data|cloud|platform|backend|frontend|full[\s-]?stack)\s+(engineer|developer)\b",
        # "University SWE" / "University SDE" — abbreviations already imply engineer
        r"\buniversity\s+(sde|swe)\b",
    ],
    "AI / ML": [
        r"\bml\s+engineer",
        r"\bml\b.{0,15}\bengineer",  # ML Framework Engineer, ML Platform Engineer, etc.
        r"machine\s+learning",
        r"\bai\s+engineer",
        r"applied\s+scientist",
        r"research\s+scientist",
        r"\bresearch\s+engineer",    # Research Engineer (OpenAI, Anthropic, DeepMind, etc.)
        r"\bdistributed\s+training\s+engineer",
        r"deep\s+learning",
        r"computer\s+vision",
        r"\bnlp\b",
        r"\bllm\b",
        r"generative\s+ai",
        r"ml\s+ops|mlops",
        r"\bai\s*/\s*ml\b",
        r"artificial\s+intelligence",
    ],
    "Database": [
        r"database\s+engineer",
        r"\bdba\b",
        r"database\s+administrator",
        r"data\s+engineer",
        r"data\s+infrastructure",
        r"data\s+platform",
        r"storage\s+engineer",
        r"\bsql\s+engineer",
        r"database\s+developer",
        r"\bdb\s+engineer",
    ],
    "Infrastructure / DevOps": [
        r"\bdev[\s-]?ops\b",
        r"\bsre\b",
        r"site\s+reliability",
        r"reliability\s+engineer",
        r"platform\s+engineer(ing)?",
        r"infrastructure\s+engineer",
        r"\binfra\s+engineer",
        r"cloud\s+engineer",
        r"\bcloud\s+developer\b",
        r"cloud\s+infrastructure",
        r"systems?\s+engineer",
        r"\bkubernetes\b",
        r"\bk8s\b",
        r"observability",
        r"build\s+(&|and)\s+release",
        r"release\s+engineer",
        r"network\s+engineer",
        r"production\s+engineer",
        r"\bci\s*/\s*cd\b",
    ],
    # Seasonal internship buckets (kept ahead of role buckets in priority).
    # We accept either explicit year markers (2026/2027, '26/'27) or clear
    # seasonal intern/co-op phrasing to avoid missing real student roles.
    "Fall Co-op / Intern": [
        r"\bfall\s*['\-]?\s*20(26|27|28)\b",
        r"\b20(26|27|28)\s*fall\b",
        r"\bfall\s*['\-]?\s*(26|27|28)\b",
        r"\b(26|27|28)\s*fall\b",
        r"\bautumn\s*['\-]?\s*20(26|27|28)\b",
        r"\bautumn\s*['\-]?\s*(26|27|28)\b",
        r"fall.{0,40}20(26|27|28).{0,50}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,50}fall.{0,40}20(26|27|28)",
        r"fall.{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}fall\b",
        r"autumn.{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}autumn\b",
    ],
    "Spring Intern": [
        r"\bspring\s*['\-]?\s*20(26|27|28)\b",
        r"\bwinter\s*['\-]?\s*20(26|27|28)\b",
        r"\bspring\s*['\-]?\s*(26|27|28)\b",
        r"\bwinter\s*['\-]?\s*(26|27|28)\b",
        r"spring.{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}spring\b",
        r"winter.{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}winter\b",
        r"(january|jan)\s*['\-]?\s*20(26|27|28).{0,60}(co[-\s]?op|intern(ship)?|analyst\s+program)\b",
        r"(co[-\s]?op|intern(ship)?|analyst\s+program).{0,60}(january|jan)\s*['\-]?\s*20(26|27|28)\b",
    ],
}
