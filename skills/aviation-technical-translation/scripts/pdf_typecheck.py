"""Check live PDF text against per-role, per-script type specifications in points."""
import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from common import atomic_write_json, ensure_distinct_paths, load_json, sha256_file
from pdf_spacing import baselines, rectangle


def name_key(value):
    # PDF subset identifiers and ReportLab TTC subfont suffixes are not font-family names.
    value = re.sub(r'^[A-Z]{6}\+', '', value)
    return re.sub(r'[\s_-]', '', re.sub(r'-\d+$', '', value)).casefold()


def script(text):
    if re.fullmatch(r'[\u3400-\u9fff\uf900-\ufaff\U00020000-\U0002ffff]', text):
        return 'cjk'
    if re.fullmatch(r'[0-9A-Za-z\u00c0-\u024f]', text):
        return 'latin'
    return None


def measure(page, region, style, fitz):
    rect=rectangle(page,region['rect'],fitz)
    target_size=style['size_pt']
    if not isinstance(target_size,(float,int)) or not math.isfinite(target_size) or target_size<=0:
        raise ValueError('size_pt must be a positive finite number')
    required=set(region['scripts'])
    if not required or not required <= {'cjk','latin'}:
        raise ValueError('Specify cjk and/or latin for the actual text present')
    allowed={}
    for lang in ('cjk','latin'):
        aliases=style[lang]
        if not isinstance(aliases,list) or not aliases or not all(isinstance(n,str) and n.strip() for n in aliases):
            raise ValueError('Give explicit PDF face names as a nonempty list per script')
        allowed[lang]={name_key(n) for n in aliases}
    observed=Counter()
    failures=[]
    resources={name_key(r[3]) for r in page.get_fonts(full=True) if r[1] not in ('n/a','')}
    raw=page.get_text('rawdict',clip=rect,flags=fitz.TEXTFLAGS_RAWDICT & ~fitz.TEXT_PRESERVE_IMAGES)
    for block in raw['blocks']:
        for line in block.get('lines',[]):
            for span in line['spans']:
                if not span.get('alpha',255):
                    continue
                for char in span['chars']:
                    lang=script(char['c'])
                    if lang:
                        observed[lang,span['font'],round(span['size'],2)]+=1
    for (lang,name,size),count in observed.items():
        normalized=name_key(name)
        if normalized not in allowed[lang] or abs(size-target_size)>0.12 or normalized not in resources:
            failures.append({'script':lang,'font':name,'size_pt':size,'characters':count,'embedded_name_found':normalized in resources})
    missing=sorted(required-{item[0] for item in observed})
    deltas=[]
    if region.get('leading',False):
        lead=style['leading_pt']
        if not isinstance(lead,(float,int)) or not math.isfinite(lead) or lead<=0:
            raise ValueError('leading_pt must be positive')
        rows=baselines(page,rect,fitz)
        deltas=[round(b-a,3) for a,b in zip(rows,rows[1:])]
        if not deltas:missing.append('adjacent_body_baselines')
        elif any(abs(x-lead)>.2 for x in deltas): failures.append({'expected_leading':lead})
    return {'status':'FAIL' if failures else ('UNMEASURED' if missing else 'PASS'),
            'observed':[{'script':lang,'font':name,'size_pt':size,'characters':n} for (lang,name,size),n in observed.items()],
            'baseline_deltas_pt':deltas,'missing':missing,'failures':failures}


def report(pdf,spec):
    import pymupdf as fitz
    config=load_json(spec)
    checks=[]
    ids=set()
    with fitz.open(pdf) as doc:
        for r in config['regions']:
            if not isinstance(r.get('id'),str) or not r['id'] or r['id'] in ids:raise ValueError('Missing/duplicate region id')
            ids.add(r['id'])
            if type(r['page'])!=int or not 1<=r['page']<=len(doc):raise ValueError('Invalid page')
            page=doc[r['page']-1]
            result=({'status':'UNMEASURED','reason':'rotated page; inspect render'} if page.rotation
                    else measure(page,r,config['roles'][r['role']],fitz))
            checks.append({**r,**result})
    if not checks:raise ValueError('At least one region is required')
    return {'status':'PASS' if all(c['status']=='PASS' for c in checks) else 'REVIEW',
            'pdf_sha256':sha256_file(pdf),'spec_sha256':sha256_file(spec),'scope':'declared text regions','checks':checks}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf',type=Path)
    parser.add_argument('--spec',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    try:
        ensure_distinct_paths({'pdf':args.pdf,'spec':args.spec,'output':args.output})
        if args.output.exists():raise ValueError('Supply a new output path')
        value=report(args.pdf,args.spec)
        atomic_write_json(args.output,value)
        print(value['status'])
        sys.exit(int(value['status']!='PASS'))
    except (OSError,ValueError,TypeError,KeyError) as exc:
        sys.exit(f'Invalid type check: {exc}')
