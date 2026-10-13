"""Read private chat IDs using the official API, without printing the bot token."""
from getpass import getpass
import sys
import httpx

def main():
    token=getpass('BotFather token (hidden; never stored): ').strip()
    if not token or ':' not in token:
        print('A valid BotFather token is required.'); return 1
    try:
        with httpx.Client(timeout=30) as client:
            response=client.get('https://api.telegram.org/bot'+token+'/getUpdates')
        if response.status_code!=200:
            print('Telegram could not read updates. Check the token and whether this bot uses a webhook.'); return 1
        data=response.json()
        ids=set()
        for update in data.get('result',[]):
            chat=(update.get('message') or {}).get('chat',{})
            if chat.get('type')=='private' and chat.get('id'): ids.add(chat['id'])
        if not ids:
            print('Open your bot in Telegram, press Start, send hello, then run this helper again.'); return 1
        for chat_id in sorted(ids): print('Private chat ID:',chat_id)
        print('Save your ID as TELEGRAM_CHAT_ID in JobHunt repository Actions secrets.')
        if len(ids)>1: print('Multiple chats found: use the ID of your own conversation.')
        return 0
    except Exception:
        # Do not print HTTP exceptions: request URLs contain the secret token.
        print('Could not reach Telegram. Check your connection and retry.'); return 1
if __name__=='__main__': sys.exit(main())
