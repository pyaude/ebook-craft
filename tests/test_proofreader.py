import copy
import threading
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from app import proofreader as pr


def fixture_book():
    return dict(id='test',status='ready',title='测试',pages=[dict(number=1,blocks=[
        dict(kind='paragraph',text='我们认真思老问题，也要检杳原文。版本是2024。',lines=[{'text':'原始识别'}]),
        dict(kind='grid',text='作者甲\t作者乙')])])


def changes(book):
    return pr.validate_changes(book['pages'][0],[
        dict(block=0,before='认真思老问题',after='认真思考问题',reason='语境中应为思考'),
        dict(block=0,before='检杳原文',after='检查原文',reason='形近字')],{0})


def test_chunking_keeps_context_and_skips_grid():
    book=fixture_book();book['pages'][0]['blocks'][0]['text']='甲'*2501
    book['pages'].append(dict(number=2,blocks=[dict(kind='paragraph',text='后页语境')]))
    batches=list(pr.batches(book,1))
    assert ''.join(p['text'] for b in batches for p in b['paragraphs'])=='甲'*2501
    assert batches[0]['next_page_context']=='后页语境'
    assert batches[1]['preceding_context']=='甲'*250
    assert all(p['block']==0 for b in batches for p in b['paragraphs'])


def test_validation_rejects_invention_digits_rewriting_and_grid():
    book=fixture_book();page=book['pages'][0]
    bad=[dict(block=i,before=b,after=a,reason='依据') for i,b,a in [
        (0,'不存在','新内容'),(0,'2024','2025'),(1,'作者甲','作者丙'),
        (99,'原文','正文'),(0,'我们认真思老问题','完全不同的大段新观点'),(True,'原文','正文')]]
    assert not pr.validate_changes(page,bad,{0,1,99})
    page['blocks'][0]['text']='原文原文'
    assert not pr.validate_changes(page,[dict(block=0,before='原文',after='正文',reason='')],{0})


def test_apply_rebases_and_preserves_source():
    book=fixture_book();items=changes(book);run=dict(id='r',suggestions=items)
    assert pr.apply_suggestions(book,run,[items[0]])==1
    assert pr.apply_suggestions(book,run,[items[1]])==1
    block=book['pages'][0]['blocks'][0]
    assert '认真思考' in block['text'] and '检查原文' in block['text']
    assert block['lines']==[{'text':'原始识别'}]
    assert len(block['proofread_history'])==2 and book['revision']==2


def test_conflicts_are_atomic():
    book=fixture_book();items=changes(book);run=dict(id='r',suggestions=items)
    duplicate=copy.deepcopy(items[0]);duplicate['id']='overlap';items.append(duplicate)
    before=copy.deepcopy(book)
    with pytest.raises(ValueError):pr.apply_suggestions(book,run,items)
    assert book==before
    items.pop();book['pages'][0]['blocks'][0]['text']+='编辑'
    with pytest.raises(ValueError):pr.apply_suggestions(book,run,items)
    assert pr.apply_suggestions(book,run,items,False)==0
    assert all(s['status']=='stale' for s in items)


@pytest.fixture
def client(monkeypatch):
    book=fixture_book();jobs={'test':book};queued=[]
    class Pool:
        def submit(self,*args):queued.append(args)
    monkeypatch.setattr(pr,'POOL',Pool())
    monkeypatch.setattr(pr,'ollama',lambda path,*args,**kw: {'models':[{'name':'local'},{'name':'bad-cloud'}]} if path=='/api/tags' else {})
    monkeypatch.setattr(pr,'generate',lambda model,batch:[dict(block=0,before='认真思老问题',after='认真思考问题',reason='语义')])
    app=FastAPI();pr.register_proofreading(app,jobs,threading.RLock(),lambda j:None)
    return TestClient(app),book,queued


def test_worker_auto_apply_undo_and_manual_edit_conflict(client):
    api,book,queue=client
    response=api.post('/api/jobs/test/proofreading',json={'model':'local','auto_apply':True})
    assert response.status_code==202
    runid=response.json()['id'];fn,*args=queue.pop();fn(*args)
    assert book['proofreading']['status']=='ready'
    assert '认真思考' in book['pages'][0]['blocks'][0]['text']
    block=book['pages'][0]['blocks'][0];block['text']+='人工编辑'
    assert api.post('/api/jobs/test/proofreading/undo',json={'run_id':runid}).status_code==409
    block['text']=block['text'].removesuffix('人工编辑')
    assert api.post('/api/jobs/test/proofreading/undo',json={'run_id':runid}).json()['restored_blocks']==1
    assert '认真思老' in block['text']


def test_cancelled_queued_run_cannot_replace_new_run(client):
    api,book,queue=client
    run=api.post('/api/jobs/test/proofreading',json={'model':'local'}).json()
    api.post('/api/jobs/test/proofreading/cancel',json={'run_id':run['id']})
    new=api.post('/api/jobs/test/proofreading',json={'model':'local'}).json()
    fn,*args=queue.pop(0);fn(*args)
    assert book['proofreading']['id']==new['id'] and book['proofreading']['status']=='queued'
    fn,*args=queue.pop();fn(*args)
    assert book['proofreading']['status']=='ready'
    assert '认真思老' in book['pages'][0]['blocks'][0]['text']


def test_unavailable_cloud_models_and_inference_error(client,monkeypatch):
    api,book,queue=client
    assert api.post('/api/jobs/test/proofreading',json={'model':'bad-cloud'}).status_code==400
    monkeypatch.setattr(pr,'ollama',lambda path,*args,**kw: {'models':[{'name':'local'}]} if path=='/api/tags' else {'remote_model':'cloud'})
    assert api.post('/api/jobs/test/proofreading',json={'model':'local'}).status_code==400
    def fail(*args,**kwargs):raise ValueError('离线')
    monkeypatch.setattr(pr,'ollama',fail)
    assert not api.get('/api/proofreading/models').json()['available']
    assert api.post('/api/jobs/test/proofreading',json={'model':'local'}).status_code==400
    assert 'proofreading' not in book


def test_remote_endpoint_rejected(monkeypatch):
    monkeypatch.setenv('OLLAMA_URL','https://example.com')
    with pytest.raises(ValueError,match='本机'):pr.ollama('/api/tags')
