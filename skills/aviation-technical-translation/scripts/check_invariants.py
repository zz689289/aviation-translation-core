"""Check evidence-derived structured invariants, NOT English semantic equivalence.

Expected values must be extracted from source/approved evidence independently of
candidate output. Counts are project data. JSON-only isolated adapter; no Word.
"""
from collections import Counter
import argparse,json
from pathlib import Path
from common import load_json,atomic_write_json

def check(s):
    failures=[]
    a={x['id']:x for x in s.get('source_units',[])};b={x['id']:x for x in s.get('target_units',[])}
    if len(a)!=len(s.get('source_units',[])) or len(b)!=len(s.get('target_units',[])):failures.append('DUPLICATE_UNIT_ID')
    for i in sorted(set(a)-set(b)):failures.append('SOURCE_UNIT_OMITTED:'+i)
    for i in sorted(set(b)-set(a)):failures.append('TARGET_UNIT_ADDED:'+i)
    for i in sorted(set(a)&set(b)):
        target_text=b[i].get('text','')
        if not isinstance(target_text,str):
            failures.append('TARGET_TEXT_INVALID:'+i)
            target_text=''
        for k in ('identifiers','numbers','units','symbols','marker'):
            if k in a[i] and a[i][k]!=b[i].get(k):failures.append(k.upper()+'_HARD_FAIL:'+i)
        # Exact, source-derived objects that must remain executable/citable.
        # Narrative algorithms still require translation; a role alone is not
        # permission to skip prose or translate code/BibTeX tokens.
        if a[i].get('preserve_exact') is True:
            if not a[i].get('source_evidence'):
                failures.append('EXACT_OBJECT_EVIDENCE_MISSING:'+i)
            if not isinstance(a[i].get('text'),str) or not isinstance(b[i].get('text'),str):
                failures.append('EXACT_OBJECT_TEXT_MISSING_OR_INVALID:'+i)
            elif a[i]['text']!=b[i]['text']:
                failures.append('EXACT_OBJECT_CHANGED:'+i)
        for rule in a[i].get('canonical_rules',[]):
            if not rule.get('approval_evidence') or not rule.get('source_context'):
                failures.append('CANONICAL_RULE_EVIDENCE_MISSING:'+i);continue
            if rule['required_target'] not in target_text:failures.append('CANONICAL_TERM_REQUIRED:'+i)
        for token in s.get('forbidden_targets',[]):
            if token in target_text:failures.append('REGRESSION_SENTINEL:'+i+':'+token)
        if a[i].get('role') not in ('header','footer') and any(t in target_text for t in ('©European Union Aviation Safety Agency','All rights reserved','ISO9001 Certified')):
            failures.append('HEADER_FOOTER_CONTAMINATION:'+i)
    notes=s.get('footnotes',{})
    refs=notes.get('references',[]);bodies=notes.get('bodies',[]);expected=notes.get('expected_bindings',[])
    rid=[x['id'] for x in refs];bid=[x['id'] for x in bodies]
    if len(bid)!=len(set(bid)):failures.append('DUPLICATE_FOOTNOTE_BODY_ID')
    if Counter(rid)!=Counter(x['id'] for x in expected):failures.append('FOOTNOTE_OCCURRENCE_COVERAGE_FAIL')
    if set(rid)!=set(bid):failures.append('ORPHAN_FOOTNOTE_REFERENCE_OR_BODY')
    if [(x['id'],x['anchor']) for x in refs]!=[(x['id'],x['anchor']) for x in expected]:failures.append('FOOTNOTE_ANCHOR_ORDER_FAIL')
    # Body strings deliberately NOT required to be globally unique.
    for e in s.get('toc',[]):
        if len({e['saved_cache_page'],e['pdf_toc_page'],e['actual_heading_page']})!=1:failures.append('STALE_TOC_CACHE:'+e['id'])
    for e in s.get('heading_geometry',[]):
        if not e.get('source_geometry_evidence'):failures.append('GEOMETRY_EVIDENCE_MISSING:'+e['id'])
        if e['actual_text_x_pt']!=e['expected_text_x_pt']:failures.append('HEADING_ALIGNMENT_FAIL:'+e['id'])
    cells=s.get('table_mapping',{})
    coords=cells.get('source_coordinates',[]);mapping=cells.get('coordinate_to_render_cell',{})
    if len(coords)!=len(set(coords)) or set(coords)!=set(mapping):failures.append('TABLE_SOURCE_COORDINATE_COVERAGE_FAIL')
    actual=cells.get('render_cell_inventory',[])
    if cells and (not actual or len(actual)!=len(set(actual)) or not all(isinstance(v,str) and v.strip() for v in actual)):
        failures.append('RENDER_CELL_INVENTORY_MISSING_OR_INVALID')
    groups={}
    for k,v in mapping.items():
        if not isinstance(v,str) or not v.strip() or v not in actual:
            failures.append('TABLE_TARGET_COORDINATE_INVALID:'+k);continue
        groups.setdefault(v,[]).append(k)
    if set(actual)-set(groups):failures.append('UNMAPPED_RENDER_CELL')
    aliases={frozenset(x) for x in cells.get('approved_repeated_header_aliases',[])}
    for group in groups.values():
        if len(group)>1 and frozenset(group) not in aliases:failures.append('UNAPPROVED_MANY_TO_ONE_CELL_MAPPING')
    return {'mechanical_status':'FAIL' if failures else 'PASS','failures':failures,
            'semantic_qa':'NOT_PERFORMED_BY_THIS_CHECKER','visual_qa':'NOT_PERFORMED_BY_THIS_CHECKER',
            'source_unit_count':len(a),'target_unit_count':len(b)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--spec',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists() or a.output.resolve()==a.spec.resolve():raise SystemExit('Refuse overwrite')
    r=check(load_json(a.spec));atomic_write_json(a.output,r);print(r['mechanical_status']);raise SystemExit(0 if r['mechanical_status']=='PASS' else 1)
if __name__=='__main__':main()
