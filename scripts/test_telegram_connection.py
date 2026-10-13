"""Validate Telegram secrets and send one confirmation; print only safe status labels."""
import asyncio, os
import httpx

def safe_error(response):
    if response.status_code in (401,404):
        return 'Telegram bot token rejected. Replace TELEGRAM_BOT_TOKEN with the full token from BotFather.'
    try:
        description=str(response.json().get('description','')).lower()
    except ValueError:
        description=''
    if 'chat not found' in description:
        return 'Telegram chat not found. Start your bot chat and verify TELEGRAM_CHAT_ID using the local helper.'
    if 'blocked' in description:
        return 'Telegram bot is blocked. Unblock it and press Start in your bot chat.'
    if 'deactivated' in description:
        return 'Telegram destination account is deactivated.'
    if response.status_code==429:
        return 'Telegram rate limit reached. Retry later.'
    if response.status_code==403:
        return 'Telegram destination does not permit this bot to send messages. Start your private bot chat or check group permissions.'
    return 'Telegram request failed with HTTP status '+str(response.status_code)+'. Check the Actions secrets.'

async def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    chat=os.getenv('TELEGRAM_CHAT_ID','').strip()
    if not token or not chat:
        print('Telegram verification failed: one or both secrets are empty.'); return 1
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response=await client.post('https://api.telegram.org/bot'+token+'/getMe')
            if response.status_code!=200 or not response.json().get('ok'):
                print(safe_error(response)); return 1
            print('Telegram bot token verified.')
            response=await client.post('https://api.telegram.org/bot'+token+'/sendMessage',json={'chat_id':chat,'text':'JobHunt Telegram connection verified. Monitoring activation is a separate setup step.'})
            if response.status_code!=200 or not response.json().get('ok'):
                print(safe_error(response)); return 1
            print('Telegram verification succeeded: confirmation delivered.'); return 0
    except Exception:
        # Raw HTTP errors may contain the credential-bearing URL.
        print('Telegram verification failed: connection or response error; no credentials logged.'); return 1
if __name__=='__main__': raise SystemExit(asyncio.run(main()))
