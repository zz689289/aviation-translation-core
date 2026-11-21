"""Small deterministic contract/regression suite. No Word, no production writes."""
import unittest,tempfile,copy,json,subprocess,sys
from pathlib import Path
import workflow as w
from check_invariants import check
from common import schema_validation_errors,load_layout_profile,resolve_layout_profile
from build_escalation_queue import classify,effective_assessor_tier,route_item

class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'evidence.txt';self.p.write_text('actual test evidence')
        self.ev=[{'path':str(self.p),'sha256':w.sha256_file(self.p)}]
        self.deps={k:w.digest(k) for k in w.DEPENDENCIES}
        self.rec={'status':'PASS','complete':True,'kind':'semantic_object','dependencies':self.deps,'scope_ids':['a'],'evidence':self.ev}
    def tearDown(self):self.tmp.cleanup()
    def proof(self,name,data):
        p=Path(self.tmp.name)/(name+'.json');p.write_text(json.dumps(data),encoding='utf-8');return {'path':str(p),'sha256':w.sha256_file(p)}
    def snap(self):return w.snapshot({'artifacts':[{'id':'target','role':'target','path':str(self.p)}],'dependencies':self.deps})
    def test_snapshot_identity_rename(self):
        x={'artifacts':[{'id':'source','role':'source','path':str(self.p)}],'dependencies':self.deps};a=w.snapshot(x)
        q=self.p.with_name('renamed.txt');q.write_bytes(self.p.read_bytes());x['artifacts'][0]['path']=str(q)
        self.assertEqual(a['snapshot_id'],w.snapshot(x)['snapshot_id'])
    def test_snapshot_mutation(self):
        a=w.snapshot({'artifacts':[{'id':'x','role':'source','path':str(self.p)}],'dependencies':self.deps});self.p.write_text('changed')
        with self.assertRaises(ValueError):w.verify_snapshot(a)
    def test_valid_cache(self):self.assertTrue(w.cache({'record':self.rec,'current':copy.deepcopy(self.rec)})['reusable'])
    def test_each_dependency_invalidates(self):
        for k in w.DEPENDENCIES:
            c=copy.deepcopy(self.rec);c['dependencies'][k]=w.digest('changed'+k)
            self.assertFalse(w.cache({'record':self.rec,'current':c})['reusable'],k)
    def test_fail_partial_not_cached(self):
        for k,v in [('status','FAIL'),('complete',False),('scope_ids',[])]:
            r=copy.deepcopy(self.rec);r[k]=v;self.assertFalse(w.cache({'record':r,'current':self.rec})['reusable'])
    def test_changed_evidence_invalidates(self):
        self.p.write_text('changed');self.assertFalse(w.cache({'record':self.rec,'current':self.rec})['reusable'])
    def test_visual_requires_actual_comparison(self):
        r=copy.deepcopy(self.rec);r['kind']='visual_page';c=copy.deepcopy(r)
        self.assertFalse(w.cache({'record':r,'current':c})['reusable'])
        c.update(actual_render_comparison_pass=True,comparison_evidence=self.ev)
        # Legacy pixel-only records no longer establish adequate visual review.
        self.assertFalse(w.cache({'record':r,'current':c})['reusable'])
    def finding(self):
        return {'id':'x','status':'OPEN','source_evidence':self.ev,'authorized_goal':'faithful translation','root_cause':'builder omission','scope':['formula-x'],**{k:False for k in w.DECISION_FLAGS}}
    def test_pending_not_amber(self):
        r=w.route({'findings':[{'id':'x','status':'PENDING'}]});self.assertEqual(r['manual_handoff'],[]);self.assertEqual(r['pending_translation_objects'],1);self.assertTrue(r['acceptance_blocked'])
    def test_routine_not_human(self):
        r=w.route({'findings':[self.finding()]});self.assertEqual(len(r['auto_repair_backlog']),1);self.assertEqual(r['manual_handoff'],[]);self.assertTrue(r['ordinary_qa_dispatch_permitted'])
    def test_true_decisions_grouped(self):
        for k in w.DECISION_FLAGS:
            f=self.finding();f[k]=True;r=w.route({'findings':[f]});self.assertEqual(len(r['manual_handoff']),1);self.assertEqual(r['auto_repair_backlog'],[])
    def test_missing_source_not_repaired(self):
        f=self.finding();f['source_evidence']=[];self.assertEqual(len(w.route({'findings':[f]})['manual_handoff']),1)
    def test_two_stalled_rounds_diagnose(self):
        f=self.finding();f['repair_history']=[{'outcome':'FAIL','failure_fingerprint':'same','substantive_progress':False}]*2
        self.assertEqual(len(w.route({'findings':[f]})['diagnosis_required']),1)
    def test_resolved_requires_recheck(self):
        with self.assertRaises(ValueError):w.route({'findings':[{'id':'x','status':'RESOLVED'}]})
        f=self.resolved();self.assertEqual(w.route({'findings':[f]})['resolved_ids'],['x'])
        f['target_sha256']=w.digest('new');
        with self.assertRaises(ValueError):w.route({'findings':[f]})
    def resolved(self):
        f=self.finding();f.update(status='RESOLVED',recheck_pass=True,target_sha256=w.sha256_file(self.p))
        f['recheck_record']=self.proof('recheck',{'finding_id':f['id'],'context_sha256':w.finding_binding(f),'status':'PASS','target_sha256':f['target_sha256']})
        return f
    def test_resolved_does_not_bypass_human_or_permission(self):
        for key in w.DECISION_FLAGS:
            f=self.resolved();f[key]=True;f.update(human_decision_approved=False,permission_granted=False)
            r=w.route({'findings':[f]});self.assertTrue(r['acceptance_blocked']);self.assertEqual(r['resolved_ids'],[])
    def test_scoped_decisions_required_not_self_declared(self):
        f=self.resolved();f['source_editorial_change']=True;f['human_decision_approved']=True
        self.assertTrue(w.route({'findings':[f]})['acceptance_blocked'])
        f['decision_records']={'source_editorial_change':self.proof('decision',{'finding_id':'x','context_sha256':w.finding_binding(f),'decision_flag':'source_editorial_change','authority':'CURRENT_USER_EXPLICIT_DECISION','status':'HUMAN_APPROVED'})}
        self.assertFalse(w.route({'findings':[f]})['acceptance_blocked'])
        f['scope']=['another-object'];self.assertTrue(w.route({'findings':[f]})['acceptance_blocked'])
    def test_old_human_decision_cannot_follow_new_target_recheck(self):
        f=self.resolved();f['source_editorial_change']=True;f['human_decision_approved']=True
        f['decision_records']={'source_editorial_change':self.proof('old-decision',{'finding_id':'x','context_sha256':w.finding_binding(f),'target_sha256':f['target_sha256'],'decision_flag':'source_editorial_change','authority':'CURRENT_USER_EXPLICIT_DECISION','status':'HUMAN_APPROVED'})}
        f['target_sha256']=w.digest('unapproved new target')
        f['recheck_record']=self.proof('new-recheck',{'finding_id':'x','context_sha256':w.finding_binding(f),'status':'PASS','target_sha256':f['target_sha256']})
        r=w.route({'findings':[f]});self.assertTrue(r['acceptance_blocked']);self.assertEqual(r['resolved_ids'],[])
    def test_local_and_global_scopes(self):
        self.assertEqual(w.scope({'actual_page_count':8,'change_kinds':['format'],'changed_pages':[4]})['review_pages'],[3,4,5])
        self.assertEqual(w.scope({'actual_page_count':8,'change_kinds':['font']})['review_pages'],list(range(1,9)))
    def cover(self):
        snap=self.snap();sid=snap['snapshot_id'];h=w.sha256_file(self.p)
        dispatch=self.proof('synthetic-dispatch',{'executor_thread_id':'main','qa_thread_id':'child','snapshot_id':sid,'source_first':True,'synthetic_test_only':True})
        return {'snapshot':snap,'snapshot_id':sid,'source_inventory_snapshot_id':sid,'dispatch_record':dispatch,'source_inventory':[{'id':'formula','layer':'formulas','pages':[1]}], 'executor_inventory':[{'id':'formula','target_artifact_id':'target','target_sha256':h}], 'reviews':[{'id':'formula','status':'PASS','rationale':'synthetic test only','evidence':self.ev,'snapshot_id':sid,'target_sha256':h,'qa_thread_id':'child'}], 'coverage_scope':'declared_sample','source_page_count':5,'source_pages':[1],'source_pages_inspected':[1],'source_inventory_basis':'INDEPENDENT_ORIGINAL_SOURCE','executor_thread_id':'main','qa_thread_id':'child','dispatch_evidence':[dispatch],'source_inspection_evidence':self.ev,'layer_review':{k:{'inspected':True,'rationale':'synthetic layer observation'} for k in w.LAYERS}}
    def test_no_replay_missing_or_old_snapshot(self):
        for key,value in [('snapshot_id',w.digest('old')),('target_sha256',w.digest('old')),('qa_thread_id','other')]:
            s=self.cover();s['reviews'][0][key]=value;self.assertEqual(w.coverage(s)['status'],'FAIL')
        s=self.cover();s.pop('snapshot');self.assertEqual(w.coverage(s)['status'],'FAIL')
        s=self.cover();self.p.write_text('changed candidate');self.assertEqual(w.coverage(s)['status'],'FAIL')
    def test_empty_change_impact_not_pass(self):
        for kind in ['text','format','checker']:
            with self.assertRaises(ValueError):w.scope({'actual_page_count':10,'change_kinds':[kind]})
        r=w.scope({'actual_page_count':10,'change_kinds':['checker'],'affected_checks':['unit-check']})
        self.assertEqual(r['intermediate_render_count'],0);self.assertEqual(r['affected_checks'],['unit-check'])
        self.assertEqual(w.scope({'actual_page_count':10,'change_kinds':['format'],'changed_objects':['title']})['page_impact_status'],'DISCOVER_AFTER_RENDER')
    def test_coverage_good_and_omitted_formula(self):
        s=self.cover();self.assertEqual(w.coverage(s)['status'],'PASS');s['executor_inventory']=[];self.assertIn('SOURCE_UNITS_NOT_PROJECTED',w.coverage(s)['failures'])
    def test_no_full_from_partial(self):
        s=self.cover();s['coverage_scope']='full_document';self.assertIn('FALSE_FULL_SOURCE_PAGE_COVERAGE',w.coverage(s)['failures'])
    def test_same_agent_not_independent(self):
        s=self.cover();s['qa_thread_id']='main';self.assertIn('INDEPENDENCE_NOT_ESTABLISHED',w.coverage(s)['failures'])
    def test_layer_coverage_and_unreviewed(self):
        s=self.cover();s['layer_review'].pop('footnotes');s['reviews']=[];self.assertNotEqual(w.coverage(s)['status'],'PASS')
    def test_unit_case_and_identifiers(self):
        for k,src,tgt in [('units',['Mg'],['kg']),('identifiers',['FEM'],['FDM']),('numbers',['25.562'],['25.561']),('symbols',['x_i^2'],['x_i'])]:
            r=check({'source_units':[{'id':'a',k:src}],'target_units':[{'id':'a',k:tgt}]});self.assertEqual(r['mechanical_status'],'FAIL')
    def test_canonical_positive_rule(self):
        s={'source_units':[{'id':'a','canonical_rules':[{'required_target':'计算流体力学','source_context':'Computational Fluid Dynamics (CFD)','approval_evidence':'project decision'}]}],'target_units':[{'id':'a','text':'计算流体动力学（CFD）'}]}
        self.assertEqual(check(s)['mechanical_status'],'FAIL');s['target_units'][0]['text']='计算流体力学（CFD）';self.assertEqual(check(s)['mechanical_status'],'PASS')
    def test_legitimate_repeated_footnote_body(self):
        notes={'expected_bindings':[{'id':1,'anchor':'a'},{'id':2,'anchor':'b'}],'references':[{'id':1,'anchor':'a'},{'id':2,'anchor':'b'}],'bodies':[{'id':1,'text':'same'},{'id':2,'text':'same'}]}
        self.assertEqual(check({'footnotes':notes})['mechanical_status'],'PASS');notes['references'].pop();self.assertEqual(check({'footnotes':notes})['mechanical_status'],'FAIL')
    def test_toc_alignment(self):
        self.assertEqual(check({'toc':[{'id':'a','saved_cache_page':2,'pdf_toc_page':3,'actual_heading_page':3}]})['mechanical_status'],'FAIL')
        self.assertEqual(check({'heading_geometry':[{'id':'h','source_geometry_evidence':'source crop','expected_text_x_pt':161.9,'actual_text_x_pt':172.9}]})['mechanical_status'],'FAIL')
    def test_continuation_aliases(self):
        m={'source_coordinates':['t1/h','t2/h','t1/1','t2/1'],'coordinate_to_render_cell':{'t1/h':'r1','t2/h':'r1','t1/1':'r2','t2/1':'r3'},'render_cell_inventory':['r1','r2','r3'],'approved_repeated_header_aliases':[['t1/h','t2/h']]}
        self.assertEqual(check({'table_mapping':m})['mechanical_status'],'PASS');m['approved_repeated_header_aliases']=[];self.assertEqual(check({'table_mapping':m})['mechanical_status'],'FAIL')
    def test_null_empty_and_nonexistent_render_cells_fail(self):
        for bad in [None,'','missing',0,[]]:
            m={'source_coordinates':['t/r/c'],'coordinate_to_render_cell':{'t/r/c':bad},'render_cell_inventory':['r1']}
            self.assertEqual(check({'table_mapping':m})['mechanical_status'],'FAIL')
    def test_source_enum_quirk_not_silently_corrected(self):
        s={'source_units':[{'id':'a','marker':'(ix)'},{'id':'b','marker':'(ix)'}],'target_units':[{'id':'a','marker':'(ix)'},{'id':'b','marker':'(ix)'}]}
        self.assertEqual(check(s)['mechanical_status'],'PASS');s['target_units'][1]['marker']='(xi)';self.assertEqual(check(s)['mechanical_status'],'FAIL')
    def test_legacy_trust_boundary_retained(self):
        self.assertEqual(effective_assessor_tier('human_authority','economy_model')[0],'economy_model')
        self.assertEqual(classify({'signals':['source_correction'],'declared_risk_class':'GREEN'})[0],'RED')
        r=route_item({'signals':['source_correction'],'candidate_resolution':'guess'},'RED','balanced','economy_model');self.assertIn('LOW_COST_RED_GUESS_SUPPRESSED',r[2])
    def test_personal_profile_opt_in(self):
        root=Path(__file__).resolve().parents[1]
        for name in ('source_faithful','zh_formal_print','personal_zh_review','personal_paper_review'):
            self.assertEqual(schema_validation_errors(load_layout_profile(name),root/'schemas/layout_profile.schema.json'),[])
        self.assertEqual(resolve_layout_profile({})['profile_id'],'source_faithful')
        s=resolve_layout_profile({'profile_id':'personal_zh_review'})['styles'];self.assertEqual(s['FootnoteText']['size_pt'],9);self.assertEqual(s['Figure Caption']['size_pt'],9)
    def test_all_schemas_parse_and_bundled_validator_executes(self):
        for p in (Path(__file__).resolve().parents[1]/'schemas').glob('*.json'):
            s=json.loads(p.read_text(encoding='utf-8-sig'));self.assertIsInstance(s,dict)
            self.assertIsInstance(schema_validation_errors({},p),list)
    def test_actual_cli_all_six_commands_positive_and_negative(self):
        specs={'snapshot':{'artifacts':[{'id':'target','role':'target','path':str(self.p)}],'dependencies':self.deps},
            'verify-snapshot':self.snap(),'route':{'findings':[]},'cache':{'record':self.rec,'current':copy.deepcopy(self.rec)},
            'coverage':self.cover(),'scope':{'actual_page_count':8,'change_kinds':['format'],'changed_pages':[4]}}
        script=Path(__file__).with_name('workflow.py')
        for cmd,s in specs.items():
            for positive in (True,False):
                p=Path(self.tmp.name)/(cmd+str(positive)+'.json');p.write_text(json.dumps(s if positive else {}),encoding='utf-8')
                out=p.with_suffix('.result.json')
                run=subprocess.run([sys.executable,'-B',str(script),cmd,'--spec',str(p),'--output',str(out)],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(run.returncode,0 if positive else 2,(cmd,positive,run.stdout,run.stderr))
                if positive:self.assertEqual(json.loads(out.read_text(encoding='utf-8'))['status'],'PASS')
        # CLI gate FAIL is distinct from invalid specification.
        p=Path(self.tmp.name)/'route-open.json';p.write_text(json.dumps({'findings':[self.finding()]}),encoding='utf-8')
        run=subprocess.run([sys.executable,'-B',str(script),'route','--spec',str(p),'--output',str(p.with_suffix('.result.json'))],capture_output=True)
        self.assertEqual(run.returncode,1)
    def test_invariant_cli_null_mapping_detected(self):
        p=Path(self.tmp.name)/'null.json';p.write_text(json.dumps({'table_mapping':{'source_coordinates':['c1'],'coordinate_to_render_cell':{'c1':None}}}),encoding='utf-8')
        run=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('check_invariants.py')),'--spec',str(p),'--output',str(p.with_suffix('.result.json'))],capture_output=True)
        self.assertEqual(run.returncode,1)

if __name__=='__main__':unittest.main(verbosity=2)
