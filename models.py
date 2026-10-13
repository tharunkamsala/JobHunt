from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib, json

def now(): return datetime.now(timezone.utc).isoformat()
@dataclass
class Job:
    company: str
    job_id: str
    title: str
    location: str
    url: str
    description: str
    posting_date: str | None = None
    experience: str = "Unspecified"
    classification: str = "Needs Review"
    reasons: list = field(default_factory=list)
    graduation_years: list = field(default_factory=list)
    sponsorship: str | None = None
    @property
    def key(self): return self.company + ":" + self.job_id
    @property
    def content_hash(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
@dataclass
class Scan:
    company: str
    status: str = "Incomplete"
    jobs: list = field(default_factory=list)
    pages: int = 0
    listings: int = 0
    total: int | None = None
    retries: int = 0
    errors: list = field(default_factory=list)
    started: str = field(default_factory=now)
    completed: str | None = None
