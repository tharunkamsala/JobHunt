import json, os
from pathlib import Path
from dataclasses import asdict
from models import now
class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {"jobs":{},"sources":{},"last_scan":None}
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix(".tmp"); tmp.write_text(json.dumps(self.data,indent=2)); os.replace(tmp,self.path)
    def observe(self,job,baseline=False,alert_existing=False):
        old=self.data["jobs"].get(job.key)
        changed=old is not None and old["content_hash"]!=job.content_hash
        rec={**asdict(job),"content_hash":job.content_hash,"first_discovered":old["first_discovered"] if old else now(),"last_seen":now(),"notified_hash":old.get("notified_hash") if old else None}
        if baseline and not alert_existing and old is None: rec["notified_hash"]=job.content_hash
        self.data["jobs"][job.key]=rec
        self.save()
        return rec, old is None, changed
