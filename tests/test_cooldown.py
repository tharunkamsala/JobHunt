import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from storage.cooldown import retry_time,after_restriction
from storage.database import Store


def test_persistent_six_hour_cooldown(tmp_path):
 clock=datetime(2026,10,13,tzinfo=timezone.utc)
 deadline=after_restriction({'restriction_cooldown_hours':6},clock)
 store=Store(tmp_path/'history.json')
 store.data['sources']['Microsoft']={'status':'Restricted','retry_after':deadline}
 store.save()
 source=Store(store.path).data['sources']['Microsoft']
 assert retry_time(source,clock+timedelta(minutes=30))==deadline
 assert retry_time(source,clock+timedelta(hours=6)) is None
 assert retry_time({'retry_after':'bad'},clock) is None
 assert retry_time({'retry_after':'2026-10-13T00:00:00'},clock) is None

async def test_cooldown_skips_browser_worker(tmp_path,monkeypatch):
 import main
 monkeypatch.chdir(tmp_path)
 monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
 store=Store(tmp_path/'history.json')
 store.data['sources']['Microsoft']={'status':'Restricted','retry_after':after_restriction({'restriction_cooldown_hours':6})}
 store.save()
 config=tmp_path/'companies.json'; config.write_text(json.dumps([{'name':'Microsoft'}]))
 class Context:
  async def __aenter__(self): return object()
  async def __aexit__(self,*args): pass
 def forbidden(*args,**kwargs): raise AssertionError('Browser source must not be instantiated during cooldown')
 monkeypatch.setattr(main,'async_playwright',Context)
 monkeypatch.setattr(main,'BrowserSource',forbidden)
 args=SimpleNamespace(state=str(store.path),config=str(config),company=None,dry_run=False)
 assert await main.run(args)==2
 report=json.loads((tmp_path/'diagnostics/scan.json').read_text())[0]
 assert report['status']=='Restricted' and report['extracted']==0
