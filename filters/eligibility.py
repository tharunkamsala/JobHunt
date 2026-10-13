import re
from models import Job
STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
TECH = re.compile(r"software|developer|machine learning|data (?:engineer|scien)|cloud|devops|site reliability|platform engineer|infrastructure engineer|systems engineer|security engineer|firmware|embedded|test engineer|automation engineer|applied scientist|analytics engineer|database engineer|computer science", re.I)
SDE_TITLE = re.compile(r"\b(?:software (?:development |design )?engineer|software developer|sde|swe)\b", re.I)
EXCLUDED_LEVEL = re.compile(r"\b(?:sde|swe|engineer|developer)\s*(?:[-–—,:/(]\s*)?(?:[2-9]|10|II|III|IV|V|VI|VII|VIII|IX|X)\b|\b(?:level|l)\s*[-:]?\s*(?:[2-9]|10|II|III|IV|V)\b", re.I)

NEW_GRAD = re.compile(r"\b(?:new[ -](?:college[ -])?grad(?:uate|uates|uation)?|university[ -]grad(?:uate|uates)?|recent[ -]grad(?:uate|uates)?|graduat\w*|class of)\b", re.I)

def requires_us_citizenship(text):
    normalized=re.sub(r"\bu\s*\.\s*s\s*\.(?:\s*a\s*\.)?", "US", text, flags=re.I)
    citizen=r"(?:(?:us|usa|united states|american)[ -]+citizen(?:s|ship)?|citizens?\s+of\s+(?:the\s+)?(?:us|usa|united states))"
    for clause in re.split(r"[.!?;\n]",normalized):
        if not re.search(citizen,clause,re.I): continue
        # Explicit alternatives and negated requirements are not citizen-only.
        if re.search(r"\bor\s+(?:a\s+|an\s+)?(?:lawful\s+)?(?:permanent resident|green[ -]card holder|non[ -]citizen)",clause,re.I): continue
        negated=r"(?:no|not)\s+(?:a\s+)?(?:us|usa|united states|american)?\s*citizenship\s+(?:is\s+)?required|citizenship\s+(?:is\s+)?not\s+(?:required|necessary)|(?:does not|do not|doesn't|don't)\s+require\s+(?:a\s+)?"+citizen
        if re.search(negated,clause,re.I): continue
        before=r"(?:must|required|requires?|requirements?|mandatory|only|restricted to|limited to|need to|needs to|shall)\b[^.!?;\n]{0,100}"
        after=r"[^.!?;\n]{0,60}\b(?:required|mandatory|only|necessary)\b"
        if re.search(before+citizen,clause,re.I) or re.search(citizen+after,clause,re.I): return True
    return False

def explicit_grad_year(job, year):
    # Match within a title or a short sentence, never an unrelated footer date.
    for section in (job.title, job.description):
        for clause in re.split(r"[.!?;\n]", section):
            for marker in NEW_GRAD.finditer(clause):
                nearby=clause[max(0,marker.start()-100):marker.end()+120]
                if re.search(r"\b"+str(year)+r"\b",nearby):
                    if not re.search(r"not eligible|ineligible|must not|do not qualify|not accepting",nearby,re.I):
                        return True
    return False

def required_experience_years(description):
    normalized=description
    for word,number in [('zero',0),('one',1),('two',2),('three',3),('four',4),('five',5),('six',6),('seven',7),('eight',8),('nine',9),('ten',10)]:
        normalized=re.sub(r"\b"+word+r"(?=\s*\+?\s*years?\b)",str(number),normalized,flags=re.I)
    requirements=[]
    headings=list(re.finditer(r"preferred qualifications|preferred requirements|basic qualifications|minimum qualifications|required qualifications",normalized,re.I))
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*\+?\s*years?\b",normalized,re.I):
        before=normalized[max(0,match.start()-100):match.start()]
        after=normalized[match.end():match.end()+100]
        clause=re.split(r"[;\n.]",before)[-1]+match.group()+re.split(r"[;\n.]",after)[0]
        if not re.search(r"experience|minimum|at least|required|basic qualifications",clause,re.I): continue
        if re.search(r"(?:less than|fewer than|under|up to|maximum of)\s*$",before,re.I): continue
        heading=next((h.group().lower() for h in reversed(headings) if h.start()<match.start()),'')
        mandatory=bool(re.search(r"minimum|at least|required|must have",clause,re.I))
        if not mandatory and (heading.startswith('preferred') or re.search(r"preferred|nice to have|a plus|desirable",clause,re.I)): continue
        requirements.append(float(match.group(1)))
    return requirements

def classify(job: Job, graduation_year=None, *, software_only=True, strict_new_grad_year=None):
    t = job.title; d = job.description; text = t + " " + d
    job.reasons = []
    loc = job.location
    us = bool(re.search(r"United States|\bUS\b|\bUSA\b|\bU\.S\.\b|remote[^.]*\bUS\b",loc,re.I) or any(re.search(r",\s*"+s+r"\b",loc) for s in STATES))
    foreign = bool(re.search(r"Canada|India|Germany|United Kingdom|China|Taiwan|Israel|France|Singapore",loc,re.I))
    required = required_experience_years(d)
    job.experience = "; ".join(dict.fromkeys(re.findall(r"[^.\n]{0,60}\b\d+\s*(?:[-–]\s*\d+|\+)?\s*years?[^.\n]{0,80}",d,re.I))) or "Unspecified"
    job.graduation_years = sorted(set(re.findall(r"(?:graduat\w*|class of)[^.\n]{0,60}?\b(20\d{2})\b",text,re.I)))
    sponsor = re.search(r"[^.\n]*sponsor[^.\n]*",d,re.I)
    job.sponsorship = sponsor.group(0).strip() if sponsor else None
    reject = []
    if requires_us_citizenship(text): reject.append("US citizenship is required")
    if software_only and not SDE_TITLE.search(t): reject.append("Title is not a software development role")
    if not software_only and not TECH.search(t): reject.append("Title is not a relevant technical role")
    if strict_new_grad_year and not explicit_grad_year(job,strict_new_grad_year):
        reject.append("No explicit new-graduate eligibility for "+str(strict_new_grad_year))
    if EXCLUDED_LEVEL.search(t): reject.append("Excluded level II or higher")
    if re.search(r"\b(senior|sr\.?|staff|principal|lead|manager|director|intern|internship)\b",t,re.I): reject.append("Excluded seniority or internship")
    if required and max(required) >= 2: reject.append("Required experience is two years or more")
    if foreign and not us: reject.append("Exclusively non-US location")
    year_uncertain = bool(graduation_year and job.graduation_years and str(graduation_year) not in job.graduation_years)
    entry_evidence=bool(strict_new_grad_year or required or re.search(r"new grad|new college|university grad|entry.level|junior|early.career|engineer [I1]\b|sde [I1]\b|0\s*[-–]\s*[12]|no (?:prior |professional )?experience (?:required|necessary)",text,re.I))
    if not entry_evidence: reject.append("No clear entry-level or under-two-years experience evidence")
    if reject: job.classification="Not Eligible"; job.reasons=reject
    elif us and not year_uncertain and entry_evidence:
        job.classification="Strong Match"; job.reasons=["US location and entry-level evidence"]
    else:
        job.classification="Needs Review"; job.reasons=["Experience or US location requires review"]
    return job
