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

@pytest.mark.parametrize('blocked',[False,True])
async def test_search_readiness_retry_does_not_bypass_challenge(monkeypatch,blocked):
 from playwright.async_api import TimeoutError
 class Field:
  def __init__(self): self.calls=0; self.actions=[]
  @property
  def first(self): return self
  async def wait_for(self,**kwargs):
   self.calls+=1
   if self.calls==1: raise TimeoutError('slow search app')
  async def input_value(self): return 'United States'
  async def fill(self,value): self.actions.append(value)
  async def press(self,key): self.actions.append(key)
 query=Field(); location=Field(); location.calls=1
 class Page:
  def locator(self,selector): return location if selector=='#location' else query
  async def wait_for_timeout(self,*args): pass
 source=BrowserSource({'name':'NVIDIA','query_selector':'#query','location_selector':'#location','search_url':'https://example.com/careers?query=engineer'})
 reloads=[]
 async def goto(*args): reloads.append(1)
 async def diagnostics(*args):
  if blocked: raise Restricted('Search page displayed an access challenge')
 monkeypatch.setattr(source,'goto',goto); monkeypatch.setattr(source,'search_diagnostics',diagnostics)
 if blocked:
  with pytest.raises(Restricted): await source.initialize_search(Page())
  assert not reloads and not query.actions
 else:
  await source.initialize_search(Page())
  assert reloads==[1] and query.actions==['engineer','Enter','Escape','Tab']

async def test_missing_search_form_fails_after_bounded_recovery(monkeypatch):
 from playwright.async_api import TimeoutError
 class Field:
  @property
  def first(self): return self
  async def wait_for(self,**kwargs): raise TimeoutError('missing')
 class Page:
  def locator(self,*args): return Field()
 source=BrowserSource({'name':'NVIDIA','query_selector':'#query','location_selector':'#location','search_url':'https://example.com'})
 attempts=[]; reloads=[]
 async def diagnostics(page,attempt): attempts.append(attempt)
 async def goto(*args): reloads.append(1)
 monkeypatch.setattr(source,'search_diagnostics',diagnostics); monkeypatch.setattr(source,'goto',goto)
 with pytest.raises(RuntimeError,match='after two attempts'): await source.initialize_search(Page())
 assert attempts==[1,2] and reloads==[1]
