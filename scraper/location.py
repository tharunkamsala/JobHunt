"""Decide whether a job's location string is in the USA.

Rules (applied in order):
  1. If the string contains any non-US country/city keyword, reject.
  2. If it contains a US keyword (state abbrev, US city, 'United States',
     'USA', 'Remote - US', etc.), accept.
  3. Pure "Remote" with no country is accepted (many US companies default
     to US-only remote); Set STRICT_REMOTE = True to reject unqualified remote.
  4. Empty / unknown location is rejected (we want a guaranteed US role).
"""
from __future__ import annotations

import re

# If True, reject locations that only say "Remote" with no country hint.
STRICT_REMOTE = False

# Two-letter US state / territory codes.
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC","PR",
}

US_STATE_NAMES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
    "south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    "district of columbia","puerto rico",
}

# Common US cities that appear in postings without a state.
US_CITIES = {
    "new york","nyc","san francisco","sf","palo alto","mountain view","sunnyvale",
    "san jose","cupertino","redwood city","menlo park","oakland","berkeley",
    "los angeles","la","santa monica","san diego","irvine","pasadena",
    "seattle","bellevue","redmond","kirkland",
    "austin","dallas","houston","san antonio","plano",
    "chicago","boston","cambridge","atlanta","denver","boulder","portland",
    "pittsburgh","philadelphia","washington dc","arlington","bethesda",
    "miami","orlando","tampa","raleigh","durham","charlotte","nashville",
    "phoenix","tempe","salt lake city","lehi","detroit","minneapolis",
    "columbus","cincinnati","indianapolis","kansas city","st louis","saint louis",
    "las vegas","reno","honolulu","anchorage",
}

US_KEYWORDS = {
    "united states","united states of america","usa","u.s.a","u.s.","us-remote",
    "us remote","remote - us","remote, us","remote (us)","remote us","americas - us",
    "north america - us",
}

# Anything that explicitly marks the job as non-US.
NON_US_COUNTRIES = {
    "canada","toronto","vancouver","montreal","ottawa","calgary","edmonton",
    "mexico","mexico city","guadalajara","brazil","sao paulo","são paulo","rio",
    "argentina","buenos aires","chile","santiago","colombia","bogota",
    "united kingdom","uk","england","scotland","london","manchester","cambridge uk",
    "ireland","dublin",
    "germany","berlin","munich","frankfurt","hamburg",
    "france","paris","lyon","toulouse",
    "spain","madrid","barcelona",
    "portugal","lisbon","porto",
    "italy","rome","milan",
    "netherlands","amsterdam","the hague",
    "belgium","brussels",
    "switzerland","zurich","geneva","lausanne",
    "austria","vienna",
    "sweden","stockholm","gothenburg",
    "norway","oslo",
    "denmark","copenhagen",
    "finland","helsinki",
    "poland","warsaw","krakow","kraków",
    "czech republic","prague",
    "romania","bucharest",
    "greece","athens",
    "turkey","istanbul",
    "russia","moscow","saint petersburg","st petersburg",
    "ukraine","kyiv","kiev",
    "israel","tel aviv","herzliya","jerusalem",
    "uae","united arab emirates","dubai","abu dhabi",
    "saudi arabia","riyadh",
    "egypt","cairo",
    "south africa","johannesburg","cape town",
    "india","bangalore","bengaluru","hyderabad","mumbai","pune","delhi","gurgaon",
    "gurugram","noida","chennai","kolkata",
    "pakistan","lahore","karachi","islamabad",
    "china","beijing","shanghai","shenzhen","hangzhou","guangzhou",
    "hong kong","taiwan","taipei",
    "japan","tokyo","osaka","kyoto",
    "south korea","korea","seoul",
    "singapore","malaysia","kuala lumpur","indonesia","jakarta",
    "thailand","bangkok","vietnam","hanoi","ho chi minh",
    "philippines","manila",
    "australia","sydney","melbourne","brisbane","perth",
    "new zealand","auckland","wellington",
    "emea","apac","latam","eu only","europe only",
}

_WORD = re.compile(r"[a-z]+|[A-Z]{2,}")


def _tokens(s: str) -> list[str]:
    return [t.group(0) for t in _WORD.finditer(s)]


def _has_state_abbrev(s: str) -> bool:
    # Look for a standalone uppercase state code, e.g. ", CA" or " NY " or "TX)".
    return bool(re.search(r"(?:^|[,\s(\-])(" + "|".join(US_STATES) + r")(?:$|[,\s)\-])", s))


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def _any_phrase(low: str, phrases) -> bool:
    """Whole-word/phrase match: 'la' won't match 'england', 'ny' won't match 'any'."""
    for p in phrases:
        if re.search(r"(?<![a-z])" + re.escape(p) + r"(?![a-z])", low):
            return True
    return False


