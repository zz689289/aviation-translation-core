"""Create an original fixture and separate shareable mechanical/QA summaries."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import Store,Invalid,SafeParser
from original_fixture import create
from term_guard import run as terms
from compare_source import run as locate
from check_invariants import run as invariants
from workflow import run as workflow

def main():
    p=SafeParser();p.add_argument('--output',required=True);a=p.parse_args()
    root=Path(a.output)
    # Caller must choose a new empty directory; source/target contexts stay private.
    store=Store(root);spec=create(root)
    for name,fn in [('terms',terms),('source_location',locate),('invariants',invariants)]:
        result=fn(Store(root),spec)
        store.write(name+'.summary.json',result)
        if result['mechanical_status']!='PASS':return 1
    request=store.json('request.json')
    store.write('handoff.summary.json',workflow(Store(root),request,'snapshot'))
    print('DEMO_MECHANICAL_PASS; HOST_QA_NOT_RUN; HUMAN_FALSE; RELEASED_FALSE')
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:print('DEMO_FAILED',file=sys.stderr);raise SystemExit(2)
