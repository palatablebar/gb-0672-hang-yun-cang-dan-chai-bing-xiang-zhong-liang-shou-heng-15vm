from contextlib import asynccontextmanager
from importlib import import_module
from fastapi import FastAPI, Request, Body
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from app.config import ROOT, META, MODULES, DB_PATH
from app.errors import BusinessError
from app.engine import evaluate
from app import store, corrections
from app.archive import serialize

@asynccontextmanager
async def lifespan(app):
    store.save(DB_PATH,evaluate())
    yield
app=FastAPI(title=META['title'],lifespan=lifespan)
app.mount('/static',StaticFiles(directory=str(ROOT/'app/static')),name='static')

@app.exception_handler(BusinessError)
async def business_error(request:Request,error:BusinessError):
    return JSONResponse({'code':error.code,'detail':error.message},status_code=error.status)

def _outcome(applied, duplicate, run_id, restored_run_id, rejected):
    return {'applied':applied,'duplicate':duplicate,'restored':not applied and not duplicate,
            'run_id':run_id,'restored_run_id':restored_run_id,'rejected':rejected}

@app.get('/')
def home():
    return RedirectResponse('/'+MODULES[0],status_code=303)
@app.get('/healthz')
def health():
    return {'status':'ok','project':META['short']}
@app.post('/api/runs')
def create(payload:dict=Body(default={})):
    return store.save(DB_PATH,evaluate(payload))
@app.post('/api/runs/{run_id}/rerun')
def rerun(run_id:str):
    previous=store.get(DB_PATH,run_id)
    if 'input_snapshot' not in previous:
        raise BusinessError('INPUT_SNAPSHOT_MISSING','旧批缺少源快照，请重新导入')
    return store.save(DB_PATH,evaluate({'dataset':previous['source']},snapshot=previous['input_snapshot']))
@app.post('/api/runs/{run_id}/corrections')
def apply_correction(run_id:str,payload:dict=Body(...)):
    """把补正包并入已有批次。

    合并成功才切换到新批次；补正包被整包退回时不写入候选结果，
    直接返回旧版结果，因此页面不会被半成品覆盖。完全相同的补正包
    重试复用已生成批次，不重复生成结果。
    """
    previous=store.get(DB_PATH,run_id)
    snapshot=previous.get('input_snapshot')
    if snapshot is None:
        raise BusinessError('INPUT_SNAPSHOT_MISSING','旧批缺少源快照，请重新导入')
    incoming=corrections.canonical_packages(corrections.packages_from_payload(payload))
    existing=list(snapshot.get('packages') or [])
    combined=corrections.dedupe_packages(existing+incoming)
    if combined==existing:
        return {**previous,'correction_outcome':_outcome(True,True,run_id,run_id,[])}
    candidate=evaluate({'dataset':previous['source']},snapshot=snapshot,packages=combined)
    prior_rejections=list((previous.get('corrections') or {}).get('rejected') or [])
    new_rejections=[item for item in (candidate.get('corrections') or {}).get('rejected',[])
                    if item not in prior_rejections]
    if new_rejections:
        # 整包退回：候选结果不落库，旧版结果继续作为当前结果。
        return {**previous,'correction_outcome':_outcome(False,False,candidate['manifest']['run_id'],run_id,new_rejections)}
    saved=store.save(DB_PATH,candidate)
    return {**saved,'correction_outcome':_outcome(True,False,saved['manifest']['run_id'],saved['manifest']['run_id'],[])}
@app.post('/api/corrections')
def corrections_demo(payload:dict=Body(default={})):
    """独立演示入口：以样例或粘贴文件为底，叠加补正包后返回裁量结果。"""
    return evaluate(payload)
@app.get('/api/runs')
def runs():
    return store.history(DB_PATH)
@app.get('/api/runs/{run_id}')
def run(run_id:str):
    return store.get(DB_PATH,run_id)
@app.post('/api/runs/{run_id}/review')
def review(run_id:str,payload:dict=Body(...)):
    revision=payload.get('revision')
    if not isinstance(revision,int) or revision<1: raise BusinessError('BAD_REVISION','版本号须为正整数')
    return store.review(DB_PATH,run_id,revision)
@app.get('/api/export/{run_id}')
def export(run_id:str,sealed:int=0):
    result=store.get(DB_PATH,run_id)
    if sealed and (result.get('archive') or {}).get('status')!='可封存':
        raise BusinessError('NOT_SEALED','当前主单尚不一致，不能形成封存件',409)
    return Response(serialize(result),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{run_id}.zip"'})
for key in MODULES:
    app.include_router(import_module(f'app.modules.{key}.handler').router)
