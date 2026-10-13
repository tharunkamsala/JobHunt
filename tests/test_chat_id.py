from scripts import telegram_chat_id

def test_group_and_private_ids(monkeypatch,capsys):
    class Response:
        status_code=200
        def json(self):
            return {'result':[
                {'message':{'chat':{'id':123,'type':'private'}}},
                {'message':{'chat':{'id':-100456,'type':'supergroup','title':'Job Alerts'}}},
                {'my_chat_member':{'chat':{'id':-789,'type':'group','title':'Friends'}}},
            ]}
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def get(self,url): return Response()
    monkeypatch.setattr(telegram_chat_id,'getpass',lambda _: '123:secret-test-token')
    monkeypatch.setattr(telegram_chat_id.httpx,'Client',Client)
    assert telegram_chat_id.main()==0
    output=capsys.readouterr().out
    assert 'Group: Job Alerts | Chat ID: -100456' in output
    assert 'Group: Friends | Chat ID: -789' in output
    assert 'Private chat ID: 123' in output
    assert 'secret-test-token' not in output
