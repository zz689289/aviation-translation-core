"""Verify source-scoped terminology decisions over aligned objects and page joins."""
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

from common import atomic_write_json, ensure_distinct_paths, load_json, load_jsonl, sha256_file


def normalized(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFC', text)).strip()


def excerpts(rule, objects):
    if 'groups' in rule:
        for group in rule['groups']:
            if not isinstance(group,list) or not group or len(set(group))!=len(group):
                raise ValueError('Use nonempty ordered groups of distinct object IDs')
            yield [objects[i] for i in group]
    else:
        for obj in objects.values():
            yield [obj]


def inspect(rows,rules):
    if not rows or not rules:raise ValueError('Expect a nonempty inventory and decision set')
    objects={r['id']:r for r in rows}
    if len(objects)!=len(rows):raise ValueError('Duplicate source id')
    checks=[]
    for rule in rules:
        source_pattern=re.compile(rule['source_pattern'],re.I)
        required=[re.compile(p,re.I) for p in rule.get('required_target',[])]
        forbidden=[re.compile(p,re.I) for p in rule.get('forbidden_target',[])]
        if not required and not forbidden:raise ValueError('Missing target decision')
        checked=[]
        for group in excerpts(rule,objects):
            source=normalized(' '.join(r['source'] for r in group))
            if not source_pattern.search(source):
                if 'groups' in rule:raise ValueError('Selected source group does not match decision: '+str(rule['id']))
                continue
            target=normalized(' '.join(r['target'] for r in group))
            missing=[p.pattern for p in required if not p.search(target)]
            rejected=[p.pattern for p in forbidden if p.search(target)]
            checked.append({'ids':[r['id'] for r in group], 'missing':missing,'forbidden':rejected,
                            'status':'REVIEW' if missing or rejected or not target else 'PASS'})
        checks.append({'decision':rule['id'],'matches':checked,
                       'status':'UNMEASURED' if not checked else ('PASS' if all(x['status']=='PASS' for x in checked) else 'REVIEW')})
    return {'status':'PASS' if all(x['status']=='PASS' for x in checks) else 'REVIEW',
            'scope':'Declared source-context decisions only. Evaluate meaning independently.', 'checks':checks}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('content','decisions','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:
        ensure_distinct_paths(vars(args))
        if args.output.exists():raise ValueError('Supply a new report path')
        result=inspect(load_jsonl(args.content),load_json(args.decisions)['rules'])
        result.update(content_sha256=sha256_file(args.content),decisions_sha256=sha256_file(args.decisions))
        atomic_write_json(args.output,result)
        print(result['status'])
        sys.exit(int(result['status']!='PASS'))
    except (KeyError,TypeError,ValueError,OSError,re.error) as exc:
        sys.exit(f'Invalid context check: {exc}')
