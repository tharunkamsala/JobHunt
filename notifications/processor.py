"""Classify and alert each verified detail while other source workers continue."""
import asyncio
import re
import logging
from filters.eligibility import STATES, classify
from models import now
from notifications.telegram import format_job

class JobProcessor:
    def __init__(self, store, telegram, *, baseline=False, alert_existing=False,
                 dry_run=False, graduation_year=None, on_delivery=None,
                 software_only=True, strict_new_grad_year=None):
        self.store=store
        self.telegram=telegram
        self.baseline=baseline
        self.alert_existing=alert_existing
        self.dry_run=dry_run
        self.graduation_year=graduation_year
        self.software_only=software_only
        self.strict_new_grad_year=strict_new_grad_year
        self.on_delivery=on_delivery
        self.locks={}
        self.processed=set()
        self.counters={"new_matching":0,"duplicates":0,"rejected":0,
                       "notifications":0,"notification_failures":0}

    async def __call__(self,job):
        await asyncio.sleep(0)
        classify(job,self.graduation_year,software_only=self.software_only,
                 strict_new_grad_year=self.strict_new_grad_year)
        async with self.locks.setdefault(job.key,asyncio.Lock()):
            version=(job.key,job.content_hash)
            if version in self.processed:
                return
            rec,new,changed=self.store.observe(job,self.baseline,self.alert_existing)
            if not new: self.counters['duplicates']+=1
            # A company + posting ID gets one successful alert for its lifetime,
            # even when its JD, title, URL, or classification changes later.
            if rec.get('delivered_at') or rec.get('notification_status')=='sent':
                self.processed.add(version)
                return
            us=bool(re.search(r'United States|\bUS\b|\bUSA\b',job.location,re.I)
                    or any(re.search(r',\s*'+state+r'\b',job.location) for state in STATES))
            if job.classification=='Not Eligible' or not us:
                self.counters['rejected']+=1
                self.processed.add(version)
                return
            if new: self.counters['new_matching']+=1
            if rec['notified_hash']!=rec['content_hash'] and not self.dry_run:
                if await self.telegram.send(format_job(rec)):
                    rec['notified_hash']=rec['content_hash']
                    rec['notification_status']='sent'
                    rec['delivered_at']=now()
                    self.counters['notifications']+=1
                    self.store.save()
                    logging.info("Telegram job delivered: %s %s",job.company,job.job_id)
                    if self.on_delivery: self.on_delivery()
                else:
                    self.counters['notification_failures']+=1
                    # Keep failed deliveries retryable if this detail appears on recovery.
                    return
            self.processed.add(version)
