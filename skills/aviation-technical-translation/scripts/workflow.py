"""Deterministic workflow gates; never performs or simulates semantic/visual review.

Use COMMAND --spec input.json --output NEW-report.json. Exit 0/1/2 = gate
PASS / incomplete-or-failed / invalid. Source and production files are read-only.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from collections import Counter
from common import load_json, sha256_file, schema_validation_errors, atomic_write_json

VERSION='1.2.2-rc7'
DEPENDENCIES={'source','target','assets','style','checker','render_environment'}
LAYERS={'ordinary','table_cells','formulas','captions','image_semantics','footnotes',
        'references','front_back_matter','branding_fields'}
DECISION_FLAGS=('semantic_uncertainty','source_editorial_change','approved_term_change','new_permission')

def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def hashes_valid(deps):
    return isinstance(deps,dict) and set(deps)==DEPENDENCIES and all(isinstance(x,str) and len(x)==64 and all(c in '0123456789abcdef' for c in x) for x in deps.values())

def evidence_valid(items):
    return isinstance(items,list) and bool(items) and all(isinstance(e,dict) and isinstance(e.get('path'),str) and
       Path(e['path']).is_file() and sha256_file(Path(e['path']))==e.get('sha256') for e in items)

def bound_record(ref, expected):
    """Check declared provenance and exact binding, not human identity/authentication.

    Actual dispatch/decisions must come from recorded tools/user input. This helper
    cannot grant permissions, prove an agent exists, or turn model text into approval.
    """
    if not evidence_valid([ref]): return False
    try: row=load_json(Path(ref['path']))
    except (OSError,ValueError): return False
    return isinstance(row,dict) and all(row.get(k)==v for k,v in expected.items())

def finding_binding(f):
    return digest({k:f.get(k) for k in ('id','scope','source_context','authorized_goal','snapshot_id','target_sha256') } |
        {'source_evidence_hashes':sorted(e['sha256'] for e in f.get('source_evidence',[]))})

def decision_satisfied(f, key):
    ref=f.get('decision_records',{}).get(key)
    if not isinstance(ref,dict): return False
    if key=='new_permission':
        if f.get('permission_granted') is not True: return False
        authority='PLATFORM_TOOL_PERMISSION';status='GRANTED'
    else:
        if f.get('human_decision_approved') is not True: return False
        authority='CURRENT_USER_EXPLICIT_DECISION';status='HUMAN_APPROVED'
    return bound_record(ref,{'finding_id':f['id'],'context_sha256':finding_binding(f),
        'decision_flag':key,'authority':authority,'status':status})

def result(ok,**kw):
    return {'workflow_version':VERSION,'status':'PASS' if ok else 'FAIL',**kw,
            'formal_publication_acceptance':'NOT_ASSESSED_BY_THIS_COMMAND'}

def snapshot(spec):
    if not hashes_valid(spec.get('dependencies')): raise ValueError('Missing/invalid dependency fingerprints')
    arts=spec.get('artifacts',[])
    if not arts or len({a['id'] for a in arts})!=len(arts): raise ValueError('Missing/duplicate artifact IDs')
    out=[]
    for a in arts:
        p=Path(a['path']).resolve(strict=True)
        if not p.is_file(): raise ValueError(f'Not a file: {p}')
        h=sha256_file(p)
        if a.get('expected_sha256',h)!=h: raise ValueError(f'ARTIFACT_HASH_DRIFT:{a["id"]}')
        out.append({'id':a['id'],'role':a['role'],'path':str(p),'size':p.stat().st_size,'sha256':h})
    identity=digest({'artifacts':sorted([{k:a[k] for k in ('id','role','size','sha256')} for a in out],key=lambda x:x['id']),'dependencies':spec['dependencies']})
    return result(True,artifacts=out,dependencies=spec['dependencies'],snapshot_id=identity)

def verify_snapshot(spec):
    got=snapshot({'artifacts':[dict(a,expected_sha256=a['sha256']) for a in spec['artifacts']], 'dependencies':spec['dependencies']})
    return result(got['snapshot_id']==spec['snapshot_id'],snapshot_id=got['snapshot_id'],input_snapshot_id=spec['snapshot_id'])

def route(spec):
    findings=spec.get('findings',[])
    if len({f['id'] for f in findings})!=len(findings): raise ValueError('Duplicate finding IDs')
    pending=[];repairs=[];manual=[];diagnosis=[];closed=[]
    for f in findings:
        if f['status']=='PENDING': pending.append(f['id']);continue
        if f['status'] not in ('OPEN','RESOLVED'): raise ValueError('Unknown finding status')
        for key in DECISION_FLAGS:
            if not isinstance(f.get(key),bool): raise ValueError(f'Missing decision flag {key}: {f["id"]}')
        required=[key for key in DECISION_FLAGS if f[key] and not decision_satisfied(f,key)]
        if required or not evidence_valid(f.get('source_evidence')):
            manual.append({**f,'route':'HUMAN_DECISION_OR_MISSING_SOURCE_EVIDENCE','unmet_decisions':required});continue
        if not f.get('authorized_goal') or not f.get('root_cause') or not f.get('scope'):
            raise ValueError('Repair needs authorized goal/root cause/scope: '+f['id'])
        if f['status']=='RESOLVED':
            if f.get('recheck_pass') is not True or not bound_record(f.get('recheck_record'),
                {'finding_id':f['id'],'context_sha256':finding_binding(f),'status':'PASS',
                 'target_sha256':f.get('target_sha256')}) or not isinstance(f.get('target_sha256'),str) or len(f['target_sha256'])!=64:
                raise ValueError('Resolution without bound target recheck evidence: '+f['id'])
            closed.append(f['id']);continue
        history=f.get('repair_history',[])
        if len(history)>=2 and all(h.get('outcome')=='FAIL' for h in history[-2:]) and history[-1].get('failure_fingerprint') and history[-1]['failure_fingerprint']==history[-2].get('failure_fingerprint') and not any(h.get('substantive_progress') is True for h in history[-2:]):
            diagnosis.append({**f,'route':'ROOT_CAUSE_DIAGNOSIS_REQUIRED'});continue
        repairs.append({**f,'route':'EXECUTOR_REPAIR_THEN_INDEPENDENT_RECHECK'})
    return result(not(manual or diagnosis or repairs),pending_translation_objects=len(pending),pending_ids=pending,
      auto_repair_backlog=repairs,manual_handoff=manual,diagnosis_required=diagnosis,resolved_ids=closed,
      ordinary_qa_dispatch_permitted=True,extra_advanced_review_dispatched=False,
      acceptance_blocked=bool(manual or diagnosis or repairs or pending),
      note='PASS here only means no unresolved findings; pending workload still blocks completion.')

def cache(spec):
    old=spec['record'];current=spec['current'];reasons=[]
    if old.get('status')!='PASS' or old.get('complete') is not True:reasons.append('NOT_COMPLETE_PASS')
    for obj in (old,current):
        if not hashes_valid(obj.get('dependencies')):reasons.append('INCOMPLETE_DEPENDENCIES')
    if old.get('dependencies')!=current.get('dependencies'):reasons.append('DEPENDENCY_CHANGED')
    if not old.get('scope_ids') or len(set(old['scope_ids']))!=len(old['scope_ids']) or set(old['scope_ids'])!=set(current.get('scope_ids',[])):reasons.append('SCOPE_CHANGED_OR_EMPTY')
    if not evidence_valid(old.get('evidence')):reasons.append('EVIDENCE_MISSING_OR_CHANGED')
    if old.get('kind')!=current.get('kind'):reasons.append('CHECK_KIND_CHANGED')
    if old.get('revoked') is True:reasons.append('REVIEW_REVOKED')
    # Equal pixels cannot repair a wrong or insufficient original review.
    # The contract describes observed aspects, never observations made by this tool.
    if current.get('kind')=='visual_page':
        if current.get('actual_render_comparison_pass') is not True or not evidence_valid(current.get('comparison_evidence')):reasons.append('NO_CURRENT_RENDER_COMPARISON')
        prior=old.get('review_contract',{});required=current.get('review_contract',{})
        for contract in (prior,required):
            if not isinstance(contract,dict):raise ValueError('Invalid visual review contract')
            aspects=contract.get('aspects',[])
            if not isinstance(aspects,list) or any(not isinstance(x,str) or not x.strip() for x in aspects) or len(aspects)!=len(set(aspects)):
                raise ValueError('Invalid review aspects')
            if not evidence_valid([contract.get('criteria',{})]):
                reasons.append('REVIEW_CRITERIA_MISSING_OR_CHANGED')
        prior_criteria=prior.get('criteria',{})
        required_criteria=required.get('criteria',{})
        if not isinstance(prior_criteria,dict) or not isinstance(required_criteria,dict):
            raise ValueError('Invalid visual review criteria reference')
        if prior_criteria.get('sha256')!=required_criteria.get('sha256'):
            reasons.append('REVIEW_CRITERIA_CHANGED')
        covered=prior.get('aspects',[]);needed=required.get('aspects',[])
        if not covered or not needed or not set(needed)<=set(covered):
            reasons.append('REVIEW_ASPECTS_NOT_COVERED')
        if prior.get('method')!='READABLE_PAGES_AND_DETAIL':
            reasons.append('READABLE_PAGE_OBSERVATION_MISSING')
        if 'source_style' in needed and prior.get('source_compared') is not True:
            reasons.append('SOURCE_STYLE_NOT_COMPARED')
        invalidated=current.get('invalidated_aspects',[])
        if not isinstance(invalidated,list) or any(not isinstance(x,str) for x in invalidated):
            raise ValueError('Invalid invalidated aspects')
        if set(invalidated) & set(needed):
            reasons.append('REVIEW_INVALIDATED_BY_FINDING')
        # Whole-artifact hashes bind comparison; scoped dependencies may remain
        # identical when another page changes. The comparison producer must use
        # actual saved/rendered bytes, not authoring intent or normalized text.
        for obj in (old,current):
            h=obj.get('artifact_sha256')
            if not isinstance(h,str) or len(h)!=64 or any(c not in '0123456789abcdef' for c in h):
                reasons.append('VISUAL_ARTIFACT_IDENTITY_MISSING')
        if not bound_record(current.get('comparison_record'),{
            'baseline_target_sha256':old.get('artifact_sha256'),
            'candidate_target_sha256':current.get('artifact_sha256'),
            'scope_ids':current.get('scope_ids'),
            'dimensions_equal':True,'raw_text_equal':True,'decoded_pixels_equal':True}):
            reasons.append('RENDER_COMPARISON_BINDING_FAIL')
    return result(not reasons,reusable=not reasons,invalidation_reasons=sorted(set(reasons)))

def plan(spec):
    """Small route selector; output is a work plan, never translation acceptance."""
    mode=spec.get('task')
    if mode not in ('excerpt','translate','repair','qa','resume'):
        raise ValueError('Unknown task')
    if mode=='excerpt':
        return result(True,references=['translation_policy.md'],
            word_required=False,independent_qa_required=False,phase='TEXT_ONLY',
            completed=False,next_action='TRANSLATE_SUPPLIED_CONTEXT')
    fmt=spec.get('output_format');kind=spec.get('document_kind')
    if fmt not in ('pdf','docx','text') or kind not in ('paper','manual','other'):
        raise ValueError('Document kind and output format are required')
    refs=['intake_workflow.md','translation_policy.md','dual_agent_workflow.md']
    if mode=='resume':refs=['intake_workflow.md']
    checks=[]
    next_action='VERIFY_CURRENT_ARTIFACTS' if mode=='resume' else 'VERIFY_REPRESENTATIVE_SAMPLE'
    if fmt=='pdf':
        refs+=['pdf_workflow.md','presentation_review.md','typography_and_headless_qa.md','qa_policy.md']
        if mode=='translate':
            next_action='INSPECT_SOURCE_PAGE_LAYOUT'
            checks+=['inspect_source_page_layout','compare_rendered_pilot_to_source_layout']
            checks.append('calibrate_body_leading_and_object_gaps_on_pilot')
        checks.extend(['compare_final_render_to_source_layout','review_rendered_body_leading_and_object_gaps'])
    elif fmt=='docx':
        refs+=['publication_workflow.md','docx_layout_policy.md','qa_policy.md']
        checks=['docx_preflight_before_word','docx_preflight_after_save','review_rendered_body_leading_and_object_gaps']
    if fmt in ('pdf','docx'):
        refs+=['typography_and_headless_qa.md']
        checks+=['verify_requested_type_on_render','review_context_terms_and_figure_labels']
        if kind=='manual':
            refs+=['long_translation.md']
            checks+=['verify_ordered_batches_and_boundary_context']
    if mode=='qa':refs+=['qa_policy.md','evidence_contract.md']
    return result(True,references=list(dict.fromkeys(refs)),word_required=fmt=='docx',
        independent_qa_required=True,phase='CURRENT_STATE_FIRST' if mode=='resume' else 'INTAKE_OR_DELTA',
        required_checks=checks,executor_model='gpt-6.2-sol',executor_effort='high',
        qa_model='gpt-6.2-sol',qa_default_effort='medium',qa_high_scope='DIFFICULT_OBJECTS_ONLY',computer_use=False, native_clipboard='NOT_TESTED',
        completed=False,layout_basis='SOURCE_WITH_SCOPED_OVERRIDES',
        next_action=next_action)

def coverage(spec):
    failures=[];source=spec.get('source_inventory',[]);built=spec.get('executor_inventory',[]);reviews=spec.get('reviews',[])
    snap=spec.get('snapshot',{});sid=snap.get('snapshot_id');arts={}
    try:
        if verify_snapshot(snap)['status']!='PASS': failures.append('SNAPSHOT_ID_DRIFT')
        arts={a['id']:a for a in snap['artifacts']}
    except (KeyError,TypeError,ValueError,OSError): failures.append('LIVE_SNAPSHOT_MISSING_OR_CHANGED')
    if not sid or spec.get('snapshot_id')!=sid or spec.get('source_inventory_snapshot_id')!=sid:
        failures.append('SOURCE_INVENTORY_SNAPSHOT_BINDING_FAIL')
    for name,rows in [('source',source),('executor',built),('reviews',reviews)]:
        if len({r['id'] for r in rows})!=len(rows):failures.append('DUPLICATE_'+name.upper()+'_ID')
    a,b={x['id'] for x in source},{x['id'] for x in built}
    if a-b:failures.append('SOURCE_UNITS_NOT_PROJECTED')
    if b-a:failures.append('EXECUTOR_UNITS_WITHOUT_SOURCE')
    if spec.get('source_inventory_basis')!='INDEPENDENT_ORIGINAL_SOURCE':failures.append('NOT_INDEPENDENT_SOURCE_INVENTORY')
    if not spec.get('qa_thread_id') or not spec.get('executor_thread_id') or spec['qa_thread_id']==spec['executor_thread_id']:failures.append('INDEPENDENCE_NOT_ESTABLISHED')
    if not evidence_valid(spec.get('dispatch_evidence')):failures.append('DISPATCH_EVIDENCE_MISSING')
    if not bound_record(spec.get('dispatch_record'),{'executor_thread_id':spec.get('executor_thread_id'),
        'qa_thread_id':spec.get('qa_thread_id'),'snapshot_id':sid,'source_first':True}):
        failures.append('DISPATCH_SNAPSHOT_BINDING_FAIL')
    if not evidence_valid(spec.get('source_inspection_evidence')):failures.append('SOURCE_INSPECTION_EVIDENCE_MISSING')
    reviewed_layers=spec.get('layer_review',{})
    if set(reviewed_layers)!=LAYERS or not all(x.get('inspected') is True and x.get('rationale') for x in reviewed_layers.values()):failures.append('CONTENT_LAYER_COVERAGE_INCOMPLETE')
    pages=spec.get('source_pages',[])
    if not pages or len(set(pages))!=len(pages) or set(pages)!=set(spec.get('source_pages_inspected',[])):failures.append('SOURCE_PAGE_COVERAGE_INCOMPLETE')
    if spec.get('coverage_scope')=='full_document' and set(pages)!=set(range(1,spec.get('source_page_count',0)+1)):failures.append('FALSE_FULL_SOURCE_PAGE_COVERAGE')
    rv={r['id']:r for r in reviews}
    bv={r['id']:r for r in built}
    for s in source:
        r=rv.get(s['id'],{})
        target=bv.get(s['id'],{});art=arts.get(target.get('target_artifact_id'),{})
        if not art or art.get('role')!='target' or target.get('target_sha256')!=art.get('sha256'):
            failures.append('TARGET_ARTIFACT_BINDING_FAIL:'+s['id'])
        if r.get('snapshot_id')!=sid or r.get('target_sha256')!=art.get('sha256') or r.get('qa_thread_id')!=spec.get('qa_thread_id'):
            failures.append('REVIEW_SNAPSHOT_TARGET_BINDING_FAIL:'+s['id'])
        if 'reuse' in r and (cache(r['reuse'])['status']!='PASS' or r['reuse']['current'].get('dependencies')!=snap.get('dependencies') or r['reuse']['current'].get('scope_ids')!=[s['id']]):
            failures.append('REUSE_NOT_APPLICABLE:'+s['id'])
        if r.get('status')!='PASS' or not r.get('rationale') or not evidence_valid(r.get('evidence')):failures.append('UNREVIEWED_OR_FAILED:'+s['id'])
        if s.get('layer') not in LAYERS or not set(s.get('pages',[]))<=set(pages) or not s.get('pages'):failures.append('INVALID_SOURCE_LOCATOR:'+s['id'])
    if set(rv)-a:failures.append('REVIEW_WITHOUT_SOURCE_UNIT')
    # A figure/table/footnote may share text with another; IDs/occurrences, not body text, govern.
    return result(not failures,coverage_scope=spec.get('coverage_scope'),source_units=len(source),reviewed_pass=sum(r.get('status')=='PASS' for r in reviews),missing_ids=sorted(a-b),extra_ids=sorted(b-a),failures=sorted(set(failures)),layer_counts=dict(Counter(s['layer'] for s in source)))

def scope(spec):
    n=spec['actual_page_count']
    if not isinstance(n,int) or n<1:raise ValueError('Invalid actual page count')
    kinds=spec['change_kinds'];changed=set(spec.get('changed_pages',[]))|set(spec.get('actual_diff_pages',[]))
    if not kinds: raise ValueError('Change kinds cannot be empty')
    allowed={'text','format','font','margin','numbering','section_pagination','render_environment','checker','metadata'}
    if set(kinds)-allowed:raise ValueError('Unknown change kind')
    if any(p<1 or p>n for p in changed):raise ValueError('Page outside actual document')
    global_types={'font','margin','numbering','section_pagination','render_environment'}
    if global_types & set(kinds):pages=set(range(1,n+1))
    else:pages={q for p in changed for q in (p-1,p,p+1) if 1<=q<=n}
    objects=set(spec.get('changed_objects',[]))|set(spec.get('context_objects',[]))|set(spec.get('reference_dependents',[]))|set(spec.get('term_dependents',[]))
    if 'text' in kinds and not spec.get('changed_objects'):raise ValueError('Text change requires changed object IDs')
    if 'format' in kinds and not(changed or spec.get('changed_objects')):raise ValueError('Format change impact missing')
    if 'checker' in kinds and not spec.get('affected_checks'):raise ValueError('Checker change requires affected check IDs')
    if 'metadata' in kinds and not(spec.get('changed_parts') and evidence_valid(spec.get('package_diff_evidence'))):raise ValueError('Metadata change requires exact parts and package diff evidence')
    # Object-only local changes need a render to discover page impact; empty pages
    # are not final approval. Checker-only changes need no unrelated Word render.
    render_needed=bool(set(kinds)-{'checker'})
    return result(True,review_pages=sorted(pages),review_objects=sorted(objects),
        affected_checks=spec.get('affected_checks',[]),page_impact_status='KNOWN' if pages else ('DISCOVER_AFTER_RENDER' if render_needed else 'CHECKER_ONLY'),
        final_double_render_required=bool(spec.get('stable_final_candidate')) and render_needed,intermediate_render_count=1 if render_needed else 0)

COMMANDS={'snapshot':snapshot,'verify-snapshot':verify_snapshot,'route':route,'cache':cache,'coverage':coverage,'scope':scope,'plan':plan}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=COMMANDS);p.add_argument('--spec',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    try:
        if a.output.exists() or a.spec.resolve()==a.output.resolve():raise ValueError('Refuse overwrite or input/output collision')
        spec=load_json(a.spec)
        errors=schema_validation_errors({'command':a.command,'spec':spec},Path(__file__).resolve().parents[1]/'schemas/workflow.schema.json')
        if errors:raise ValueError('; '.join(errors))
        output=COMMANDS[a.command](spec);atomic_write_json(a.output,output)
        print(json.dumps({'status':output['status'],'report':str(a.output.resolve())}));sys.exit(0 if output['status']=='PASS' else 1)
    except (KeyError,TypeError,ValueError,OSError) as e:
        print('INVALID: '+str(e),file=sys.stderr);sys.exit(2)
if __name__=='__main__':main()
