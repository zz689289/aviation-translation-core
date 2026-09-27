"""Locate source units in a simple text PDF. This never compares Chinese semantics."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import contextlib
import io
import logging
import re
from common import Invalid, summary, cli
from contracts import load_project

def normalize(s): return re.sub(r'\s+',' ',s).strip()

def inspect_pdf(store,spec,src):
    try:
        from pypdf import PdfReader
    except ImportError: raise Invalid('DEPENDENCY_PYPDF_MISSING') from None
    logger=logging.getLogger('pypdf'); old=logger.disabled; logger.disabled=True
    try:
        with contextlib.redirect_stderr(io.StringIO()),contextlib.redirect_stdout(io.StringIO()):
            reader=PdfReader(io.BytesIO(store.read(spec['pdf']['path'],spec['pdf']['sha256'])),strict=True)
            if reader.is_encrypted: raise Invalid('PDF_ENCRYPTED_UNSUPPORTED')
            root=reader.trailer['/Root']
            if '/OpenAction' in root or '/AA' in root: raise Invalid('PDF_ACTIVE_CONTENT_UNSUPPORTED')
            if len(reader.pages)!=spec['page_count']: raise Invalid('PDF_PAGE_COUNT_MISMATCH')
            for page_num in spec['pages']:
                page=reader.pages[page_num-1]
                if page.get('/Annots') or page.get('/Resources',{}).get('/XObject'):
                    raise Invalid('PDF_NON_TEXT_LAYER_UNSUPPORTED')
                text=page.extract_text()
                if not text or not text.strip(): raise Invalid('PDF_EXTRACTION_FAILED')
                expected=' '.join(u['text'] for u in src['units'] if u['page']==page_num)
                if normalize(text)!=normalize(expected): raise Invalid('PDF_SOURCE_MAPPING_INCOMPLETE')
    except Invalid: raise
    except Exception: raise Invalid('PDF_EXTRACTION_FAILED') from None
    finally: logger.disabled=old

def run(store,spec):
    src,tgt=load_project(store,spec)
    inspect_pdf(store,spec,src)
    return summary('source_location',pages=len(spec['pages']),units=len(src['units']),scope=spec['scope'])

if __name__=='__main__': raise SystemExit(cli(run))