def is_usa(location: str | None) -> bool:
    """Return True if the location string is (plausibly) in the United States."""
    if not location:
        return False
    raw = location.strip()
    low = _norm(raw)

    # Workday/Greenhouse multi-location placeholders ("2 Locations",
    # "Multiple Locations", "Various", ...). These postings almost always
    # include at least one US office; rejecting them entirely throws away
    # huge numbers of real US intern roles (NVIDIA, Apple, Amazon, ...).
    if re.fullmatch(r"\d+\s+locations?", low):
        return True
    if low in {
        "multiple locations",
        "various locations",
        "various",
        "varies",
        "multiple us locations",
        "multiple cities",
        "multiple offices",
        # Greenhouse companies that post US-only roles sometimes use these
        # vague strings when offices[] wasn't resolved to a real city.
        # We treat them as "unknown but possibly US" — the greenhouse.py
        # scraper now tries to resolve offices[] first, so these should
        # only appear when the company has no office metadata at all.
        # Accept rather than silently drop those roles.
        "in-office",
        "in office",
        "on-site",
        "onsite",
        "on site",
        "hybrid",
        "hybrid remote",
        "on-site/remote",
        "on-site / remote",
        "flexible",
    }:
        return True

    # Workday-style country-prefixed format: "US-CA-San Francisco",
    # "DE-Munich-MSO", "IN-Bangalore", "GB-London". If it starts with a
    # two-letter country code followed by "-", use that code as ground truth.
    m = re.match(r"^([A-Za-z]{2})-[A-Za-z]", raw)
    if m:
        cc = m.group(1).upper()
        if cc == "US":
            return True
        # Known non-US country codes used by Workday.
        non_us_cc = {
            "DE","FR","GB","UK","IT","ES","NL","BE","CH","SE","NO","DK","FI",
            "PL","CZ","IE","AT","PT","GR","RO","HU","BG","HR","SK","SI","EE",
            "LV","LT","RS","TR","RU","UA","IL","AE","SA","EG","ZA",
            "CA","MX","BR","AR","CL","CO","PE","VE","UY",
            "IN","PK","BD","LK","CN","HK","TW","JP","KR","SG","MY","ID","TH",
            "VN","PH","AU","NZ",
        }
        if cc in non_us_cc:
            return False
        # Unknown two-letter prefix: fall through to normal checks.

    # Canadian province codes at end-of-field (e.g. "Toronto, ON, CA" or
    # "Vancouver, BC"). These strings often also contain "CA" which would
    # otherwise be mis-read as California. Reject outright.
    if re.search(r",\s*(on|qc|bc|ab|mb|sk|ns|nb|nl|pe|yt|nt|nu)\s*(,\s*ca)?\s*$", low):
        return False
    # Explicit ", CA" at end preceded by a Canadian city is also Canada.
    if re.search(r"\b(toronto|vancouver|montreal|montréal|ottawa|calgary|edmonton|waterloo|kitchener|mississauga|winnipeg|quebec|québec)\b.*\bca\b\s*$", low):
        return False

    if _any_phrase(low, NON_US_COUNTRIES):
        # Mixed string like "New York, US; London, UK" still counts as US because
        # the candidate can work from NY. But if the string ONLY mentions non-US,
        # reject. Heuristic: require that we ALSO find a US marker — but
        # exclude the ambiguous "CA" token when a Canadian city is present.
        raw_for_abbrev = raw
        if re.search(r"\b(toronto|vancouver|montreal|ottawa|calgary|edmonton|waterloo|ontario|quebec|british\s+columbia|alberta|manitoba)\b", low):
            # Strip trailing ", CA" so _has_state_abbrev doesn't match it.
            raw_for_abbrev = re.sub(r",\s*CA\s*$", "", raw_for_abbrev, flags=re.I)
        us_hit = (
            _has_state_abbrev(raw_for_abbrev)
            or _any_phrase(low, US_KEYWORDS)
            or _any_phrase(low, US_STATE_NAMES)
            or _any_phrase(low, US_CITIES)
        )
        if not us_hit:
            return False

    if _any_phrase(low, US_KEYWORDS):
        return True
    if _has_state_abbrev(raw):
        return True
    if _any_phrase(low, US_STATE_NAMES):
        return True
    if _any_phrase(low, US_CITIES):
        return True

    # Generic "remote" handling.
    if "remote" in low:
        if STRICT_REMOTE:
            return False
        # Reject if remote is explicitly scoped to non-US.
        if re.search(r"remote.*(emea|apac|eu|europe|india|canada|latam|uk|global)", low):
            return False
        if re.search(r"(emea|apac|eu|europe|india|canada|latam|uk).*remote", low):
            return False
        # "Remote" alone, or "Remote - United States": accept.
        return True

    return False



