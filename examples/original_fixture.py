"""AI-assisted original neutral training example, not institutional material.
SYNTHETIC_TEST_ONLY. English/Chinese are authored locally; no translation API.
"""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from common import Store,digest

ENGLISH='A sample cart travels 6 m in 4 s. The BX sensor should remain active.'
# Preserve numeric source sequence in this controlled fixture, as the checker is ordered.
CHINESE='示例小车行进 6 m，耗时 4 s。BX 传感器应保持工作。'

def make_pdf(path,pages):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
    writer=PdfWriter()
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    ref=writer._add_object(font)
    for lines in pages:
        page=writer.add_blank_page(width=400,height=300)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):ref})})
        safe=lines.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        stream=DecodedStreamObject();stream.set_data(('BT /F1 10 Tf 15 260 Td ('+safe+') Tj ET').encode('ascii'))
        page[NameObject('/Contents')]=writer._add_object(stream)
    with path.open('xb') as f:writer.write(f)

def create(root):
    root=Path(root);store=Store(root)
    if any(root.iterdir()):raise ValueError('EMPTY_FIXTURE_DIRECTORY_REQUIRED')
    make_pdf(root/'source.pdf',[ENGLISH])
    ph=digest((root/'source.pdf').read_bytes())
    # Authored from the English independently, never extracted from target text.
    expected={'numbers':['6','4'],'units':['m','s'],'identifiers':['BX'],'symbols':[],'markers':[]}
    source={'contract_version':2,'basis':'INDEPENDENT_SOURCE','derived_from_target':False,'synthetic_test_only':True,'pdf_sha256':ph,
      'units':[{'id':'unit_a','page':1,'layer':'ordinary','text':ENGLISH,'evidence_sha256':ph,'expected':expected}], 'footnotes':[],'tables':[]}
    target={'contract_version':2,'synthetic_test_only':True,'units':[{'id':'unit_a','text':CHINESE,'state':'COMPLETE'}],'footnotes':[],'tables':[]}
    store.write('source.json',source);store.write('target.json',target)
    def ref(n):return {'path':n,'sha256':digest((root/n).read_bytes())}
    layers={k:'ABSENT' for k in ['ordinary','table_cells','formulas','captions','image_semantics','footnotes','references','front_back_matter','branding_fields']};layers['ordinary']='PRESENT'
    project={'version':2,'scope':'full','pages':[1],'page_count':1,'source':ref('source.json'),'target':ref('target.json'),'pdf':ref('source.pdf'),
      'inspection':{'pdf_sha256':ph,'rationale':'SYNTHETIC_TEST_ONLY original one-page plain text inventory.'},'layers':layers,
      'vocabulary':{'units':['m','s'],'identifiers':['BX'],'symbols':['=']},'pollution_tokens':['DEMO_INTERNAL_STAMP'],
      'term_rules':[{'id':'sensor','forms':['sensor','sensors'],'case_sensitive':False,'forbidden_targets':['演示禁用词'],'required_target':'传感器'}]}
    store.write('project.json',project)
    request={'project':ref('project.json'),'record':None,'findings':[],'impact':{'kind':'local','changed_ids':[],'dependent_ids':[]}}
    store.write('request.json',request)
    return project
