"""The legacy-named --workflow wrapper must enforce the same input contract."""
import json,subprocess,sys,tempfile,unittest
from pathlib import Path
class Adapter(unittest.TestCase):
    def test_workflow_wrapper_real_cli(self):
        with tempfile.TemporaryDirectory() as d:
            for i,(data,expected) in enumerate([({},2),({'findings':'invalid'},2),({'findings':[]},0),({'findings':[{'id':'pending','status':'PENDING'}]},0)]):
                p=Path(d)/f'input-{i}.json';p.write_text(json.dumps(data),encoding='utf-8');out=Path(d)/f'result-{i}.json'
                r=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('build_escalation_queue.py')),'--workflow','--input',str(p),'--output',str(out)],capture_output=True,text=True)
                self.assertEqual(r.returncode,expected,(data,r.stdout,r.stderr))
                if i==3:
                    report=json.loads(out.read_text(encoding='utf-8'));self.assertTrue(report['acceptance_blocked']);self.assertEqual(report['manual_handoff'],[])
if __name__=='__main__':unittest.main(verbosity=2)
