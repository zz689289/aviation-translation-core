"""Explicit source/target evidence contract, not an authorship or QA authenticator."""
import re
from common import Invalid, validate, digest
FIELDS=('numbers','units','identifiers','symbols','markers')
LAYERS=('ordinary','table_cells','formulas','captions','image_semantics','footnotes','references','front_back_matter','branding_fields')

def tokens(text, vocabulary):
    result={'numbers':re.findall(r'(?<![A-Za-z0-9_.+-])[+-]?[0-9]+(?:\.[0-9]+)?(?![A-Za-z0-9_]|\.[0-9])',text),
            'markers':re.findall(r'\([a-z]+\)',text)}
    for k in ('units','identifiers','symbols'):
        hits=[]
        for term in vocabulary[k]:
            hits.extend((m.start(),m.group()) for m in re.finditer(r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])',text))
        result[k]=[v for _,v in sorted(hits)]
    return result

def load_project(store, spec):
    validate(spec,'project.schema.json')
    src=store.json(spec['source']['path'],spec['source']['sha256'])
    tgt=store.json(spec['target']['path'],spec['target']['sha256'])
    store.read(spec['pdf']['path'],spec['pdf']['sha256'])
    validate(src,'source.schema.json'); validate(tgt,'target.schema.json')
    if src['basis']!='INDEPENDENT_SOURCE' or src['pdf_sha256']!=spec['pdf']['sha256']:
        raise Invalid('SOURCE_EVIDENCE_BINDING')
    if src['derived_from_target']: raise Invalid('TARGET_DERIVED_EXPECTATIONS')
    if not spec['inspection']['rationale'].strip(): raise Invalid('INSPECTION_RATIONALE_REQUIRED')
    if spec['inspection']['pdf_sha256']!=spec['pdf']['sha256']:
        raise Invalid('INSPECTION_BINDING')
    if set(spec['layers'])!=set(LAYERS): raise Invalid('LAYERS_MISSING')
    present={k for k,v in spec['layers'].items() if v=='PRESENT'}
    if any(v=='UNSUPPORTED' for v in spec['layers'].values()): raise Invalid('LAYER_UNSUPPORTED')
    if any(u['layer'] not in present for u in src['units']): raise Invalid('LAYER_DECLARATION_CONFLICT')
    if present!={u['layer'] for u in src['units']}: raise Invalid('PRESENT_LAYER_UNMAPPED')
    pages=spec['pages']
    if spec['scope']=='full' and pages!=list(range(1,spec['page_count']+1)):
        raise Invalid('FULL_PAGE_SCOPE_INCOMPLETE')
    if any(n>spec['page_count'] for n in pages): raise Invalid('PAGE_OUTSIDE_SOURCE')
    if set(pages)!={u['page'] for u in src['units']}: raise Invalid('SCOPE_UNMAPPED')
    ids=[u['id'] for u in src['units']]; tids=[u['id'] for u in tgt['units']]
    if len(set(ids))!=len(ids) or len(set(tids))!=len(tids): raise Invalid('DUPLICATE_UNIT_ID')
    if set(ids)!=set(tids): raise Invalid('SOURCE_TARGET_UNIT_SET_MISMATCH')
    if any(not u['text'].strip() for u in src['units']+tgt['units']): raise Invalid('EMPTY_CONTENT')
    if any(u['state']!='COMPLETE' for u in tgt['units']): raise Invalid('UNFINISHED_WORK')
    for u in src['units']:
        declared=set(spec['vocabulary']['units']+spec['vocabulary']['identifiers'])
        if set(re.findall(r'\b[A-Z]{2,}\b',u['text']))-declared: raise Invalid('TOKEN_VOCABULARY_INCOMPLETE')
        if set(re.findall(r'(?<=\d)\s+(kg|m|s|Hz|Pa)\b',u['text']))-declared: raise Invalid('TOKEN_VOCABULARY_INCOMPLETE')
        if u['evidence_sha256']!=spec['pdf']['sha256']: raise Invalid('UNIT_EVIDENCE_BINDING')
        if tokens(u['text'],spec['vocabulary'])!=u['expected']: raise Invalid('SOURCE_EXPECTATIONS_INCOMPLETE')
    if src['synthetic_test_only']!=tgt['synthetic_test_only']: raise Invalid('EVIDENCE_MODE_MISMATCH')
    return src,tgt

def binding(spec):
    # Bind the entire validated contract, including all rule lists and versions.
    # Object key order is canonicalized by digest; array order remains significant.
    return digest({'binding_contract':2,'project':spec})
