import pytest, app
from fastapi.testclient import TestClient
@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(app,'DB',str(tmp_path/'test.db'));monkeypatch.setenv('INVENTORY_API_KEY','test-secret')
    return TestClient(app.app)
P={'sku':'KEY-01','name':'Keyboard','quantity':10,'price_cents':2500}
H={'X-API-Key':'test-secret'}
def test_health(client):assert client.get('/health').json()=={'status':'ok'}
def test_auth(client):assert client.post('/products',json=P).status_code==401
def test_roundtrip(client):
    r=client.post('/products',json=P,headers=H);assert r.status_code==201
    assert client.get('/products/1').json()['sku']=='KEY-01'
    assert client.get('/summary').json()['value_cents']==25000
def test_duplicate(client):
    client.post('/products',json=P,headers=H);assert client.post('/products',json=P,headers=H).status_code==409
def test_validation(client):
    for field,value in [('quantity',-1),('quantity',1.5),('name',' '),('price_cents',-1)]:
        assert client.post('/products',json={**P,field:value},headers=H).status_code==422
def test_atomic_movement(client):
    client.post('/products',json=P,headers=H)
    assert client.post('/products/1/movements',json={'delta':-11},headers=H).status_code==409
    assert client.get('/products/1').json()['quantity']==10
    assert client.get('/movements').json()['items']==[]
    assert client.post('/products/1/movements',json={'delta':-3},headers=H).json()['quantity']==7
    assert len(client.get('/movements').json()['items'])==1
def test_paging_and_search(client):
    client.post('/products',json=P,headers=H)
    assert client.get('/products?q=KEY&limit=1').json()['total']==1
    assert client.get('/products?q=%27%20OR%201=1--').json()['total']==0
    assert client.get('/products?limit=0').status_code==422
    assert client.get('/products?offset=1').json()['items']==[]
def test_missing(client):assert client.get('/products/999').status_code==404
def test_zero_movement(client):
    assert client.post('/products/1/movements',json={'delta':0},headers=H).status_code==422
def test_fail_closed(client,monkeypatch):
    monkeypatch.delenv('INVENTORY_API_KEY');assert client.post('/products',json=P,headers=H).status_code==503
