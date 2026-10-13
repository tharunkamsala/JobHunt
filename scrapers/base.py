import asyncio, json, re
from pathlib import Path
from playwright.async_api import TimeoutError as BrowserTimeout
from urllib.parse import urljoin, urlsplit, parse_qs
from protego import Protego
from bs4 import BeautifulSoup
import httpx
from models import Job, Scan, now

class Restricted(Exception): pass
class BrowserSource:
    def __init__(self, config, max_pages=100, max_details=2000, on_job=None):
        self.on_job=on_job
        self.c=config; self.max_pages=max_pages; self.max_details=max_details; self.policies={}; self.rate_locks={}; self.last_requests={}
    async def emit(self,result,job):
        result.jobs.append(job)
        if self.on_job is not None:
            await self.on_job(job)
    async def pace(self,origin,policy):
        delay=max(0.5,float(self.c.get('request_interval',0.5)))
        if policy is not None:
            delay=max(delay,policy.crawl_delay("NewGradJobHunter") or 0)
            rate=policy.request_rate("NewGradJobHunter")
            if rate and rate.requests: delay=max(delay,rate.seconds/rate.requests)
        if delay>600: raise Restricted("Source crawl delay exceeds scan budget")
        lock=self.rate_locks.setdefault(origin,asyncio.Lock())
        async with lock:
            loop=asyncio.get_running_loop()
            await asyncio.sleep(max(0,self.last_requests.get(origin,0)+delay-loop.time()))
            self.last_requests[origin]=loop.time()
    async def allowed(self,url):
        parts=urlsplit(url); robots=f"{parts.scheme}://{parts.netloc}/robots.txt"
        if robots in self.policies:
            rp=self.policies[robots]
            if rp is not None and not rp.can_fetch(url,"NewGradJobHunter"): raise Restricted("robots.txt disallows requested URL")
            await self.pace(robots,rp)
            return
        async with httpx.AsyncClient(timeout=25,follow_redirects=True) as client:
            response=await client.get(robots)
        if response.status_code==404:
            self.policies[robots]=None
            await self.pace(robots,None)
            return
        if response.status_code!=200: raise Restricted("robots.txt unavailable: "+str(response.status_code))
        if "<html" in response.text.lower() or "<!doctype" in response.text.lower(): raise Restricted("robots.txt returned HTML; access policy unverified")
        rp=Protego.parse(response.text); self.policies[robots]=rp
        if not rp.can_fetch(url,"NewGradJobHunter"): raise Restricted("robots.txt disallows requested URL")
        await self.pace(robots,rp)
    async def goto(self,page,url):
        await self.allowed(url)
        response=await page.goto(url,wait_until="domcontentloaded",timeout=45000)
        if response and response.status in (401,403,429): raise Restricted("Access restriction HTTP "+str(response.status))
        await page.wait_for_timeout(1500)
        body=await page.locator("body").inner_text()
        if re.search(r"verify you are human|access denied|unusual traffic|complete the captcha",body,re.I): raise Restricted("Access challenge; no bypass attempted")
    async def detail(self,page,url,title):
        await self.goto(page,url)
        soup=BeautifulSoup(await page.content(),"html.parser")
        payload=None
        def find(obj):
            if isinstance(obj,dict):
                if obj.get("@type")=="JobPosting": return obj
                for v in obj.values():
                    result=find(v)
                    if result: return result
            if isinstance(obj,list):
                for v in obj:
                    result=find(v)
                    if result: return result
        for script in soup.select('script[type="application/ld+json"]'):
            try: payload=find(json.loads(script.get_text()))
            except (ValueError,TypeError): continue
            if payload: break
        if not payload: raise ValueError("No validated JobPosting structured data on detail page")
        title=payload.get("title") or title
        desc=BeautifulSoup(payload.get("description", ""),"html.parser").get_text(" ",strip=True)
        locations=payload.get("jobLocation",[])
        if isinstance(locations,dict): locations=[locations]
        loc=[]
        for entry in locations:
            addr=entry.get("address",{})
            if isinstance(addr,str): loc.append(addr); continue
            country=addr.get("addressCountry","")
            if isinstance(country,dict): country=country.get("name","")
            country={"US":"United States","CA":"Canada","IN":"India","GB":"United Kingdom","DE":"Germany","CN":"China","TW":"Taiwan","IL":"Israel","FR":"France","SG":"Singapore"}.get(country,country)
            loc.append(", ".join(str(v) for v in [addr.get("addressLocality"),addr.get("addressRegion"),country] if v))
        for entry in payload.get("applicantLocationRequirements",[]) if isinstance(payload.get("applicantLocationRequirements"),list) else [payload.get("applicantLocationRequirements",{})]:
            if entry.get("name"): loc.append(entry["name"])
        ident=payload.get("identifier",{})
        jid=str(ident.get("value", "")) if isinstance(ident,dict) else str(ident)
        if not jid:
            match=re.search(r"(?:jobs?/|gh_jid=)([\w-]+)",url)
            jid=match.group(1) if match else urlsplit(url).path
        if not title or len(desc)<100 or not loc or not jid: raise ValueError("Incomplete job detail fields")
        return Job(self.c["name"],jid,title,"; ".join(loc),url,desc,payload.get("datePosted"))
    async def search_diagnostics(self,page,attempt):
        name=re.sub(r'[^a-z0-9]+','-',self.c['name'].lower())
        directory=Path('diagnostics'); directory.mkdir(exist_ok=True)
        body=await page.locator('body').inner_text()
        (directory/f'{name}-search-{attempt}.json').write_text(json.dumps({
            'url':page.url,'title':await page.title(),'body':body[:8000],
            'inputs':await page.locator('input').evaluate_all(
                'es=>es.map(e=>({id:e.id,placeholder:e.placeholder,visible:!!e.getClientRects().length}))')
        },indent=2))
        if re.search(r'verify you are human|access denied|unusual traffic|complete the captcha',body,re.I):
            raise Restricted('Search page displayed an access challenge')

    async def initialize_search(self,page):
        if not self.c.get('query_selector'): return
        selectors=[self.c['query_selector']]+self.c.get('query_fallback_selectors',[])
        query=page.locator(', '.join(s+':visible' for s in selectors)).first
        location=page.locator(self.c['location_selector'])
        timeout=self.c.get('search_ready_timeout_ms',30000)
        for attempt in range(2):
            try:
                await query.wait_for(timeout=timeout)
                await location.wait_for(timeout=timeout)
                break
            except BrowserTimeout:
                await self.search_diagnostics(page,attempt+1)
                if attempt:
                    raise RuntimeError('Search form did not load after two attempts; page diagnostics saved') from None
                await self.goto(page,self.c['search_url'])
        if 'United States' not in await location.input_value():
            raise ValueError('US location filter did not initialize')
        params=parse_qs(urlsplit(self.c['search_url']).query)
        keyword=(params.get('query') or params.get('base_query') or [''])[0]
        await query.fill(keyword)
        await query.press('Enter')
        await page.wait_for_timeout(2000)
        await query.press('Escape')
        await query.press('Tab')
    async def once(self,browser,result):
        context=await browser.new_context(user_agent="NewGradJobHunter/1.0 (personal career monitor)")
        try:
            page=await context.new_page()
            await self.goto(page,self.c["url"])
            await self.goto(page,self.c["search_url"])
            await self.initialize_search(page)
            # URL parameters initialize location; the actual keyword input executes search.
            seen=set(); signatures=set(); detail_failed=False
            for _ in range(self.max_pages):
                await page.wait_for_function("pattern => Array.from(document.querySelectorAll('a[href]')).some(e => new RegExp(pattern).test(e.href))",arg=self.c["job_pattern"],timeout=30000)
                links=await page.locator(self.c.get("listing_selector","a[href]")).evaluate_all("els => els.map(e => ({url:e.href,title:e.innerText.trim()}))")
                links={x['url'].split('#')[0]:x['title'] for x in links if re.search(self.c['job_pattern'],x['url']) and x['title']}
                if not links: raise ValueError("No job links found; empty result is unverified")
                signature=tuple(sorted(links))
                if signature in signatures: raise ValueError("Pagination repeated a result page")
                signatures.add(signature); result.pages+=1
                if self.c.get("total_selector"):
                    count=await page.locator(self.c["total_selector"]).inner_text()
                    match=re.fullmatch(r"([\d,]+) jobs",count.strip(),re.I)
                    if match: result.total=int(match.group(1).replace(',',''))
                # Facet counts are never used as a source total (Amazon has no exact UI total).
                pending=[(url,title) for url,title in links.items() if url not in seen]
                remaining=self.max_details-len(seen)
                limited=len(pending)>remaining
                pending=pending[:remaining]
                semaphore=asyncio.Semaphore(self.c.get('detail_concurrency',4))
                blocked=None
                async def extract(url,title):
                    nonlocal detail_failed,blocked
                    async with semaphore:
                        if blocked is not None: return
                        seen.add(url); result.listings=len(seen)
                        detail=await context.new_page()
                        try: job=await self.detail(detail,url,title)
                        except Restricted as exc:
                            blocked=exc
                        except Exception as exc:
                            detail_failed=True; result.errors.append("Detail: "+type(exc).__name__+": "+str(exc)[:200])
                        else: await self.emit(result,job)
                        finally: await detail.close()
                await asyncio.gather(*(extract(url,title) for url,title in pending))
                if blocked is not None: raise blocked
                if limited: raise ValueError("Detail safety limit reached")
                reject=page.get_by_role("button",name=re.compile(r"^Reject(?: all)?$",re.I))
                if await reject.count() and await reject.first.is_visible(): await reject.first.click()
                nxt=page.get_by_role("button",name=re.compile(r"^(next|next page|next jobs|load more(?: roles)?)$",re.I)).or_(page.get_by_role("link",name=re.compile(r"^next(?: page)?$",re.I)))
                if await nxt.count() and await nxt.first.is_enabled():
                    await nxt.first.click(); await page.wait_for_timeout(2000)
                else:
                    if not detail_failed and result.total is not None and result.total==len(seen): result.status="Verified Complete"
                    else: result.errors.append("Completeness unverified: absent/mismatched source total or detail failures")
                    return
            raise ValueError("Pagination safety limit reached")
        finally: await context.close()
    async def scan(self,playwright):
        final=Scan(self.c["name"])
        deadline=asyncio.get_running_loop().time()+1500
        collected={}
        for attempt in range(3):
            result=Scan(self.c["name"],retries=attempt)
            browser=None
            try:
                browser=await playwright.chromium.launch(headless=True)
                await asyncio.wait_for(self.once(browser,result),timeout=min(1200,max(1,deadline-asyncio.get_running_loop().time())))
                final=result
                if result.status=="Verified Complete": break
            except Exception as exc:
                result.status="Restricted" if isinstance(exc,Restricted) else "Failed" if not result.jobs else "Incomplete"
                result.errors.append(type(exc).__name__+": "+str(exc)[:300]); final=result
                if isinstance(exc,Restricted): break
            finally:
                if browser: await browser.close()
            collected.update({job.key:job for job in result.jobs})
            if asyncio.get_running_loop().time()>=deadline: break
            if attempt<2: await asyncio.sleep(2**(attempt+1))
        if final.status!="Verified Complete":
            collected.update({job.key:job for job in final.jobs}); final.jobs=list(collected.values())
        final.completed=now()
        return final
