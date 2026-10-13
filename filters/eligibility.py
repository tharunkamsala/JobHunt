import re
from models import Job
STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
TECH = re.compile(r"software|developer|machine learning|data (?:engineer|scien)|cloud|devops|site reliability|platform engineer|infrastructure engineer|systems engineer|security engineer|firmware|embedded|test engineer|automation engineer|applied scientist|analytics engineer|database engineer|computer science", re.I)
SDE_TITLE = re.compile(r"\b(?:software (?:development |design )?engineer|software developer|sde|swe)\b", re.I)
EXCLUDED_LEVEL = re.compile(r"\b(?:sde|swe|engineer|developer)\s*(?:[-–—,:/(]\s*)?(?:[2-9]|10|II|III|IV|V|VI|VII|VIII|IX|X)\b|\b(?:level|l)\s*[-:]?\s*(?:[2-9]|10|II|III|IV|V)\b", re.I)

NEW_GRAD = re.compile(r"\b(?:new[ -](?:college[ -])?grad(?:uate|uates|uation)?|university[ -]grad(?:uate|uates)?|recent[ -]grad(?:uate|uates)?|graduat\w*|class of)\b", re.I)

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

def classify(job: Job, graduation_year=None, *, software_only=True, strict_new_grad_year=None):
    t = job.title; d = job.description; text = t + " " + d
    job.reasons = []
    loc = job.location
    us = bool(re.search(r"United States|\bUS\b|\bUSA\b|\bU\.S\.\b|remote[^.]*\bUS\b",loc,re.I) or any(re.search(r",\s*"+s+r"\b",loc) for s in STATES))
    foreign = bool(re.search(r"Canada|India|Germany|United Kingdom|China|Taiwan|Israel|France|Singapore",loc,re.I))
    required = re.findall(r"(?:minimum|at least|required|basic qualifications)[^.\n]{0,80}?(\d+)\+?\s*years?", d,re.I)
    required += re.findall(r"(\d+)\+?\s*years?[^.\n]{0,50}(?:required|minimum)",d,re.I)
    job.experience = "; ".join(dict.fromkeys(re.findall(r"[^.\n]{0,60}\b\d+\s*(?:[-–]\s*\d+|\+)?\s*years?[^.\n]{0,80}",d,re.I))) or "Unspecified"
    job.graduation_years = sorted(set(re.findall(r"(?:graduat\w*|class of)[^.\n]{0,60}?\b(20\d{2})\b",text,re.I)))
    sponsor = re.search(r"[^.\n]*sponsor[^.\n]*",d,re.I)
    job.sponsorship = sponsor.group(0).strip() if sponsor else None
    reject = []
    if software_only and not SDE_TITLE.search(t): reject.append("Title is not a software development role")
    if not software_only and not TECH.search(t): reject.append("Title is not a relevant technical role")
    if strict_new_grad_year and not explicit_grad_year(job,strict_new_grad_year):
        reject.append("No explicit new-graduate eligibility for "+str(strict_new_grad_year))
    if EXCLUDED_LEVEL.search(t): reject.append("Excluded level II or higher")
    if re.search(r"\b(senior|sr\.?|staff|principal|lead|manager|director|intern|internship)\b",t,re.I): reject.append("Excluded seniority or internship")
    if required and max(map(int,required)) > 2: reject.append("Explicit required experience exceeds two years")
    if foreign and not us: reject.append("Exclusively non-US location")
    year_uncertain = bool(graduation_year and job.graduation_years and str(graduation_year) not in job.graduation_years)
    if reject: job.classification="Not Eligible"; job.reasons=reject
    elif us and not year_uncertain and (strict_new_grad_year or required or re.search(r"new grad|new college|university grad|entry.level|junior|early.career|engineer [I1]\b|sde [I1]\b|0\s*[-–]\s*2",text,re.I)):
        job.classification="Strong Match"; job.reasons=["US location and entry-level evidence"]
    else:
        job.classification="Needs Review"; job.reasons=["Experience or US location requires review"]
    return job
