import asyncio
from models import Job, Scan
from storage.database import Store
from notifications.processor import JobProcessor
from scrapers.base import BrowserSource

class Telegram:
    def __init__(self,results=None): self.messages=[]; self.results=iter(results or [True]*10)
    async def send(self,text):
        self.messages.append(text)
        return next(self.results)

def job(): return Job('Test','1','Software Engineer I','Seattle, WA','https://example.com/jobs/1','Minimum 1 year of experience building software.')

def test_streaming_before_source_finishes_and_deduplicates(tmp_path):
    async def scenario():
        telegram=Telegram(); store=Store(tmp_path/'history.json')
        processor=JobProcessor(store,telegram,baseline=True,alert_existing=True)
        source=BrowserSource({'name':'Test'},on_job=processor)
        scan=Scan('Test'); release=asyncio.Event()
        async def worker():
            await source.emit(scan,job())
            await release.wait()
            await source.emit(scan,job())
        task=asyncio.create_task(worker())
        for _ in range(10): await asyncio.sleep(0)
        assert len(telegram.messages)==1 and not task.done()
        release.set(); await task
        assert len(telegram.messages)==1
        record=Store(store.path).data['jobs']['Test:1']
        assert record['notification_status']=='sent' and record['delivered_at']
        # Existing jobs explicitly enabled must not resend a delivered version.
        await JobProcessor(Store(store.path),telegram,alert_existing=True)(job())
        assert len(telegram.messages)==1
    asyncio.run(scenario())

def test_failed_delivery_retried_and_baseline_released(tmp_path):
    async def scenario():
        store=Store(tmp_path/'history.json'); store.observe(job(),baseline=True)
        telegram=Telegram([False,True]); processor=JobProcessor(store,telegram,alert_existing=True)
        await processor(job())
        assert store.data['jobs']['Test:1']['notified_hash'] is None
        await processor(job())
        assert len(telegram.messages)==2
        assert store.data['jobs']['Test:1']['notification_status']=='sent'
    asyncio.run(scenario())

def test_checkpoint_persists_during_scan(tmp_path,monkeypatch):
    import subprocess
    from storage.checkpoint import Checkpoint
    repo=tmp_path/'repo'; repo.mkdir(); remote=tmp_path/'remote.git'
    def git(*args,cwd=repo):
        return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.DEVNULL,text=True)
    git('init','--bare',str(remote))
    git('init'); git('config','user.name','Test'); git('config','user.email','test@example.com')
    (repo/'history.json').write_text('{}')
    git('add','.'); git('commit','-m','initial'); git('branch','-M','bot-state')
    git('remote','add','origin',str(remote)); git('push','-u','origin','bot-state')
    state=tmp_path/'state.json'; state.write_text('{"delivered":true}')
    monkeypatch.chdir(repo)
    async def scenario():
        checkpoint=Checkpoint(state,enabled=True)
        task=asyncio.create_task(checkpoint.run()); checkpoint.mark_dirty()
        for _ in range(100):
            await asyncio.sleep(.02)
            if git('--git-dir',str(remote),'show','bot-state:history.json')==state.read_text(): break
        assert not task.done()
        assert git('--git-dir',str(remote),'show','bot-state:history.json')==state.read_text()
        state.write_text('{"delivered":2}')
        checkpoint.stopping=True; checkpoint.mark_dirty(); await task
        assert git('--git-dir',str(remote),'show','bot-state:history.json')==state.read_text()
    asyncio.run(scenario())

def test_strict_greenhouse_preference_blocks_unspecified_year(tmp_path):
    async def scenario():
        telegram=Telegram(); store=Store(tmp_path/'history.json')
        processor=JobProcessor(store,telegram,alert_existing=True,
                               software_only=False,strict_new_grad_year=2027)
        j=job(); j.company='Greenhouse: Databricks'
        await processor(j)
        assert not telegram.messages
        j.description='New graduates graduating in 2027 are eligible.'
        await processor(j)
        assert len(telegram.messages)==1
    asyncio.run(scenario())

def test_citizen_only_never_sent_for_any_source(tmp_path):
    async def scenario():
        telegram=Telegram(); store=Store(tmp_path/'history.json')
        for company in ['Microsoft','Amazon','NVIDIA','Greenhouse: Cloudflare','Greenhouse: Databricks']:
            processor=JobProcessor(store,telegram,alert_existing=True,
                software_only=not company.startswith('Greenhouse:'),
                strict_new_grad_year=2027 if company.startswith('Greenhouse:') else None)
            j=job(); j.company=company
            j.description='New graduates graduating in 2027. Must be a U.S. citizen.'
            await processor(j)
        assert not telegram.messages
        assert all(j['classification']=='Not Eligible' for j in store.data['jobs'].values())
    asyncio.run(scenario())

def test_two_year_requirement_never_alerts(tmp_path):
    async def scenario():
        telegram=Telegram(); store=Store(tmp_path/'history.json')
        for company in ['Microsoft','Amazon','NVIDIA','Greenhouse: Cloudflare','Greenhouse: Databricks']:
            processor=JobProcessor(store,telegram,alert_existing=True,
                software_only=not company.startswith('Greenhouse:'),
                strict_new_grad_year=2027 if company.startswith('Greenhouse:') else None)
            j=job(); j.company=company
            j.description='New graduates graduating in 2027. Minimum 2 years of development experience.'
            await processor(j)
        assert not telegram.messages
    asyncio.run(scenario())
