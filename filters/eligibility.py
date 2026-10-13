import re
from models import Job
STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
TECH = re.compile(r"software|developer|machine learning|data (?:engineer|scien)|cloud|devops|site reliability|platform engineer|infrastructure engineer|systems engineer|security engineer|firmware|embedded|test engineer|automation engineer|applied scientist|analytics engineer|database engineer|computer science", re.I)
def classify(job: Job, graduation_year=None):
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
    if not TECH.search(text): reject.append("No relevant technical evidence")
    if re.search(r"\b(senior|sr\.?|staff|principal|lead|manager|director|intern|internship)\b",t,re.I): reject.append("Excluded seniority or internship")
    if required and max(map(int,required)) > 2: reject.append("Explicit required experience exceeds two years")
    if foreign and not us: reject.append("Exclusively non-US location")
    year_uncertain = bool(graduation_year and job.graduation_years and str(graduation_year) not in job.graduation_years)
    if reject: job.classification="Not Eligible"; job.reasons=reject
    elif us and not year_uncertain and (required or re.search(r"new grad|new college|university grad|entry.level|junior|early.career|engineer [I1]\b|sde [I1]\b|0\s*[-–]\s*2",text,re.I)):
        job.classification="Strong Match"; job.reasons=["US location and entry-level evidence"]
    else:
        job.classification="Needs Review"; job.reasons=["Experience or US location requires review"]
    return job
