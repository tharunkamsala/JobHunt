"""Bounded live listing/pagination test; no notifications or durable job history."""
import asyncio,json,sys,re
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from scrapers.base import BrowserSource
async def main():
    cs=json.loads(Path('config/companies.json').read_text())[:3]
    async with async_playwright() as p:
        async def check(c):
            b=await p.chromium.launch(); context=await b.new_context(); page=await context.new_page()
            result={'company':c['name']}
            try:
                await BrowserSource(c).goto(page,c['search_url'])
                selector=c['listing_selector']
                await page.locator(selector).first.wait_for(timeout=30000)
                result['keyword']=await page.locator(c['query_selector']).input_value()
                result['location']=await page.locator(c['location_selector']).input_value()
                # Exercise the actual search field while retaining the initialized US filter.
                await page.locator(c['query_selector']).fill(result['keyword'])
                await page.locator(c['query_selector']).press('Enter')
                await page.wait_for_timeout(2500)
                await page.locator(selector).first.wait_for(timeout=30000)
                reject=page.get_by_role('button',name=re.compile(r'^Reject all$',re.I))
                if await reject.count() and await reject.first.is_visible(): await reject.first.click()
                before=await page.locator(selector).evaluate_all('es=>es.map(e=>e.href)')
                next_button=page.get_by_role('button',name=re.compile(r'^Next (?:jobs|page)$',re.I))
                await next_button.click()
                await page.wait_for_function('([selector,before])=>document.querySelectorAll(selector).length>0 && JSON.stringify(Array.from(document.querySelectorAll(selector),e=>e.href))!==JSON.stringify(before)',arg=[selector,before],timeout=30000)
                after=await page.locator(selector).evaluate_all('es=>es.map(e=>e.href)')
                if not before or not after or set(before)==set(after): raise ValueError('Page did not change')
                result.update(first_count=len(before),second_count=len(after),status='Passed')
            except Exception as e:result.update(status='Failed',error=type(e).__name__+': '+str(e)[:300])
            finally:await b.close()
            return result
        results=await asyncio.gather(*(check(c) for c in cs))
    Path('diagnostics/pagination.json').write_text(json.dumps(results,indent=2)); print(json.dumps(results,indent=2))
asyncio.run(main())
