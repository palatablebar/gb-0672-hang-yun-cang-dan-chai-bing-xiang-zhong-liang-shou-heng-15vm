from importlib import import_module
from pathlib import Path
from copy import deepcopy
import json, time, base64
from app.config import ROOT, MODULES, MAX_BYTES
from app.errors import BusinessError
from app.manifest import digest, make_manifest
from app import corrections


def _payload_packages(payload):
    if 'corrections' in payload:
        return corrections.canonical_packages(payload.get('corrections'))
    if 'correction' in payload:
        return corrections.canonical_packages(payload.get('correction'))
    return []


def evaluate(payload=None, until=7, snapshot=None, packages=None):
    payload=payload or {}
    dataset=payload.get('dataset','dirty')
    if dataset not in {'dirty','clean','legacy'}: raise BusinessError('BAD_DATASET','样例名称无效')
    if not isinstance(payload.get('overrides',{}),dict): raise BusinessError('BAD_CONTEXT','参数须为对象')
    if snapshot is not None:
        raw=base64.b64decode(snapshot['bytes_b64'],validate=True)
        context=deepcopy(snapshot['context'])
        if packages is None:
            packages=deepcopy(snapshot.get('packages',[]))
        packages=corrections.canonical_packages(packages)
    else:
        raw=(str(payload['csv_text']).encode() if 'csv_text' in payload else (ROOT/'sample_data'/f'{dataset}.csv').read_bytes())
        context=json.loads((ROOT/'sample_data/context.json').read_text())
        context.update(deepcopy(payload.get('overrides',{})))
        packages=_payload_packages(payload) if packages is None else corrections.canonical_packages(packages)
    if len(raw)>MAX_BYTES: raise BusinessError('TOO_LARGE','文件超过2MB',413)
    packages=corrections.dedupe_packages(packages)
    start=time.perf_counter()
    base_context=deepcopy(context)
    state={'raw_bytes':raw,'context':context,'records':[],'quarantine':[], 'counts':{},'views':{},'source':dataset,
           'correction_packages':packages}
    for index,key in enumerate(MODULES,1):
        if index>until: break
        import_module(f'app.modules.{key}.rules').apply(state)
        if index==1:
            # 采信一结束就留档，之后无论补正成败都能追回原始证据。
            corrections.snapshot_intake(state)
            if packages:
                corrections.apply_packages(state,packages)
    state['input_snapshot']={'bytes_b64':base64.b64encode(raw).decode(),'context':base_context,'packages':deepcopy(packages)}
    state.pop('raw_bytes',None)
    state['manifest']=make_manifest(digest(raw,base_context,packages),dataset,time.perf_counter()-start)
    return state
