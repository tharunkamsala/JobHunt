from storage.database import Store
from models import Job

def test_history(tmp_path):
 path=tmp_path/'history.json'; s=Store(path)
 j=Job('A','1','Software Engineer','United States','https://example.com/jobs/1','description')
 rec,new,changed=s.observe(j,True)
 assert new and rec['notified_hash']==j.content_hash
 rec,new,changed=Store(path).observe(j)
 assert not new and not changed
 first=rec['first_discovered']; j.description='updated'
 rec,new,changed=Store(path).observe(j)
 assert changed and rec['notified_hash']!=j.content_hash and rec['first_discovered']==first
