"""Compare independent source-derived fields; no semantic or human approval."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from collections import Counter
from common import Invalid, summary, cli
from contracts import load_project,tokens,FIELDS
from compare_source import inspect_pdf

def structural(src,tgt,layers):
    failures=[]
    su={u['id']:u for u in src['units']};tu={u['id']:u for u in tgt['units']}
    a=src['footnotes'];b=tgt['footnotes']
    if (layers['footnotes']=='PRESENT')!=bool(a): failures.append('FOOTNOTE_LAYER_CONFLICT')
    if len({x['id'] for x in a})!=len(a) or len({x['id'] for x in b})!=len(b): failures.append('FOOTNOTE_DUPLICATE_ID')
    key=lambda x:(x['id'],x['anchor'],x.get('body_unit_id'))
    if list(map(key,a))!=list(map(key,b)): failures.append('FOOTNOTE_BINDING')
    for notes,units in ((a,su),(b,tu)):
        refs=[x.get('body_unit_id') for x in notes]
        if len(set(refs))!=len(refs): failures.append('FOOTNOTE_BODY_REUSED')
        for x in notes:
            ref=x.get('body_unit_id')
            if x['anchor'] not in units: failures.append('FOOTNOTE_ANCHOR_MISSING')
            if not x['body'].strip(): failures.append('FOOTNOTE_BODY_EMPTY')
            if ref not in units or ref==x['anchor']:
                failures.append('FOOTNOTE_BODY_REFERENCE');continue
            if ref not in su or su[ref].get('layer')!='footnotes': failures.append('FOOTNOTE_BODY_LAYER')
            if x['body']!=units[ref].get('text'): failures.append('FOOTNOTE_BODY_CONFLICT')
    if {x.get('body_unit_id') for x in a}!={k for k,v in su.items() if v.get('layer')=='footnotes'}:
        failures.append('FOOTNOTE_UNIT_COVERAGE')
    if {x['id'] for x in src['tables']}!={x['id'] for x in tgt['tables']}: failures.append('TABLE_SET_MISMATCH')
    if (layers['table_cells']=='PRESENT')!=bool(src['tables']): failures.append('TABLE_LAYER_CONFLICT')
    if len({x['id'] for x in src['tables']})!=len(src['tables']) or len({x['id'] for x in tgt['tables']})!=len(tgt['tables']): failures.append('TABLE_DUPLICATE_ID')
    covered=set()
    for table in src['tables']:
        coords=table['coordinates'];covered.update(coords.values())
        if any(k not in su or su[k].get('layer')!='table_cells' for k in coords.values()): failures.append('TABLE_SOURCE_REFERENCE')
        other=next((t for t in tgt['tables'] if t['id']==table['id']),None)
        if not other: continue
        mapping=other['mapping'];cells=other['cells']
        if not coords or set(coords)!=set(mapping) or not set(coords.values())<=set(su): failures.append('TABLE_COORDINATE_COVERAGE')
        if not cells or len(set(cells))!=len(cells) or any(not c.strip() for c in cells): failures.append('TABLE_CELL_INVENTORY')
        if any(not isinstance(v,str) or not v or v not in cells or v not in tu for v in mapping.values()): failures.append('TABLE_TARGET_INVALID');continue
        if set(mapping.values())!=set(cells): failures.append('TABLE_UNMAPPED_CELL')
        aliases={frozenset(x) for x in table['repeated_header_aliases']}
        if any(not group or not group<=set(coords) for group in aliases): failures.append('TABLE_ALIAS_INVALID')
        for cell in cells:
            group={k for k,v in mapping.items() if v==cell}
            if len(group)>1 and frozenset(group) not in aliases: failures.append('TABLE_UNAPPROVED_MERGE')
            refs={coords[k] for k in group if k in coords}
            if cell not in refs: failures.append('TABLE_CONTENT_BINDING');continue
            # An approved repeated header can share an actual target unit only
            # when every source occurrence and every checked target agree.
            for ref in refs:
                if ref not in su or ref not in tu or cell not in su:
                    failures.append('TABLE_CONTENT_BINDING');continue
                if su[ref].get('text')!=su[cell].get('text') or su[ref].get('expected')!=su[cell].get('expected') or tu[ref].get('text')!=tu[cell].get('text'):
                    failures.append('TABLE_ALIAS_CONTENT_CONFLICT')
    if covered!={k for k,v in su.items() if v.get('layer')=='table_cells'}: failures.append('TABLE_UNIT_COVERAGE')
    return failures

def run(store,spec):
    src,tgt=load_project(store,spec); inspect_pdf(store,spec,src)
    failures=[]; targets={u['id']:u for u in tgt['units']}
    for unit in src['units']:
        observed=tokens(targets[unit['id']]['text'],spec['vocabulary'])
        for k in FIELDS:
            if unit['expected'][k]!=observed[k]: failures.append(k.upper()+'_MISMATCH')
        if any(t in targets[unit['id']]['text'] for t in spec['pollution_tokens']): failures.append('POLLUTION_TOKEN')
    failures+=structural(src,tgt,spec['layers'])
    return summary('source_target_invariants',failures,units=len(src['units']),scope=spec['scope'])

if __name__=='__main__': raise SystemExit(cli(run))
