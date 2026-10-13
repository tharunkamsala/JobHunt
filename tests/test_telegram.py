from models import Job
from storage.database import Store
from notifications.telegram import format_job, Telegram

def test_format(tmp_path):
 j=Job('A','1','Software Engineer','United States','https://example.com/jobs/1','description')
 rec,_,_=Store(tmp_path/'s.json').observe(j)
 message=format_job(rec)
 assert j.url in message and 'Unspecified' in message and 'Discovered:' in message

async def test_missing_credentials(monkeypatch):
 monkeypatch.delenv('TELEGRAM_BOT_TOKEN',raising=False)
 assert await Telegram().send('test') is False
