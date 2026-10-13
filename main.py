import argparse, asyncio, json, logging, os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
from scrapers.base import BrowserSource
from scrapers.greenhouse import GreenhouseSource
from scrapers.amazon import AmazonSource
from filters.eligibility import classify
from storage.database import Store
from notifications.telegram import Telegram
from notifications.processor import JobProcessor
from storage.checkpoint import Checkpoint
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
    checkpoint=Checkpoint(store.path, enabled=os.getenv('GITHUB_ACTIONS')=='true' and not args.dry_run)
    checkpoint_task=asyncio.create_task(checkpoint.run())
    async def worker(p,c):
        adapter=GreenhouseSource if c["name"].startswith("Greenhouse:") else AmazonSource if c["name"]=="Amazon" else BrowserSource
        source=store.data["sources"].get(c["name"],{})
        baseline=not source.get("baseline_initialized",False)
        processor=JobProcessor(store,telegram,baseline=baseline,alert_existing=args.alert_existing,
                               dry_run=args.dry_run,graduation_year=args.graduation_year,
                               on_delivery=checkpoint.mark_dirty,
                               software_only=c.get("software_only",True),
                               strict_new_grad_year=c.get("strict_new_grad_year"))
        scan=await adapter(c,args.max_pages,args.max_details,on_job=processor).scan(p)
        counters=processor.counters
        source={"status":scan.status,"last_scan":scan.completed,"baseline_complete":source.get("baseline_complete",False) or scan.status=="Verified Complete","baseline_initialized":source.get("baseline_initialized",False) or (bool(scan.jobs) and not args.dry_run),"recovery_pending":scan.status!="Verified Complete"}
        store.data['sources'][c['name']]=source; store.save()
        report=asdict(scan); report.pop('jobs'); report.update(counters); report['extracted']=len(scan.jobs)
        if counters['notification_failures']: report['status']='Incomplete'; report['errors'].append('Telegram delivery failed; pending alerts retained')
        logging.info("%s",json.dumps(report))
        if scan.status!='Verified Complete' and not args.dry_run:
            await telegram.send(c['name']+": "+scan.status+"; recovery pending. "+"; ".join(scan.errors[:2]))
        return report
    try:
        async with async_playwright() as p:
            reports=await asyncio.gather(*(worker(p,c) for c in configs),return_exceptions=True)
    finally:
        checkpoint.stopping=True
        checkpoint.mark_dirty()
        await checkpoint_task
    cleaned=[x if isinstance(x,dict) else {"status":"Failed","error":type(x).__name__} for x in reports]
    Path('diagnostics').mkdir(exist_ok=True); Path('diagnostics/scan.json').write_text(json.dumps(cleaned,indent=2))
    return 0 if all(x['status']=='Verified Complete' for x in cleaned) else 2

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',default='config/companies.json'); parser.add_argument('--state',default='state/history.json'); parser.add_argument('--company'); parser.add_argument('--graduation-year',type=int,default=int(os.environ['GRADUATION_YEAR']) if os.getenv('GRADUATION_YEAR') else None); parser.add_argument('--alert-existing',action='store_true',default=os.getenv('ALERT_EXISTING')=='true'); parser.add_argument('--dry-run',action='store_true'); parser.add_argument('--max-pages',type=int,default=200); parser.add_argument('--max-details',type=int,default=2000)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    raise SystemExit(asyncio.run(run(parser.parse_args())))
