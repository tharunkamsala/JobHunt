"""Checkpoint delivered alerts to the state branch while scans continue."""
import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

class Checkpoint:
    def __init__(self,path,enabled=False):
        self.path=Path(path).resolve()
        self.enabled=enabled
        self.event=asyncio.Event()
        self.stopping=False
        self.directory=None

    def mark_dirty(self):
        self.event.set()

    async def git(self,*args,check=True):
        proc=await asyncio.create_subprocess_exec('git',*args,cwd=self.directory,
                    stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL)
        try: code=await asyncio.wait_for(proc.wait(),60)
        except asyncio.TimeoutError:
            proc.kill(); await proc.wait(); raise RuntimeError('Git checkpoint timed out')
        if check and code: raise RuntimeError('Git checkpoint failed')
        return code

    async def save(self):
        if self.directory is None:
            directory=tempfile.mkdtemp(prefix='hunter-checkpoint-')
            await self.git('worktree','add','--detach',directory,'origin/bot-state')
            self.directory=directory
            await self.git('config','user.name','job-hunter[bot]')
            await self.git('config','user.email','job-hunter@users.noreply.github.com')
        shutil.copyfile(self.path,Path(self.directory)/'history.json')
        await self.git('add','history.json')
        if await self.git('diff','--cached','--quiet',check=False):
            await self.git('commit','-m','Checkpoint streamed Telegram deliveries')
        # Retry the push even when a previous commit succeeded but its push failed.
        await self.git('push','origin','HEAD:bot-state')
        logging.info('Streamed alert history checkpoint saved')

    async def run(self):
        if not self.enabled: return
        while True:
            await self.event.wait()
            self.event.clear()
            try: await self.save()
            except Exception as exc:
                logging.warning('State checkpoint unavailable (%s); final workflow save will retry',type(exc).__name__)
            if self.stopping:
                if self.event.is_set(): continue
                return
            # Collect deliveries for the next checkpoint without delaying Telegram.
            try: await asyncio.wait_for(self._stop_wait(),30)
            except asyncio.TimeoutError: pass

    async def _stop_wait(self):
        while not self.stopping:
            await asyncio.sleep(0.5)
