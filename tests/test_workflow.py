from pathlib import Path
import yaml

def test_workflow():
 w=yaml.safe_load((Path(__file__).resolve().parents[1]/'.github/workflows/job-hunter.yml').read_text())
 assert w['jobs']['scan']['runs-on']=='ubuntu-latest'
 assert w['concurrency']['cancel-in-progress'] is False
 assert 'private == false' in w['jobs']['scan']['if']
 assert 'bot-state' in str(w)
