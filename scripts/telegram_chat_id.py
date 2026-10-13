"""Read private and group chat IDs without printing the bot token."""
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
        chats={}
        for update in data.get('result',[]):
            event=update.get('message') or update.get('my_chat_member') or {}
            chat=event.get('chat',{})
            if chat.get('type') in ('private','group','supergroup') and chat.get('id'):
                chats[chat['id']]=chat
        if not chats:
            print('Press Start in your private bot chat, or add the bot to your group and send /start@YourBotUsername there, then retry.'); return 1
        for chat_id,chat in sorted(chats.items()):
            if chat['type']=='private': print('Private chat ID:',chat_id)
            else: print('Group:',chat.get('title','Unnamed group'),'| Chat ID:',chat_id)
        print('Save the destination ID as TELEGRAM_CHAT_ID in JobHunt repository Actions secrets.')
        if len(chats)>1: print('Multiple chats found: choose the intended private chat or group.')
        return 0
    except Exception:
        # Do not print HTTP exceptions: request URLs contain the secret token.
        print('Could not reach Telegram. Check your connection and retry.'); return 1
if __name__=='__main__': sys.exit(main())
