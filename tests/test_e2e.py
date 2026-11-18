from fastapi.testclient import TestClient
from app import main,store
from app.engine import evaluate
import pytest

def client(tmp_path,monkeypatch):
    monkeypatch.setattr(main,'DB_PATH',str(tmp_path/'test.sqlite'));return TestClient(main.app)
def test_api_idempotent(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);a=c.post('/api/runs',json={}).json();b=c.post('/api/runs',json={}).json();assert a['manifest']['run_id']==b['manifest']['run_id'];assert len(c.get('/api/runs').json())==1
def test_stale_review(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);a=c.post('/api/runs',json={}).json();url='/api/runs/'+a['manifest']['run_id']+'/review';assert c.post(url,json={'revision':1}).status_code==200;assert c.post(url,json={'revision':1}).status_code==409
def test_seven_entries(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    for k in main.MODULES:
        assert c.post('/api/'+k,json={}).status_code==200
        assert c.get('/'+k).status_code==200
def test_bad_dataset(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);assert c.post('/api/runs',json={'dataset':'../bad'}).status_code==422
def test_missing_run(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);assert c.get('/api/runs/none').status_code==404
def test_restart_store(tmp_path,sample):
    p=str(tmp_path/'durable.sqlite');store.save(p,sample);assert store.get(p,sample['manifest']['run_id'])['manifest']['sha256']==sample['manifest']['sha256']
def test_bad_revision(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch);s=c.post('/api/runs',json={}).json();assert c.post('/api/runs/'+s['manifest']['run_id']+'/review',json={'revision':0}).status_code==422

def test_clean_navigation_run_preserved(tmp_path,monkeypatch):
    c=client(tmp_path,monkeypatch)
    run=c.post('/api/runs',json={'dataset':'clean'}).json()
    rid=run['manifest']['run_id']
    for k in main.MODULES:
        html=c.get('/'+k+'?run_id='+rid).text
        assert '?run_id='+rid in html
        assert rid in html
    assert c.get('/api/export/'+rid).status_code==200

def test_custom_csv_snapshot_and_navigation(tmp_path,monkeypatch):
    from app.config import ROOT
    c=client(tmp_path,monkeypatch)
    original=(ROOT/'sample_data/clean.csv').read_text()
    # 改成独立于所有仓内样例的证据编号，追踪其跨页与重跑行为。
    first=original.splitlines()[1].split(',')[0]
    custom=original.replace(first,first+'-CUSTOM')
    result=c.post('/api/runs',json={'csv_text':custom}).json()
    rid=result['manifest']['run_id']
    assert '-CUSTOM' in str(result['records']) or '-CUSTOM' in str(result['quarantine'])
    for key in main.MODULES:
        response=c.get('/'+key+'?run_id='+rid)
        assert response.status_code==200
        assert '?run_id='+rid in response.text
    repeated=c.post('/api/runs/'+rid+'/rerun',json={})
    assert repeated.status_code==200
    assert repeated.json()['manifest']['run_id']==rid
    assert repeated.json()['manifest']['sha256']==result['manifest']['sha256']


def test_correction_endpoint_merges_and_stores(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    run=c.post('/api/runs',json={'dataset':'clean'}).json();rid=run['manifest']['run_id']
    body={'package_id':'W1','rows':[{'id':'M001-P1-1','revision':'2','gross':'0.12'},
                                    {'id':'M001-P1','revision':'2','gross':'230'},
                                    {'id':'M001','revision':'2','gross':'450'}],
          'declaration':{'pieces':240,'net_kg':'2400','gross_kg':'2650'}}
    first=c.post('/api/runs/'+rid+'/corrections',json=body).json()
    assert first['correction_outcome']['applied'] is True
    new_id=first['manifest']['run_id'];assert new_id!=rid
    again=c.post('/api/runs/'+new_id+'/corrections',json=body).json()
    assert again['correction_outcome']['duplicate'] is True
    assert again['manifest']['run_id']==new_id
    stored=c.get('/api/runs/'+new_id).json()
    assert stored['corrections']['roots'][0]['source']=='W1'
    assert c.get('/archive?run_id='+new_id).status_code==200
    assert c.get('/api/export/'+new_id+'?sealed=1').status_code==200


def test_rejected_correction_restores_previous_run(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    run=c.post('/api/runs',json={'dataset':'clean'}).json();rid=run['manifest']['run_id']
    body={'package_id':'W1','rows':[{'id':'M001','revision':'4','gross':'442'}]}
    response=c.post('/api/runs/'+rid+'/corrections',json=body)
    assert response.status_code==200
    data=response.json()
    assert data['correction_outcome']['restored'] is True
    assert data['manifest']['run_id']==rid
    assert data['correction_outcome']['rejected'][0]['code']=='REVISION_GAP'
    assert len(c.get('/api/runs').json())==1


def test_sealed_export_refused_when_blocked(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    run=c.post('/api/runs',json={'dataset':'clean'}).json();rid=run['manifest']['run_id']
    body={'package_id':'W1','rows':[{'id':'M001','revision':'2','gross':'442'}]}
    blocked=c.post('/api/runs/'+rid+'/corrections',json=body).json()
    assert c.get('/api/export/'+blocked['manifest']['run_id']+'?sealed=1').status_code==409
    assert c.get('/api/export/'+blocked['manifest']['run_id']).status_code==200


def test_correction_demo_endpoint(tmp_path, monkeypatch):
    c=client(tmp_path,monkeypatch)
    body={'dataset':'clean','corrections':[{'package_id':'B1','rows':[{'id':'M001','revision':'2','container':'C9'}]}]}
    data=c.post('/api/corrections',json=body).json()
    assert data['corrections']['summary']['packages']==1
    assert data['corrections']['roots'][0]['consistent'] is True
