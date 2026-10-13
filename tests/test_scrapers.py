import json
import pytest
from scrapers.base import BrowserSource, Restricted

class Locator:
 async def inner_text(self): return 'Job description'
class Page:
 async def content(self):
  return '<script type="application/ld+json">'+json.dumps({'@type':'JobPosting','title':'Software Engineer','identifier':{'value':'123'},'description':'Build software. '*30,'jobLocation':{'address':{'addressLocality':'Seattle','addressRegion':'WA','addressCountry':'US'}}})+'</script>'

async def test_structured_detail(monkeypatch):
 source=BrowserSource({'name':'Test'})
 async def goto(*a): pass
 monkeypatch.setattr(source,'goto',goto)
 job=await source.detail(Page(),'https://example.com/jobs/123','')
 assert job.job_id=='123' and 'United States' in job.location

async def test_retry(monkeypatch):
 class Browser:
  async def close(self): pass
 class Chromium:
  async def launch(self,**kwargs): return Browser()
 class P: chromium=Chromium()
 source=BrowserSource({'name':'Test'})
 calls=[]
 async def once(browser,result):
  calls.append(1)
  if len(calls)<3: raise ValueError('temporary')
  result.status='Verified Complete'
 async def sleep(*a): pass
 monkeypatch.setattr(source,'once',once)
 monkeypatch.setattr('scrapers.base.asyncio.sleep',sleep)
 result=await source.scan(P())
 assert result.status=='Verified Complete' and result.retries==2
