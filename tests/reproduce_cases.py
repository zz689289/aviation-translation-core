"""Six controller-specified synthetic regressions; writes only a NEW private work tree."""
from pathlib import Path
import argparse,json,sys,subprocess,os,hashlib,importlib.metadata as meta
p=argparse.ArgumentParser();p.add_argument('--code',required=True);p.add_argument('--work',required=True);p.add_argument('--result',required=True);a=p.parse_args()
code=Path(a.code).resolve();work=Path(a.work).resolve()
if Path(a.result).exists():raise SystemExit('RESULT_EXISTS')
work.mkdir(parents=True)
sys.path.insert(0,str(code/'examples'));sys.path.insert(0,str(code/'scripts'))
from original_fixture import create,make_pdf
from contracts import tokens,binding

def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(root,n,v):
 (root/n).write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8');return {'path':n,'sha256':h(root/n)}
def read(root,n):return json.loads((root/n).read_text(encoding='utf-8'))
def sync(root,spec,src=None,tgt=None):
 if src is not None:spec['source']=put(root,'source.json',src)
 if tgt is not None:spec['target']=put(root,'target.json',tgt)
 return put(root,'project.json',spec)
commands=[]
def run(root,script,out,command=None):
 cmd=[sys.executable,'-X','utf8','-I','-B',str(code/'scripts'/script)]
 if command:cmd.append(command)
 cmd+=['--root',str(root),'--spec','request.json' if command else 'project.json','--output',out]
 env=dict(os.environ);env.pop('PYTHONPATH',None);env['TEMP']=str(work);env['TMP']=str(work)
 r=subprocess.run(cmd,cwd=code,env=env,capture_output=True,text=True,encoding='utf-8')
 commands.append({'script':script,'command':command,'exit_code':r.returncode,'flags':['-X','utf8','-I','-B']})
 if (root/out).exists():v=read(root,out)
 else:
  try:v=json.loads(r.stderr)
  except Exception:v={'code':'UNPARSEABLE_PRIVATE_DIAGNOSTIC'}
 return {'exit_code':r.returncode,'status':v.get('mechanical_status',v.get('status')),'errors':v.get('errors',[v['code']] if 'code' in v else []),'binding_reusable':v.get('counts',{}).get('binding_reusable'),'human_approved':v.get('human_approved',False),'released':v.get('released',False)}
results={}
for case in ('R1a','R1b','R2a','R2b','R3a','R3b'):
 root=work/case;root.mkdir();spec=create(root);src=read(root,'source.json');tgt=read(root,'target.json')
 if case=='R1a':
  src['units'][0]['layer']='table_cells';spec['layers']['ordinary']='ABSENT';spec['layers']['table_cells']='PRESENT'
  src['tables']=[{'id':'table_a','coordinates':{'r1c1':'unit_a'},'repeated_header_aliases':[]}]
  tgt['tables']=[{'id':'table_a','mapping':{'r1c1':'phantom_cell'},'cells':['phantom_cell']}]
 elif case=='R1b':
  make_pdf(root/'note.pdf',['One original note follows. Limit 8 m.']);ph=h(root/'note.pdf');spec['pdf']={'path':'note.pdf','sha256':ph};spec['inspection']['pdf_sha256']=ph;src['pdf_sha256']=ph
  spec['layers']['footnotes']='PRESENT';spec['vocabulary']={'units':['m'],'identifiers':[],'symbols':['=']}
  src['units']=[{'id':i,'page':1,'layer':layer,'text':text,'evidence_sha256':ph,'expected':tokens(text,spec['vocabulary'])} for i,layer,text in [('main','ordinary','One original note follows.'),('note','footnotes','Limit 8 m.')]]
  tgt['units']=[{'id':'main','text':'一条原创注释如下。','state':'COMPLETE'},{'id':'note','text':'限值 8 m。','state':'COMPLETE'}]
  src['footnotes']=[{'id':'fn','anchor':'main','body':'Limit 8 m.'}];tgt['footnotes']=[{'id':'fn','anchor':'main','body':'限值 999 m。'}]
  if spec['version']>=2:
   src['footnotes'][0]['body_unit_id']='note';tgt['footnotes'][0]['body_unit_id']='note'
 elif case=='R3a':tgt['units'][0]['text']+='另加999项。'
 elif case=='R3b':tgt['units'][0]['text']='示例小车行进6 m，耗时4 s。BX传感器应保持工作。'
 sync(root,spec,src,tgt)
 if case.startswith('R2'):
  req=read(root,'request.json');req['project']=sync(root,spec);put(root,'request.json',req)
  snapshot=run(root,'workflow.py','snapshot.json','snapshot');before=binding(spec)
  if case=='R2a':spec['term_rules'][0]['forbidden_targets'].append('传感器')
  else:spec['pollution_tokens'].append('传感器')
  req['project']=sync(root,spec);req['record']={'path':'snapshot.json','sha256':h(root/'snapshot.json')};put(root,'request.json',req)
  results[case]={'snapshot_initial':snapshot,'new_check':run(root,'term_guard.py' if case=='R2a' else 'check_invariants.py','check.json'),'binding_changed':before!=binding(spec),'verify':run(root,'workflow.py','verify.json','verify-snapshot'),'cache':run(root,'workflow.py','cache.json','cache')}
 else:results[case]=run(root,'check_invariants.py','result.json')
record={'mode':'SYNTHETIC_TEST_ONLY','environment':{'python':sys.version.split()[0],'pypdf':meta.version('pypdf'),'jsonschema':meta.version('jsonschema'),'platform':sys.platform},'cases':results,'commands':commands}
with Path(a.result).open('x',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print('SYNTHETIC_CASES_RECORDED; NOT_REAL_QA')

expected=(results['R1a']['errors']==['TABLE_TARGET_INVALID'] and
          results['R1b']['errors']==['FOOTNOTE_BODY_CONFLICT'] and
          results['R3a']['errors']==['NUMBERS_MISMATCH'] and results['R3b']['status']=='PASS')
for key in ('R2a','R2b'):
    v=results[key]
    expected=expected and v['snapshot_initial']['status']=='PASS' and v['binding_changed'] and v['new_check']['status']=='FAIL'
    expected=expected and all(v[k]['errors']==['EVIDENCE_BINDING_MISMATCH'] and v[k]['exit_code']==2 for k in ('verify','cache'))
raise SystemExit(0 if expected else 1)
