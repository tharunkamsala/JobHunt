import asyncio, os
import httpx
class Telegram:
    def __init__(self):
        self.send_lock=asyncio.Lock()
        self.last_sent=0.0
        self.token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(); self.chat=os.getenv("TELEGRAM_CHAT_ID", "").strip()
    async def send(self,text):
        async with self.send_lock:
            return await self._send(text)

    async def _send(self,text):
        if not self.token or not self.chat: return False
        async with httpx.AsyncClient(timeout=30) as client:
            for start in range(0,len(text),3500):
                for attempt in range(4):
                    try:
                        loop=asyncio.get_running_loop()
                        await asyncio.sleep(max(0,self.last_sent+1.1-loop.time()))
                        self.last_sent=loop.time()
                        r=await client.post("https://api.telegram.org/bot"+self.token+"/sendMessage",json={"chat_id":self.chat,"text":text[start:start+3500],"link_preview_options":{"is_disabled":True}})
                        if r.status_code==429:
                            delay=r.json().get("parameters",{}).get("retry_after",5)
                            if delay>120: return False
                            await asyncio.sleep(delay); continue
                        if r.status_code>=500: await asyncio.sleep(2**attempt); continue
                        if r.status_code!=200 or not r.json().get("ok"): return False
                        break
                    except (httpx.HTTPError,ValueError):
                        if attempt==3: return False
                        await asyncio.sleep(2**attempt)
                else: return False
        return True

def format_job(j):
    return "\n".join([j["company"],j["title"],j["location"],"Experience: "+j["experience"],j["classification"],"Posted: "+str(j["posting_date"] or "Unspecified"),"Discovered: "+j["first_discovered"],j["url"]])
