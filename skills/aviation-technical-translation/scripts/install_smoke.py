"""Headless installation smoke test using three supplied font files and a private temporary PDF."""
import argparse
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pdf_typecheck import report, name_key


def smoke(body,heading,latin, expected=('SimSun','SimHei','TimesNewRomanPSMT')):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
    import pymupdf as fitz
    import pypdfium2 as pdfium
    with TemporaryDirectory() as tmp:
        out=Path(tmp)
        for key,path in [('Body',body),('Heading',heading),('Western',latin)]:
            pdfmetrics.registerFont(TTFont(key,str(path),subfontIndex=0))
        sample=out/'smoke.pdf'
        c=canvas.Canvas(str(sample),pagesize=(400,240))
        c.setFont('Heading',16)
        c.drawString(24,198,'航空验证')
        c.setFont('Body',12)
        for y in (158,140):
            c.drawString(24,y,'语境与数据')
            c.setFont('Western',12)
            c.drawString(96,y,'EASA 12')
            c.setFont('Body',12)
        c.save()
        faces={k:pdfmetrics.getFont(k).face.name.decode() for k in ('Body','Heading','Western')}
        for key,face in zip(('Body','Heading','Western'),expected):
            if name_key(faces[key]) != name_key(face):
                raise ValueError(f'{key}: expected {face}, font file supplies {faces[key]}')
        spec={'roles':{'body':{'cjk':[faces['Body']],'latin':[faces['Western']],'size_pt':12,'leading_pt':18},
                       'heading':{'cjk':[faces['Heading']],'latin':[faces['Western']],'size_pt':16}},
              'regions':[{'id':'head','page':1,'rect':[18,22,274,55],'role':'heading','scripts':['cjk']},
                         {'id':'body','page':1,'rect':[18,64,275,108],'role':'body','scripts':['cjk','latin'],'leading':True}]}
        path=out/'spec.json'
        path.write_text(json.dumps(spec),encoding='utf8')
        measurement=report(sample,path)
        if measurement['status']!='PASS':
            raise ValueError('Unexpected embedded font or baseline: '+str(measurement['checks']))
        with fitz.open(sample) as d: t1=d[0].get_text()
        t2=PdfReader(BytesIO(sample.read_bytes())).pages[0].extract_text()
        if not all(all(w in txt for w in ('航空验证','语境与数据','EASA 12')) for txt in (t1,t2)):
            raise ValueError('Extraction mismatch')
        with pdfium.PdfDocument(str(sample)) as doc:
            pg=doc[0]
            bmp=pg.render(scale=2)
            try:
                image=bmp.to_pil().convert('L')
                if image.getextrema()[0]>150:raise ValueError('Blank render')
            finally:
                bmp.close()
                pg.close()
    return {'status':'PASS','registered_faces':faces,'embedded_type_checks':measurement['checks'],
            'extractors':['PyMuPDF','pypdf'],'renderer':'PDFium','native_clipboard':'NOT_TESTED'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('body','heading','latin'):p.add_argument('--'+k,type=Path,required=True)
    for role,default in [('body','SimSun'),('heading','SimHei'),('latin','TimesNewRomanPSMT')]:
        p.add_argument('--expect-'+role,default=default,help='Expected embedded PostScript face name')
    args=p.parse_args()
    print(json.dumps(smoke(args.body,args.heading,args.latin,(args.expect_body,args.expect_heading,args.expect_latin)),ensure_ascii=False,indent=2))
