"""Binding gates only. Real host QA and human approval are intentionally unavailable."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import Invalid,validate,summary,cli,digest
from contracts import load_project,binding
from pathlib import Path

def implementation_digest():
    root=Path(__file__).resolve().parents[1]
    paths=sorted(list((root/'scripts').glob('*.py'))+list((root/'schemas').glob('*.json')))
    return digest({p.relative_to(root).as_posix():digest(p.read_bytes()) for p in paths})
from compare_source import inspect_pdf

def record(store,ref,expected):
    if ref is None: raise Invalid('EVIDENCE_REQUIRED')
    data=store.json(ref['path'],ref['sha256'])
    if not isinstance(data,dict) or any(data.get(k)!=v for k,v in expected.items()):raise Invalid('EVIDENCE_BINDING_MISMATCH')
    return data

def run(store,spec,command):
    validate(spec,'workflow.schema.json')
    project=store.json(spec['project']['path'],spec['project']['sha256'])
    src,tgt=load_project(store,project);inspect_pdf(store,project,src)
    key=binding(project);failures=[];counts={};extra={}
    if command=='snapshot':
        extra={'binding':key,'checker_sha256':implementation_digest()}
    elif command=='verify-snapshot':
        record(store,spec['record'],{'binding':key,'mechanical_status':'PASS','check':'workflow_snapshot'})
    elif command=='cache':
        old=record(store,spec['record'],{'binding':key,'mechanical_status':'PASS','check':'workflow_snapshot'})
        if old.get('checker_sha256')!=implementation_digest():failures.append('CHECKER_CHANGED')
        counts={'binding_reusable':not failures,'review_reusable':False}
    elif command=='coverage':
        event=record(store,spec['record'],{'binding':key})
        if event.get('mode')=='SYNTHETIC_TEST_ONLY' and not src['synthetic_test_only']:failures.append('SYNTHETIC_IN_PRODUCTION')
        if event.get('mode')!='SYNTHETIC_TEST_ONLY':failures.append('HOST_EVENT_UNTRUSTED')
        if not event.get('executor_id') or not event.get('qa_id') or event['executor_id']==event['qa_id']:failures.append('SAME_OR_MISSING_REVIEWER')
        if event.get('source_first') is not True:failures.append('SOURCE_FIRST_REQUIRED')
        reviewed=event.get('reviewed_ids',[]);ids=[u['id'] for u in src['units']]
        if len(set(reviewed))!=len(reviewed) or set(reviewed)!=set(ids):failures.append('REVIEW_COVERAGE_INCOMPLETE')
        if event.get('layers')!=project['layers']:failures.append('REVIEW_LAYERS_INCOMPLETE')
        counts={'records_checked':1,'real_reviews_verified':0}
    elif command=='route':
        findings=spec['findings'];pending=0;open_count=0
        if len({f['id'] for f in findings})!=len(findings):raise Invalid('DUPLICATE_FINDING_ID')
        for f in findings:
            if f['state']=='PENDING':pending+=1;continue
            if f['state']=='OPEN':open_count+=1;continue
            context=digest({'id':f['id'],'binding':key,'scope':f['scope'],'decision_required':f['decision_required']})
            proof=record(store,f['evidence'],{'binding':key,'context':context,'state':'RECHECKED'})
            if proof.get('mode')=='SYNTHETIC_TEST_ONLY' and not src['synthetic_test_only']:failures.append('SYNTHETIC_IN_PRODUCTION')
            if proof.get('mode')!='SYNTHETIC_TEST_ONLY':failures.append('RECHECK_AUTHORITY_UNVERIFIED')
            if f['decision_required']:
                decision=record(store,f['decision'],{'binding':key,'context':context,'decision':'APPROVE'})
                if decision.get('mode')!='SYNTHETIC_TEST_ONLY':failures.append('DECISION_AUTHORITY_UNVERIFIED')
        if pending:failures.append('UNFINISHED_WORK')
        if open_count:failures.append('REPAIR_OR_HUMAN_DECISION_REQUIRED')
        counts={'pending':pending,'open':open_count}
    elif command=='scope':
        impact=spec['impact']
        if not impact['changed_ids'] or not set(impact['changed_ids'])<={u['id'] for u in src['units']}:raise Invalid('CHANGE_IMPACT_MISSING')
        if impact['kind']=='global':counts={'units_to_recheck':len(src['units'])}
        else:counts={'units_to_recheck':len(set(impact['changed_ids']+impact['dependent_ids']))}
        if not set(impact['dependent_ids'])<={u['id'] for u in src['units']}:raise Invalid('DEPENDENT_UNIT_UNKNOWN')
    result=summary('workflow_'+command,failures,scope=project['scope'],**counts)
    result.update(extra)
    result['evidence_mode']='SYNTHETIC_TEST_ONLY' if src['synthetic_test_only'] else 'UNVERIFIED_DECLARATION'
    result['trusted_host_integration']='NOT_RUN'
    return result

if __name__=='__main__':raise SystemExit(cli(run,workflow=True))
