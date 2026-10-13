import argparse, asyncio, json, logging, os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
from scrapers.base import BrowserSource
from scrapers.greenhouse import GreenhouseSource
from filters.eligibility import classify
from storage.database import Store
from notifications.telegram import Telegram, format_job
from models import now

async def run(args):
    store=Store(args.state); telegram=Telegram()
    configs=json.loads(Path(args.config).read_text())
    if args.company: configs=[c for c in configs if args.company.lower() in c["name"].lower()]
    if not configs: raise SystemExit("No matching sources")
    if store.data.get("last_scan"):
        gap=(datetime.now(timezone.utc)-datetime.fromisoformat(store.data["last_scan"])).total_seconds()
        if gap>4500: logging.warning("Missed or delayed scan: %.0f minutes since last start",gap/60)
    store.data["last_scan"]=now(); store.save()
    async def worker(p,c):
        adapter=GreenhouseSource if c["name"].startswith("Greenhouse:") else BrowserSource
        scan=await adapter(c,args.max_pages,args.max_details).scan(p)
        source=store.data["sources"].get(c["name"],{})
        baseline=not source.get("baseline_complete",False)
        counters={"new_matching":0,"duplicates":0,"rejected":0,"notifications":0,"notification_failures":0}
        for job in scan.jobs:
            classify(job,args.graduation_year)
            rec,new,changed=store.observe(job,baseline,args.alert_existing)
            if not new: counters["duplicates"]+=1
            # Never alert uncertain locations; uncertain experience remains reviewable.
            from filters.eligibility import STATES
            import re
            us=bool(re.search(r"United States|\bUS\b|\bUSA\b|remote[^.]*\bUS\b",job.location,re.I) or any(re.search(r",\s*"+s+r"\b",job.location) for s in STATES))
            if job.classification=="Not Eligible" or not us: counters["rejected"]+=1; continue
            if new: counters["new_matching"]+=1
            if rec['notified_hash']!=rec['content_hash'] and not args.dry_run:
                if await telegram.send(("Updated posting\n" if changed else "")+format_job(rec)):
                    rec['notified_hash']=rec['content_hash']; counters['notifications']+=1; store.save()
                else: counters['notification_failures']+=1
        source={"status":scan.status,"last_scan":scan.completed,"baseline_complete":source.get("baseline_complete",False) or scan.status=="Verified Complete","recovery_pending":scan.status!="Verified Complete"}
        store.data['sources'][c['name']]=source; store.save()
        report=asdict(scan); report.pop('jobs'); report.update(counters); report['extracted']=len(scan.jobs)
        if counters['notification_failures']: report['status']='Incomplete'; report['errors'].append('Telegram delivery failed; pending alerts retained')
        logging.info("%s",json.dumps(report))
        if scan.status!='Verified Complete' and not args.dry_run:
            await telegram.send(c['name']+": "+scan.status+"; recovery pending. "+"; ".join(scan.errors[:2]))
        return report
    async with async_playwright() as p:
        reports=await asyncio.gather(*(worker(p,c) for c in configs),return_exceptions=True)
    cleaned=[x if isinstance(x,dict) else {"status":"Failed","error":type(x).__name__} for x in reports]
    Path('diagnostics').mkdir(exist_ok=True); Path('diagnostics/scan.json').write_text(json.dumps(cleaned,indent=2))
    return 0 if all(x['status']=='Verified Complete' for x in cleaned) else 2

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',default='config/companies.json'); parser.add_argument('--state',default='state/history.json'); parser.add_argument('--company'); parser.add_argument('--graduation-year',type=int,default=int(os.environ['GRADUATION_YEAR']) if os.getenv('GRADUATION_YEAR') else None); parser.add_argument('--alert-existing',action='store_true',default=os.getenv('ALERT_EXISTING')=='true'); parser.add_argument('--dry-run',action='store_true'); parser.add_argument('--max-pages',type=int,default=100); parser.add_argument('--max-details',type=int,default=2000)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
