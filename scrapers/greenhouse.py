"""Documented public Job Board API, after visiting each real employer board."""
from html import unescape
from urllib.parse import urlsplit
import httpx
from bs4 import BeautifulSoup
from models import Job
from .base import BrowserSource, Restricted

class GreenhouseSource(BrowserSource):
    async def once(self,browser,result):
        context=await browser.new_context()
        try:
            page=await context.new_page()
            await self.goto(page,self.c['url']); result.pages=1
            token=urlsplit(self.c['url']).path.strip('/').split('/')[0]
            url=f'https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true'
            await self.allowed(url)
            async with httpx.AsyncClient(timeout=45) as client:
                response=await client.get(url)
            if response.status_code in (401,403,429): raise Restricted('Greenhouse access restriction '+str(response.status_code))
            response.raise_for_status(); data=response.json()
            result.total=data.get('meta',{}).get('total')
            rows=data.get('jobs',[]); result.listings=len(rows)
            for row in rows:
                if len(result.jobs)>=self.max_details:
                    result.errors.append('Detail safety limit reached'); return
                desc=BeautifulSoup(unescape(row.get('content','')),'html.parser').get_text(' ',strip=True)
                location=row.get('location',{}).get('name','')
                if not row.get('id') or not row.get('title') or not location or len(desc)<100 or not row.get('absolute_url'):
                    result.errors.append('Incomplete Greenhouse job fields'); continue
                await self.emit(result,Job(self.c['name'],str(row['id']),row['title'],location,row['absolute_url'],desc))
            if result.total is not None and result.total>0 and result.total==len(result.jobs) and len({j.job_id for j in result.jobs})==result.total:
                result.status='Verified Complete'
            else: result.errors.append('Missing/mismatched total or unverified empty board')
        finally: await context.close()
