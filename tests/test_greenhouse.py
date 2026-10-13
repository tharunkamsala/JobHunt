import pytest
from models import Scan
from scrapers.greenhouse import GreenhouseSource

@pytest.mark.parametrize('total,expected',[(1,'Verified Complete'),(2,'Incomplete'),(0,'Incomplete')])
async def test_api_completeness(monkeypatch,total,expected):
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self):
            return {'meta':{'total':total},'jobs':[{'id':123,'title':'Software Engineer','location':{'name':'United States'},'absolute_url':'https://boards.greenhouse.io/example/jobs/123','content':'&lt;p&gt;Build software and infrastructure. &lt;/p&gt;'*20}]}
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url): return Response()
    class Context:
        async def new_page(self): return object()
        async def close(self): pass
    class Browser:
        async def new_context(self): return Context()
    async def noop(*args): pass
    monkeypatch.setattr('scrapers.greenhouse.httpx.AsyncClient',Client)
    source=GreenhouseSource({'name':'Greenhouse: Example','url':'https://boards.greenhouse.io/example'})
    monkeypatch.setattr(source,'goto',noop); monkeypatch.setattr(source,'allowed',noop)
    result=Scan('Greenhouse: Example')
    await source.once(Browser(),result)
    assert result.status==expected
    assert '<p>' not in result.jobs[0].description
    assert result.jobs[0].posting_date is None
