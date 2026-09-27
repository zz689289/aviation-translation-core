"""Original adversarial fixtures; every claimed review here is SYNTHETIC_TEST_ONLY."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from common import Store,Invalid,digest,validate
from contracts import load_project,binding,tokens
from original_fixture import create,make_pdf
import term_guard as term
import compare_source as compare
import check_invariants as invariants
import workflow
WORK=None

class Core(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=WORK);self.root=Path(self.tmp.name);self.spec=create(self.root)
    def tearDown(self):self.tmp.cleanup()
    def store(self):return Store(self.root)
    def read(self,n):return json.loads((self.root/n).read_text(encoding='utf-8'))
    def put(self,n,value):
        (self.root/n).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        return {'path':n,'sha256':digest((self.root/n).read_bytes())}
    def mutate(self,which,fn):
        n=which+'.json';v=self.read(n);fn(v);self.spec[which]=self.put(n,v)
    def request(self):
        return {'project':self.put('project.json',self.spec),'record':None,'findings':[],
                'impact':{'kind':'local','changed_ids':[],'dependent_ids':[]}}
    def gate(self,req,command):return workflow.run(self.store(),req,command)
    def invalid(self,fn,code):
        with self.assertRaises(Invalid) as e:fn()
        self.assertEqual(e.exception.code,code)
    def token_case(self,source,target,expected=None):
        p=self.root/'alt.pdf';make_pdf(p,[source]);ph=digest(p.read_bytes())
        self.spec['pdf']={'path':'alt.pdf','sha256':ph};self.spec['inspection']['pdf_sha256']=ph
        a=self.read('source.json');a['pdf_sha256']=ph;a['units'][0].update(text=source,evidence_sha256=ph,expected=expected or tokens(source,self.spec['vocabulary']))
        self.spec['source']=self.put('source.json',a)
        self.mutate('target',lambda x:x['units'][0].update(text=target))
    def test_original_three_checks(self):
        for f in (term.run,compare.run,invariants.run):
            r=f(self.store(),self.spec);self.assertEqual(r['mechanical_status'],'PASS');self.assertFalse(r['human_approved']);self.assertFalse(r['released']);self.assertNotEqual(r['completion'],'PASS')
    def test_term_boundaries_forms_and_case(self):
        r={'forms':['sensor','sensors'],'case_sensitive':False}
        self.assertEqual(len(term.matches('sensor sensors Sensor nonsensor sensor_1',r)),3)
        r['case_sensitive']=True;self.assertEqual(len(term.matches('Sensor sensor',r)),1)
    def test_term_overlap_is_explicit(self):
        r1={'forms':['sample cart'],'case_sensitive':False};r2={'forms':['cart'],'case_sensitive':False}
        self.assertEqual(len(term.matches('sample cart',r1))+len(term.matches('sample cart',r2)),2)
    def test_forbidden_translation(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text']+'演示禁用词'))
        self.assertIn('FORBIDDEN_TRANSLATION',term.run(self.store(),self.spec)['errors'])
    def test_required_translation(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text'].replace('传感器','部件')))
        self.assertIn('REQUIRED_TRANSLATION_MISSING',term.run(self.store(),self.spec)['errors'])
    def test_number_mismatch(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text'].replace('6','7')))
        self.assertIn('NUMBERS_MISMATCH',invariants.run(self.store(),self.spec)['errors'])
    def test_unit_case(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text'].replace(' m',' M')))
        self.assertIn('UNITS_MISMATCH',invariants.run(self.store(),self.spec)['errors'])
    def test_identifier(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text'].replace('BX','BY')))
        self.assertIn('IDENTIFIERS_MISMATCH',invariants.run(self.store(),self.spec)['errors'])
    def test_symbols_and_markers(self):
        self.token_case('(a) level = 8 m.','(a) 水平 = 8 m。')
        self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'PASS')
        self.mutate('target',lambda x:x['units'][0].update(text='(b) 水平 8 m。'))
        self.assertEqual(set(invariants.run(self.store(),self.spec)['errors']),{'SYMBOLS_MISMATCH','MARKERS_MISMATCH'})
    def test_pollution(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text']+' DEMO_INTERNAL_STAMP'))
        self.assertIn('POLLUTION_TOKEN',invariants.run(self.store(),self.spec)['errors'])
    def test_target_added(self):
        self.mutate('target',lambda x:x['units'].append(dict(x['units'][0],id='extra')))
        self.invalid(lambda:load_project(self.store(),self.spec),'SOURCE_TARGET_UNIT_SET_MISMATCH')
    def test_target_missing(self):
        self.mutate('target',lambda x:x.update(units=[]))
        self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_duplicate_id(self):
        self.mutate('source',lambda x:x['units'].append(copy.deepcopy(x['units'][0])))
        self.invalid(lambda:load_project(self.store(),self.spec),'DUPLICATE_UNIT_ID')
    def test_empty_target(self):
        self.mutate('target',lambda x:x['units'][0].update(text='  '))
        self.invalid(lambda:load_project(self.store(),self.spec),'EMPTY_CONTENT')
    def test_empty_source(self):
        self.mutate('source',lambda x:x['units'][0].update(text=' '))
        self.invalid(lambda:load_project(self.store(),self.spec),'EMPTY_CONTENT')
    def test_missing_field(self):
        self.mutate('source',lambda x:x['units'][0]['expected'].pop('units'))
        self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_omitted_expectations(self):
        self.mutate('source',lambda x:x['units'][0]['expected'].update(numbers=[]))
        self.invalid(lambda:load_project(self.store(),self.spec),'SOURCE_EXPECTATIONS_INCOMPLETE')
    def test_omitted_vocabulary(self):
        self.spec['vocabulary']['identifiers']=[]
        self.invalid(lambda:load_project(self.store(),self.spec),'TOKEN_VOCABULARY_INCOMPLETE')
    def test_target_derived(self):
        self.mutate('source',lambda x:x.update(derived_from_target=True))
        self.invalid(lambda:load_project(self.store(),self.spec),'TARGET_DERIVED_EXPECTATIONS')
    def test_pending(self):
        self.mutate('target',lambda x:x['units'][0].update(state='PENDING'))
        self.invalid(lambda:load_project(self.store(),self.spec),'UNFINISHED_WORK')
    def test_schema_scope_required(self):
        self.spec.pop('scope');self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_missing_layer(self):
        self.spec['layers'].pop('formulas');self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_unsupported_layer(self):
        self.spec['layers']['image_semantics']='UNSUPPORTED';self.invalid(lambda:load_project(self.store(),self.spec),'LAYER_UNSUPPORTED')
    def test_fake_absence(self):
        self.spec['layers']['ordinary']='ABSENT';self.invalid(lambda:load_project(self.store(),self.spec),'LAYER_DECLARATION_CONFLICT')
    def test_footnote_positive_and_missing(self):
        src={'units':[{'id':'unit_a','layer':'ordinary','text':'anchor'},{'id':'unit_b','layer':'ordinary','text':'anchor'},{'id':'body_a','layer':'footnotes','text':'same'},{'id':'body_b','layer':'footnotes','text':'same'}],'footnotes':[{'id':'note_a','anchor':'unit_a','body_unit_id':'body_a','body':'same'},{'id':'note_b','anchor':'unit_b','body_unit_id':'body_b','body':'same'}],'tables':[]}
        tgt=copy.deepcopy(src);layers={'footnotes':'PRESENT','table_cells':'ABSENT'}
        self.assertEqual(invariants.structural(src,tgt,layers),[])
        tgt['footnotes'].pop();self.assertIn('FOOTNOTE_BINDING',invariants.structural(src,tgt,layers))
    def test_footnote_duplicate_and_anchor(self):
        src={'units':[{'id':'unit_a','layer':'ordinary','text':'anchor'},{'id':'body_a','layer':'footnotes','text':'body'}],'footnotes':[{'id':'n','anchor':'unit_a','body_unit_id':'body_a','body':'body'}],'tables':[]};tgt=copy.deepcopy(src)
        tgt['footnotes'].append(dict(tgt['footnotes'][0],anchor='missing'))
        f=invariants.structural(src,tgt,{'footnotes':'PRESENT','table_cells':'ABSENT'})
        self.assertIn('FOOTNOTE_DUPLICATE_ID',f);self.assertIn('FOOTNOTE_ANCHOR_MISSING',f)
    def table(self):
        src={'units':[{'id':'unit_a','layer':'table_cells','text':'Header'}],'footnotes':[],'tables':[{'id':'table_a','coordinates':{'h1':'unit_a','h2':'unit_a'},'repeated_header_aliases':[['h1','h2']]}]}
        tgt={'units':[{'id':'unit_a','layer':'table_cells','text':'Header'}],'footnotes':[],'tables':[{'id':'table_a','mapping':{'h1':'unit_a','h2':'unit_a'},'cells':['unit_a']}]}
        return src,tgt,{'footnotes':'ABSENT','table_cells':'PRESENT'}
    def test_table_approved_alias(self):
        src,tgt,l=self.table();self.assertEqual(invariants.structural(src,tgt,l),[])
        src['tables'][0]['repeated_header_aliases']=[];self.assertIn('TABLE_UNAPPROVED_MERGE',invariants.structural(src,tgt,l))
    def test_table_missing_coordinate(self):
        src,tgt,l=self.table();tgt['tables'][0]['mapping'].pop('h1');self.assertIn('TABLE_COORDINATE_COVERAGE',invariants.structural(src,tgt,l))
    def test_table_invalid_cell(self):
        for value in (None,'','missing'):
            src,tgt,l=self.table();tgt['tables'][0]['mapping']['h1']=value
            self.assertIn('TABLE_TARGET_INVALID',invariants.structural(src,tgt,l))
    def test_table_unmapped_cell(self):
        src,tgt,l=self.table();tgt['tables'][0]['cells'].append('unused');self.assertIn('TABLE_UNMAPPED_CELL',invariants.structural(src,tgt,l))
    def test_pdf_wrong_text(self):
        self.mutate('source',lambda x:x['units'][0].update(text=x['units'][0]['text']+' Missing sentence.'))
        self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_SOURCE_MAPPING_INCOMPLETE')
    def test_pdf_wrong_page(self):
        self.mutate('source',lambda x:x['units'][0].update(page=2));self.invalid(lambda:compare.run(self.store(),self.spec),'SCOPE_UNMAPPED')
    def test_pdf_page_count(self):
        self.spec['scope']='declared_sample';self.spec['page_count']=2
        self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_PAGE_COUNT_MISMATCH')
    def test_full_cannot_omit_page(self):
        self.spec['page_count']=2;self.invalid(lambda:compare.run(self.store(),self.spec),'FULL_PAGE_SCOPE_INCOMPLETE')
    def test_empty_mapping(self):
        self.mutate('source',lambda x:x.update(units=[]));self.invalid(lambda:compare.run(self.store(),self.spec),'SCHEMA_INVALID')
    def test_pdf_extract_failure(self):
        from pypdf import PdfWriter
        p=self.root/'blank.pdf';w=PdfWriter();w.add_blank_page(100,100)
        with p.open('wb') as f:w.write(f)
        h=digest(p.read_bytes());self.spec['pdf']={'path':'blank.pdf','sha256':h};self.spec['inspection']['pdf_sha256']=h
        self.mutate('source',lambda x:(x.update(pdf_sha256=h),x['units'][0].update(evidence_sha256=h)))
        self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_EXTRACTION_FAILED')
    def test_sample_label(self):
        self.spec['scope']='declared_sample';r=compare.run(self.store(),self.spec);self.assertEqual(r['counts']['scope'],'declared_sample');self.assertNotEqual(r['completion'],'PASS')
    def test_source_hash_drift(self):
        (self.root/'source.json').write_text('{}');self.invalid(lambda:load_project(self.store(),self.spec),'HASH_DRIFT')
    def test_target_hash_drift(self):
        (self.root/'target.json').write_text('{}');self.invalid(lambda:load_project(self.store(),self.spec),'HASH_DRIFT')
    def test_pdf_hash_drift(self):
        (self.root/'source.pdf').write_bytes(b'bad');self.invalid(lambda:load_project(self.store(),self.spec),'HASH_DRIFT')
    def test_no_validator_fallback(self):
        with patch.dict(sys.modules,{'jsonschema':None}):self.invalid(lambda:validate({},'project.schema.json'),'DEPENDENCY_JSONSCHEMA_MISSING')

    def test_path_escape(self):
        self.invalid(lambda:self.store().read('../outside.txt'),'PATH_ESCAPE')
    def test_absolute_path(self):
        self.invalid(lambda:self.store().read(str(self.root/'source.json')),'PATH_INVALID' if os.name=='nt' else 'PATH_ESCAPE')
    def test_existing_output(self):
        before=(self.root/'target.json').read_bytes();self.invalid(lambda:self.store().write('target.json',{}),'OUTPUT_EXISTS');self.assertEqual((self.root/'target.json').read_bytes(),before)
    def test_input_output_collision(self):
        s=self.store();s.read('source.json');self.invalid(lambda:s.write('source.json',{}),'INPUT_OUTPUT_COLLISION')
    def test_mid_check_change(self):
        s=self.store();s.read('target.json');(self.root/'target.json').write_text('{}');self.invalid(lambda:s.write('new.json',{}),'INPUT_CHANGED_DURING_CHECK');self.assertFalse((self.root/'new.json').exists())
    def test_file_link_escape(self):
        link=self.root/'linked.json'
        try:link.symlink_to(self.root/'source.json')
        except OSError:self.skipTest('NOT_TESTED: Windows symbolic-link privilege unavailable')
        self.invalid(lambda:self.store().read('linked.json'),'LINK_REJECTED')
        link.unlink()
    def test_directory_reparse_escape(self):
        real=self.root/'real';real.mkdir();(real/'a').write_text('x');link=self.root/'junction'
        if os.name=='nt':
            p=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(real)],capture_output=True)
            if p.returncode:self.skipTest('NOT_TESTED: directory junction unavailable')
        else:link.symlink_to(real,target_is_directory=True)
        try:self.invalid(lambda:self.store().read('junction/a'),'LINK_REJECTED')
        finally:
            if os.name=='nt':os.rmdir(link)
            else:link.unlink()
    def test_shareable_outputs(self):
        for fn in (term.run,compare.run,invariants.run):
            text=json.dumps(fn(self.store(),self.spec),ensure_ascii=False)
            for secret in (str(self.root),self.read('source.json')['units'][0]['text'],self.read('target.json')['units'][0]['text']):self.assertNotIn(secret,text)
    def test_cli_error_redaction(self):
        script=Path(__file__).resolve().parents[1]/'scripts/term_guard.py'
        self.put('bad.json',{'private':'never-echo-this-marker'})
        p=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(script),'--root',str(self.root),'--spec','bad.json','--output','bad_result.json'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        for s in (str(self.root),'never-echo-this-marker','Traceback'):self.assertNotIn(s,p.stdout+p.stderr)
        self.assertFalse((self.root/'bad_result.json').exists())
    def snapshot(self):
        req=self.request();snap=self.gate(req,'snapshot');ref=self.put('snap.json',snap);req['record']=ref;return req
    def test_snapshot_verify_cache(self):
        req=self.snapshot()
        self.assertEqual(self.gate(req,'verify-snapshot')['mechanical_status'],'PASS')
        cached=self.gate(req,'cache');self.assertTrue(cached['counts']['binding_reusable']);self.assertFalse(cached['counts']['review_reusable'])
    def test_snapshot_replay(self):
        req=self.snapshot();self.spec['scope']='declared_sample';req['project']=self.put('project.json',self.spec)
        self.invalid(lambda:self.gate(req,'verify-snapshot'),'EVIDENCE_BINDING_MISMATCH')
    def test_cache_checker_changed(self):
        req=self.snapshot();r=self.read('snap.json');r['checker_sha256']='0'*64;req['record']=self.put('snap.json',r)
        self.assertIn('CHECKER_CHANGED',self.gate(req,'cache')['errors'])
    def event(self):
        req=self.request();event={'binding':binding(self.spec),'mode':'SYNTHETIC_TEST_ONLY','executor_id':'executor','qa_id':'reviewer','source_first':True,'reviewed_ids':['unit_a'],'layers':self.spec['layers']}
        req['record']=self.put('event.json',event);return req,event
    def test_synthetic_binding_never_real_qa(self):
        req,_=self.event();r=self.gate(req,'coverage');self.assertEqual(r['mechanical_status'],'PASS');self.assertEqual(r['host_qa'],'INDEPENDENT_QA_UNAVAILABLE');self.assertEqual(r['trusted_host_integration'],'NOT_RUN');self.assertFalse(r['human_approved'])
    def test_same_agent(self):
        req,e=self.event();e['qa_id']=e['executor_id'];req['record']=self.put('event.json',e);self.assertIn('SAME_OR_MISSING_REVIEWER',self.gate(req,'coverage')['errors'])
    def test_no_trusted_host(self):
        req,e=self.event();e['mode']='CLAIMED_REAL';req['record']=self.put('event.json',e);self.assertIn('HOST_EVENT_UNTRUSTED',self.gate(req,'coverage')['errors'])
    def test_synthetic_in_production(self):
        self.mutate('source',lambda x:x.update(synthetic_test_only=False));self.mutate('target',lambda x:x.update(synthetic_test_only=False))
        req,e=self.event();self.assertIn('SYNTHETIC_IN_PRODUCTION',self.gate(req,'coverage')['errors'])
    def test_qa_replay(self):
        req,e=self.event();e['binding']='0'*64;req['record']=self.put('event.json',e);self.invalid(lambda:self.gate(req,'coverage'),'EVIDENCE_BINDING_MISMATCH')
    def test_qa_missing_unit(self):
        req,e=self.event();e['reviewed_ids']=[];req['record']=self.put('event.json',e);self.assertIn('REVIEW_COVERAGE_INCOMPLETE',self.gate(req,'coverage')['errors'])
    def test_qa_layer(self):
        req,e=self.event();e['layers']={};req['record']=self.put('event.json',e);self.assertIn('REVIEW_LAYERS_INCOMPLETE',self.gate(req,'coverage')['errors'])
    def finding(self,state='PENDING'):
        return {'id':'finding_a','state':state,'scope':['unit_a'],'decision_required':False,'evidence':None,'decision':None}
    def test_pending_route(self):
        req=self.request();req['findings']=[self.finding()];self.assertIn('UNFINISHED_WORK',self.gate(req,'route')['errors'])
    def test_open_route(self):
        req=self.request();req['findings']=[self.finding('OPEN')];self.assertIn('REPAIR_OR_HUMAN_DECISION_REQUIRED',self.gate(req,'route')['errors'])
    def resolved(self):
        req=self.request();f=self.finding('RESOLVED');f['decision_required']=True;k=binding(self.spec)
        ctx=digest({'id':f['id'],'binding':k,'scope':f['scope'],'decision_required':True})
        f['evidence']=self.put('proof.json',{'binding':k,'context':ctx,'state':'RECHECKED','mode':'SYNTHETIC_TEST_ONLY'})
        f['decision']=self.put('decision.json',{'binding':k,'context':ctx,'decision':'APPROVE','mode':'SYNTHETIC_TEST_ONLY'})
        req['findings']=[f];return req
    def test_bound_synthetic_decision_not_human_approval(self):
        r=self.gate(self.resolved(),'route');self.assertEqual(r['mechanical_status'],'PASS');self.assertFalse(r['human_approved'])
    def test_old_human_target_invalid(self):
        req=self.resolved();self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text']+'。'));req['project']=self.put('project.json',self.spec)
        self.invalid(lambda:self.gate(req,'route'),'EVIDENCE_BINDING_MISMATCH')
    def test_old_decision_scope_invalid(self):
        req=self.resolved();req['findings'][0]['scope']=['other'];self.invalid(lambda:self.gate(req,'route'),'EVIDENCE_BINDING_MISMATCH')
    def test_no_decision(self):
        req=self.resolved();req['findings'][0]['decision']=None;self.invalid(lambda:self.gate(req,'route'),'EVIDENCE_REQUIRED')
    def test_scope_positive_negative(self):
        req=self.request();self.invalid(lambda:self.gate(req,'scope'),'CHANGE_IMPACT_MISSING')
        req['impact']['changed_ids']=['unit_a'];self.assertEqual(self.gate(req,'scope')['counts']['units_to_recheck'],1)
        req['impact']['kind']='global';self.assertEqual(self.gate(req,'scope')['mechanical_status'],'PASS')
    def test_all_cli_contracts(self):
        base=Path(__file__).resolve().parents[1]/'scripts'
        for name in ['term_guard.py','compare_source.py','check_invariants.py']:
            self.put('project.json',self.spec)
            command=[sys.executable,'-X','utf8','-I','-B',str(base/name),'--root',str(self.root),'--spec','project.json','--output',name+'.json']
            p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,0,(name,p.stderr))
            p=subprocess.run(command,capture_output=True,text=True);self.assertEqual(p.returncode,2)
        req=self.snapshot();req['impact']['changed_ids']=['unit_a'];self.put('cli-request.json',req)
        for cmd in ['snapshot','verify-snapshot','cache','route','scope']:
            p=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(base/'workflow.py'),cmd,'--root',str(self.root),'--spec','cli-request.json','--output','cli-'+cmd+'.json'],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,(cmd,p.stderr))
        req,e=self.event();self.put('cli-event.json',req)
        p=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(base/'workflow.py'),'coverage','--root',str(self.root),'--spec','cli-event.json','--output','cli-coverage.json'],capture_output=True,text=True);self.assertEqual(p.returncode,0)

    def rebind_pdf(self,name):
        h=digest((self.root/name).read_bytes());self.spec['pdf']={'path':name,'sha256':h};self.spec['inspection']['pdf_sha256']=h
        self.mutate('source',lambda x:(x.update(pdf_sha256=h),[u.update(evidence_sha256=h) for u in x['units']]))
    def test_actual_two_page_sample_not_full(self):
        text=self.read('source.json')['units'][0]['text'];make_pdf(self.root/'two.pdf',[text,'Another original page.'])
        self.rebind_pdf('two.pdf');self.spec['page_count']=2;self.spec['scope']='declared_sample'
        r=compare.run(self.store(),self.spec);self.assertEqual(r['counts']['pages'],1);self.assertEqual(r['counts']['scope'],'declared_sample')
        self.spec['scope']='full';self.invalid(lambda:compare.run(self.store(),self.spec),'FULL_PAGE_SCOPE_INCOMPLETE')
    def test_malformed_pdf(self):
        (self.root/'broken.pdf').write_bytes(b'not a pdf with private diagnostic text');self.rebind_pdf('broken.pdf')
        self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_EXTRACTION_FAILED')
    def test_pdf_image_layer_rejected(self):
        from pypdf import PdfReader,PdfWriter
        from pypdf.generic import NameObject,DictionaryObject
        reader=PdfReader(self.root/'source.pdf');writer=PdfWriter();writer.add_page(reader.pages[0])
        writer.pages[0]['/Resources'][NameObject('/XObject')]=DictionaryObject({NameObject('/Image1'):DictionaryObject()})
        with (self.root/'objects.pdf').open('wb') as f:writer.write(f)
        self.rebind_pdf('objects.pdf');self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_NON_TEXT_LAYER_UNSUPPORTED')
    def test_pdf_encrypted_rejected(self):
        from pypdf import PdfReader,PdfWriter
        writer=PdfWriter();writer.add_page(PdfReader(self.root/'source.pdf').pages[0]);writer.encrypt('synthetic-fixture-only')
        with (self.root/'encrypted.pdf').open('wb') as f:writer.write(f)
        self.rebind_pdf('encrypted.pdf');self.invalid(lambda:compare.run(self.store(),self.spec),'PDF_ENCRYPTED_UNSUPPORTED')
    def test_whitespace_inspection_not_evidence(self):
        self.spec['inspection']['rationale']=' ';self.invalid(lambda:load_project(self.store(),self.spec),'INSPECTION_RATIONALE_REQUIRED')

    def test_cli_argument_error_redaction(self):
        script=Path(__file__).resolve().parents[1]/'scripts/workflow.py'
        p=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(script),'private-command-marker','--root',str(self.root)],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertNotIn('private-command-marker',p.stderr);self.assertNotIn(str(self.root),p.stderr);self.assertNotIn('Traceback',p.stderr)

    def test_r1_phantom_cell(self):
        a,b,l=self.table();b['tables'][0].update(mapping={'h1':'phantom','h2':'phantom'},cells=['phantom'])
        self.assertIn('TABLE_TARGET_INVALID',invariants.structural(a,b,l))
    def test_r1_table_swapped(self):
        a,b,l=self.table();a['units'].append({'id':'unit_b','layer':'table_cells','text':'Other'})
        b['units']=copy.deepcopy(a['units']);a['tables'][0].update(coordinates={'h1':'unit_a','h2':'unit_b'},repeated_header_aliases=[])
        b['tables'][0].update(mapping={'h1':'unit_b','h2':'unit_a'},cells=['unit_a','unit_b'])
        self.assertIn('TABLE_CONTENT_BINDING',invariants.structural(a,b,l))
    def test_r1_distinct_repeated_headers(self):
        a,b,l=self.table();a['units'].append(dict(a['units'][0],id='unit_b'));b['units']=copy.deepcopy(a['units'])
        a['tables'][0]['coordinates']['h2']='unit_b'
        self.assertEqual(invariants.structural(a,b,l),[])
        b['units'][1]['text']='Different'
        self.assertIn('TABLE_ALIAS_CONTENT_CONFLICT',invariants.structural(a,b,l))
    def test_r1_table_layer_and_coverage(self):
        a,b,l=self.table();a['units'][0]['layer']='ordinary'
        self.assertIn('TABLE_SOURCE_REFERENCE',invariants.structural(a,b,l))
        a,b,l=self.table();a['units'].append({'id':'unused','layer':'table_cells','text':'Other'})
        self.assertIn('TABLE_UNIT_COVERAGE',invariants.structural(a,b,l))
    def note_fixture(self):
        a={'units':[{'id':'anchor','layer':'ordinary','text':'Main'},{'id':'body','layer':'footnotes','text':'Limit 8 m.'}],
           'footnotes':[{'id':'note','anchor':'anchor','body_unit_id':'body','body':'Limit 8 m.'}],'tables':[]}
        return a,copy.deepcopy(a),{'footnotes':'PRESENT','table_cells':'ABSENT'}
    def test_r1_note_body_conflict(self):
        a,b,l=self.note_fixture();b['footnotes'][0]['body']='Limit 999 m.'
        self.assertIn('FOOTNOTE_BODY_CONFLICT',invariants.structural(a,b,l))
    def test_r1_note_missing_reference(self):
        a,b,l=self.note_fixture();b['footnotes'][0].pop('body_unit_id')
        self.assertIn('FOOTNOTE_BODY_REFERENCE',invariants.structural(a,b,l))
    def test_r1_note_wrong_layer(self):
        a,b,l=self.note_fixture();a['units'][1]['layer']='ordinary'
        self.assertIn('FOOTNOTE_BODY_LAYER',invariants.structural(a,b,l))
    def test_r1_note_wrong_reference(self):
        a,b,l=self.note_fixture();b['footnotes'][0]['body_unit_id']='anchor'
        self.assertIn('FOOTNOTE_BODY_REFERENCE',invariants.structural(a,b,l))
    def test_r1_note_uncovered(self):
        a,b,l=self.note_fixture();a['units'].append({'id':'unused','layer':'footnotes','text':'Extra'})
        self.assertIn('FOOTNOTE_UNIT_COVERAGE',invariants.structural(a,b,l))
    def test_r1_note_shared_body_reference(self):
        a,b,l=self.note_fixture();a['footnotes'].append(dict(a['footnotes'][0],id='note_b'))
        self.assertIn('FOOTNOTE_BODY_REUSED',invariants.structural(a,b,l))
    def test_r1_legacy_contract_rejected(self):
        self.spec['version']=1;self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_r1_missing_source_contract_rejected(self):
        self.mutate('source',lambda x:x.pop('contract_version'))
        self.invalid(lambda:load_project(self.store(),self.spec),'SCHEMA_INVALID')
    def test_r1_missing_note_binding_schema(self):
        x=self.read('source.json');x['footnotes']=[{'id':'note','anchor':'unit_a','body':'Body'}]
        self.invalid(lambda:validate(x,'source.schema.json'),'SCHEMA_INVALID')
    def test_r1_note_pdf_binding(self):
        self.mutate('source',lambda x:(x['units'][0].update(layer='footnotes'),x.update(footnotes=[])))
        self.spec['layers'].update(ordinary='ABSENT',footnotes='PRESENT')
        self.mutate('source',lambda x:x['units'][0].update(text=x['units'][0]['text']+' Not in document.'))
        self.invalid(lambda:invariants.run(self.store(),self.spec),'PDF_SOURCE_MAPPING_INCOMPLETE')
    def test_r2_term_rule_snapshot(self):
        req=self.snapshot();self.spec['term_rules'][0]['forbidden_targets'].append('传感器');req['project']=self.put('project.json',self.spec)
        self.assertEqual(term.run(self.store(),self.spec)['mechanical_status'],'FAIL')
        for cmd in ('verify-snapshot','cache'):self.invalid(lambda:self.gate(req,cmd),'EVIDENCE_BINDING_MISMATCH')
    def test_r2_pollution_snapshot(self):
        req=self.snapshot();self.spec['pollution_tokens'].append('传感器');req['project']=self.put('project.json',self.spec)
        self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'FAIL')
        for cmd in ('verify-snapshot','cache'):self.invalid(lambda:self.gate(req,cmd),'EVIDENCE_BINDING_MISMATCH')
    def test_r2_whole_contract_binding(self):
        old=binding(self.spec)
        self.assertEqual(old,binding(dict(reversed(list(self.spec.items())))))
        for field in self.spec:
            changed=copy.deepcopy(self.spec);changed[field]={'synthetic_changed':True}
            self.assertNotEqual(old,binding(changed),field)
    def test_r3_chinese_extra_number(self):
        self.mutate('target',lambda x:x['units'][0].update(text=x['units'][0]['text']+'另加999项。'))
        self.assertIn('NUMBERS_MISMATCH',invariants.run(self.store(),self.spec)['errors'])
    def test_r3_chinese_adjacent_positive(self):
        self.mutate('target',lambda x:x['units'][0].update(text='示例小车行进6 m，耗时4 s。BX传感器应保持工作。'))
        self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'PASS')
    def test_r3_sign_decimal_punctuation(self):
        for text,expected in [('值-12.5，值+4.0。',['-12.5','+4.0']),('6, 4; (8).',['6','4','8']),('值6。值4！',['6','4']),('6.',['6']),('0 -0 +0.25',['0','-0','+0.25'])]:
            self.assertEqual(tokens(text,self.spec['vocabulary'])['numbers'],expected)
    def test_r3_english_internal_digits(self):
        for text in ['BX6 A12B sensor_6 _7 8_A','AB-12 XY+4','1.2.3 .5 6e3 3E-2']:
            self.assertEqual(tokens(text,self.spec['vocabulary'])['numbers'],[])
    def test_r3_vocab_boundaries(self):
        t=tokens('行进6 m，BX传感器 m单位；prefixBX BX_1 BX2',self.spec['vocabulary'])
        self.assertEqual(t['numbers'],['6']);self.assertEqual(t['units'],['m','m']);self.assertEqual(t['identifiers'],['BX'])
    def test_r3_signed_decimal_full_check(self):
        self.token_case('Limit -12.5 m and +4.0 s. BX active.','限值-12.5 m与+4.0 s。BX工作。')
        self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'PASS')

    def structured_case(self,kind):
        entries=[('anchor','ordinary','Two notes follow.','两条注释如下。'),('body_a','footnotes','Limit 8 m.','限值8 m。'),('body_b','footnotes','Limit 8 m.','限值8 m。')] if kind=='notes' else [('unit_a','table_cells','Header 8 m.','表头8 m。'),('unit_b','table_cells','Header 8 m.','表头8 m。')]
        make_pdf(self.root/'structured.pdf',[' '.join(x[2] for x in entries)]);ph=digest((self.root/'structured.pdf').read_bytes())
        self.spec['pdf']={'path':'structured.pdf','sha256':ph};self.spec['inspection']['pdf_sha256']=ph
        self.spec['layers']={k:('PRESENT' if k in {x[1] for x in entries} else 'ABSENT') for k in self.spec['layers']}
        a=self.read('source.json');b=self.read('target.json');a['pdf_sha256']=ph
        a['units']=[{'id':i,'layer':l,'page':1,'text':s,'evidence_sha256':ph,'expected':tokens(s,self.spec['vocabulary'])} for i,l,s,t in entries]
        b['units']=[{'id':i,'text':t,'state':'COMPLETE'} for i,l,s,t in entries]
        if kind=='notes':
            a['footnotes']=[{'id':'note_'+i[-1],'anchor':'anchor','body_unit_id':i,'body':s} for i,l,s,t in entries[1:]]
            b['footnotes']=[{'id':'note_'+i[-1],'anchor':'anchor','body_unit_id':i,'body':t} for i,l,s,t in entries[1:]]
        else:
            a['tables']=[{'id':'table_a','coordinates':{'h1':'unit_a','h2':'unit_b'},'repeated_header_aliases':[['h1','h2']]}]
            b['tables']=[{'id':'table_a','mapping':{'h1':'unit_a','h2':'unit_a'},'cells':['unit_a']}]
        self.spec['source']=self.put('source.json',a);self.spec['target']=self.put('target.json',b)
    def test_r1_full_repeated_notes_positive(self):
        self.structured_case('notes');self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'PASS')
        self.mutate('target',lambda x:x['footnotes'][1].update(body='限值999 m。'))
        self.assertIn('FOOTNOTE_BODY_CONFLICT',invariants.run(self.store(),self.spec)['errors'])
    def test_r1_full_repeated_headers_positive(self):
        self.structured_case('table');self.assertEqual(invariants.run(self.store(),self.spec)['mechanical_status'],'PASS')
        self.mutate('target',lambda x:x['units'][1].update(text='不同表头8 m。'))
        self.assertIn('TABLE_ALIAS_CONTENT_CONFLICT',invariants.run(self.store(),self.spec)['errors'])
