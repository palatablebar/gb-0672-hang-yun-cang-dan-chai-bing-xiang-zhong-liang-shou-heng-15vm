import hashlib,json
from app import corrections

def decide(state):
    ledger=state.setdefault('corrections',corrections.adjudicate(state))
    b=state['balance']
    blocked=(b['graph_errors']+b['weight_errors']+len(b['declaration_differences'])
             +len(state['hazard_issues'])+len(state['quarantine'])+len(ledger['rejected']))
    all_consistent=bool(ledger['roots']) and ledger['summary']['all_consistent']
    evidence={'roots':state['graph']['roots'],'weights':state['weight_checks'],'hazards':state['hazard_issues'],
              'corrections':[{'package_id':p['package_id'],'digest':p['digest']} for p in ledger['accepted']]}
    status='可封存' if b['row_balanced'] and all_consistent and not blocked else '待处理'
    return {'status':status,'blocked':blocked,'all_consistent':all_consistent,
            'seal':hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()}

def apply(state):
    state['corrections']=corrections.adjudicate(state)
    state['archive']=decide(state)
    state['views']['archive']={
        'title':'版本封存',
        'rows':[{'id':r['id'],'revision':r['revision'],'parent':r['parent']} for r in state['records']],
        'correction_rows':state['corrections']['roots'],
        'accepted_packages':state['corrections']['accepted'],
        'rejected_packages':state['corrections']['rejected'],
        'metrics':{'主单':len(state['graph']['roots']),'状态':state['archive']['status'],'阻断':state['archive']['blocked']}}
