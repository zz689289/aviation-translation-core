"""Independent per-rule matching, including overlaps. No automatic disambiguation."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import re
from common import summary,cli
from contracts import load_project
from compare_source import inspect_pdf

def matches(text,rule):
    pattern='|'.join(re.escape(x) for x in sorted(rule['forms'],key=len,reverse=True))
    return list(re.finditer(r'(?<!\w)(?:'+pattern+r')(?!\w)',text,0 if rule['case_sensitive'] else re.IGNORECASE))

def run(store,spec):
    src,tgt=load_project(store,spec); inspect_pdf(store,spec,src)
    targets={u['id']:u['text'] for u in tgt['units']}; failures=[]; hits=0
    for rule in spec['term_rules']:
        for u in src['units']:
            found=matches(u['text'],rule);hits+=len(found)
            if found and any(x in targets[u['id']] for x in rule['forbidden_targets']):failures.append('FORBIDDEN_TRANSLATION')
            if found and rule['required_target'] and rule['required_target'] not in targets[u['id']]:failures.append('REQUIRED_TRANSLATION_MISSING')
    return summary('term_context',failures,occurrences=hits,rules=len(spec['term_rules']),scope=spec['scope'])

if __name__=='__main__':raise SystemExit(cli(run))
