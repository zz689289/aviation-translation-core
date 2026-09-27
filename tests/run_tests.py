"""Standard-library runner; explicit private work directory; sanitized results."""
import argparse,json,sys,tempfile,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
for p in ('scripts','examples','tests'):sys.path.insert(0,str(root/p))
import test_core

def main():
    a=argparse.ArgumentParser();a.add_argument('--work',required=True);a.add_argument('--results',required=True);args=a.parse_args()
    work=Path(args.work);work.mkdir(parents=True,exist_ok=True);tempfile.tempdir=str(work);test_core.WORK=str(work)
    dest=Path(args.results)
    if dest.exists():raise SystemExit('RESULT_EXISTS')
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_core)
    # Detailed tracebacks are private: only statuses and test IDs enter shareable JSON.
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    record={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
      'passed':result.testsRun-len(result.failures)-len(result.errors)-len(result.skipped),
      'failed_ids':[x.id() for x,_ in result.failures+result.errors],
      'skips':[{'id':x.id(),'reason':reason} for x,reason in result.skipped],
      'host_integration':'NOT_RUN','human_approved':False,'released':False}
    dest.write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    return 0 if result.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
