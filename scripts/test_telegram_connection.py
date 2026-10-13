"""Send a setup verification with environment secrets; never print credentials."""
import asyncio,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from notifications.telegram import Telegram
async def main():
    ok=await Telegram().send('JobHunt Telegram connection verified. Monitoring activation is a separate setup step.')
    print('Telegram verification succeeded.' if ok else 'Telegram verification failed. Check Actions secrets and start your bot chat.')
    return 0 if ok else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
