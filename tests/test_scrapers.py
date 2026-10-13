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

async def test_detail_restriction_stops_queued_requests(monkeypatch):
 class Links:
  async def evaluate_all(self,*args):
   return [{'url':f'https://example.com/jobs/{i}','title':'Software Engineer I'} for i in range(5)]
 class Page:
  async def wait_for_function(self,*args,**kwargs): pass
  def locator(self,*args): return Links()
  async def close(self): pass
 class Context:
  def __init__(self): self.created=0; self.closed=False
  async def new_page(self): self.created+=1; return Page()
  async def close(self): self.closed=True
 context=Context()
 class Browser:
  async def new_context(self,**kwargs): return context
 source=BrowserSource({'name':'Microsoft','url':'https://example.com','search_url':'https://example.com/search','job_pattern':'/jobs/','detail_concurrency':1})
 async def goto(*args): pass
 calls=[]
 async def detail(*args):
  calls.append(1)
  raise Restricted('Access restriction HTTP 403')
 monkeypatch.setattr(source,'goto',goto); monkeypatch.setattr(source,'detail',detail)
 from models import Scan
 with pytest.raises(Restricted): await source.once(Browser(),Scan('Microsoft'))
 assert len(calls)==1 and context.created==2 and context.closed

async def test_restriction_is_not_retried(monkeypatch):
 class Browser:
  async def close(self): pass
 class Chromium:
  async def launch(self,**kwargs): return Browser()
 class P: chromium=Chromium()
 source=BrowserSource({'name':'Microsoft'})
 calls=[]
 async def once(*args):
  calls.append(1); raise Restricted('Access restriction HTTP 403')
 monkeypatch.setattr(source,'once',once)
 result=await source.scan(P())
 assert result.status=='Restricted' and len(calls)==1 and result.retries==0
