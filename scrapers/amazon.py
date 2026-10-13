import re
from bs4 import BeautifulSoup
from models import Job
from .base import BrowserSource

class AmazonSource(BrowserSource):
    async def detail(self,page,url,title):
        await self.goto(page,url)
        await page.locator('h1.title').wait_for(timeout=20000)
        await page.wait_for_function("Array.from(document.querySelectorAll('h2')).some(e=>e.textContent.trim()==='Basic Qualifications')",timeout=20000)
        soup=BeautifulSoup(await page.content(),'html.parser')
        title=soup.select_one('h1.title').get_text(' ',strip=True)
        sections=[]
        for heading in soup.select('h2'):
            if heading.get_text(strip=True) in ('Description','Basic Qualifications','Preferred Qualifications'):
                sections.append(heading.parent.get_text(' ',strip=True))
        meta=soup.select_one('p.meta')
        match=re.search(r'Job ID:\s*(\d+)',meta.get_text() if meta else '')
        heading=soup.find('h2',class_='job-details-title')
        locations=[]
        if heading:
            container=heading.parent.parent
            locations=[e.get_text(' ',strip=True) for e in container.select('li') if re.match(r'(?:USA|US),',e.get_text(strip=True))]
        if not locations:
            locations=[e.get_text(' ',strip=True) for e in soup.select('li') if re.match(r'(?:USA|US),',e.get_text(strip=True)) and not e.find('a')]
        if not match or not title or len(sections)!=3 or not locations or len(' '.join(sections))<100:
            raise ValueError('Incomplete Amazon title/ID/qualifications/US location fields')
        return Job(self.c['name'],match.group(1),title,'; '.join(dict.fromkeys(locations)),url,'\n'.join(sections))
