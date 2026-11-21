"""OOXML-only inspection/preparation and post-Word validation. Never drives a UI."""
import argparse, hashlib, json, re, shutil, sys, zipfile, posixpath
from collections import defaultdict, Counter
from pathlib import Path
from lxml import etree as E
from pypdf import PdfReader

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
EXTERNAL = {'INCLUDETEXT','INCLUDEPICTURE','LINK','DDE','DDEAUTO','DATABASE','RD','IMPORT'}
INTERNAL = {'TOC','PAGEREF','REF','NOTEREF','SEQ','PAGE','NUMPAGES','SECTION','SECTIONPAGES','STYLEREF','DOCPROPERTY','DOCVARIABLE','IF','QUOTE','COMPARE','=', 'SYMBOL','HYPERLINK','SHAPE'}

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def dump(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def inventory(path):
    result = dict(Path=str(path), SHA256=digest(path), Fields=[], Relationships=[], Dependencies=[], Errors=[], Bookmarks=[], UpdateFields=[], Dirty=[],StoryParts={},HasTextboxes=False)
    with zipfile.ZipFile(path) as z:
        rels={n.get('Id'):posixpath.normpath(posixpath.join('word',n.get('Target',''))) for n in E.fromstring(z.read('word/_rels/document.xml.rels'))}
        document=E.fromstring(z.read('word/document.xml'))
        for section,s in enumerate(document.findall('.//w:sectPr',NS),1):
            for n in s:
                kind=E.QName(n).localname
                if kind not in ('headerReference','footerReference'):continue
                typ=n.get('{'+W+'}type');target=rels[n.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
                story={('headerReference','default'):7,('headerReference','first'):10,('headerReference','even'):6,('footerReference','default'):9,('footerReference','first'):11,('footerReference','even'):8}[(kind,typ)]
                result['StoryParts'].setdefault(target,[]).append(dict(StoryType=story,Section=section))
        counts=Counter()
        for part,links in result['StoryParts'].items():
            for typ in sorted({n['StoryType'] for n in links}):
                label=str(typ)+':'+str(counts[typ]);counts[typ]+=1
                for n in links:
                    if n['StoryType']==typ:n['COMStory']=label
        for name in z.namelist():
            if name.endswith('.rels'):
                tree = E.fromstring(z.read(name))
                for node in tree:
                    if node.get('TargetMode') == 'External':
                        row=dict(Part=name, **node.attrib)
                        result['Relationships'].append(row)
                        if not node.get('Type','').endswith('/hyperlink'):
                            result['Dependencies'].append(dict(Kind='external_relationship', **row))
            if name.startswith('word/') and name.endswith('.xml'):
                tree=E.fromstring(z.read(name))
                result['HasTextboxes'] |= any(n.tag=='{'+W+'}txbxContent' for n in tree.iter())
                for paragraph in tree.iter('{'+W+'}p'):
                    visible=''.join(n.text or '' for n in paragraph.iter('{'+W+'}t'))
                    if re.search(r'\[\[(?:MATH|FOOTNOTE):',visible):
                        result['Errors'].append('UNFINISHED_NATIVE_STRUCTURE_MARKER: '+name+': '+visible[:180])
                result['Bookmarks'] += [n.get('{'+W+'}name') for n in tree.iter('{'+W+'}bookmarkStart')]
                result['Dirty'] += [dict(Part=name, Tag=n.tag, Value=n.get('{'+W+'}dirty')) for n in tree.iter() if n.get('{'+W+'}dirty') is not None]
                if name=='word/settings.xml':
                    result['UpdateFields']=[n.get('{'+W+'}val','true') for n in tree.findall('w:updateFields',NS)]
                for n in tree.iter():
                    if E.QName(n).localname in ('OLEObject','control','altChunk'):
                        result['Dependencies'].append(dict(Kind='active_or_imported_object',Part=name,Tag=n.tag,Attributes=dict(n.attrib)))
                    if n.tag.endswith('}blip') and n.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}link'):
                        result['Dependencies'].append(dict(Kind='linked_image',Part=name,Attributes=dict(n.attrib)))
                if any(n.tag in ('{'+W+'}fldChar','{'+W+'}fldSimple','{'+W+'}instrText') for n in tree.iter()):
                    roots=list(tree) if E.QName(tree).localname in ('footnotes','endnotes') else [tree]
                    def scan(root, story):
                        stack=[]
                        def walk(node):
                            if node.tag=='{'+W+'}txbxContent' and node is not root:
                                scan(node, story+'/textbox'+str(len(result['Fields'])))
                                return
                            simple=node.tag=='{'+W+'}fldSimple'
                            if simple:
                                row=dict(Part=name,Story=story,Code=node.get('{'+W+'}instr',''),Result='',Kind='simple',Depth=len(stack),ParentId=stack[-1]['Id'] if stack else None,InParentCode=bool(stack and stack[-1]['Mode']=='code'),HasResult=True,Id=len(result['Fields']),Mode='result',NodePath=tree.getroottree().getpath(node),Dirty=node.get('{'+W+'}dirty'),Locked=node.get('{'+W+'}fldLock'))
                                result['Fields'].append(row); stack.append(row)
                            if node.tag=='{'+W+'}fldChar':
                                kind=node.get('{'+W+'}fldCharType')
                                if kind=='begin':
                                    row=dict(Part=name,Story=story,Code='',Result='',Kind='complex',Depth=len(stack),ParentId=stack[-1]['Id'] if stack else None,InParentCode=bool(stack and stack[-1]['Mode']=='code'),HasResult=False,Id=len(result['Fields']),Mode='code',Dirty=node.get('{'+W+'}dirty'),Locked=node.get('{'+W+'}fldLock'),NodePath=tree.getroottree().getpath(node))
                                    result['Fields'].append(row); stack.append(row)
                                elif kind=='separate':
                                    if stack: stack[-1]['Mode']='result';stack[-1]['HasResult']=True
                                    else: result['Errors'].append(story+': orphan separate')
                                elif kind=='end':
                                    if stack and stack[-1]['Kind']=='complex': stack.pop()
                                    else: result['Errors'].append(story+': orphan end')
                            elif node.tag=='{'+W+'}instrText':
                                if stack and stack[-1]['Mode']=='code': stack[-1]['Code']+=node.text or ''
                                elif stack:
                                    # Word stores a nested operand's RESULT as
                                    # instrText because it lives inside its parent's code.
                                    for field in stack:
                                        if field['Mode']=='result':field['Result']+=node.text or ''
                            elif node.tag=='{'+W+'}t':
                                for field in stack:
                                    if field['Mode']=='result': field['Result']+=node.text or ''
                            elif node.tag=='{'+W+'}tab' and node.getparent() is not None and node.getparent().tag=='{'+W+'}r':
                                for field in stack:
                                    if field['Mode']=='result': field['Result']+='\t'
                            for child in node: walk(child)
                            if simple:
                                if stack and stack[-1] is row: stack.pop()
                                else: result['Errors'].append(story+': unbalanced simple field')
                            if node.tag=='{'+W+'}p':
                                for field in stack:
                                    if field['Mode']=='result': field['Result']+='\n'
                        walk(root)
                        if stack: result['Errors'].append(story+': unclosed field')
                    for index, root in enumerate(roots): scan(root,name+':'+str(index))
            if 'vbaproject' in name.lower():
                result['Dependencies'].append(dict(Kind='macro',Part=name))
    for field in result['Fields']:
        field.pop('Mode',None)
        match=re.match(r'\s*([A-Za-z]+|=)',field['Code'])
        field['Token']=match.group(1).upper() if match else 'UNKNOWN'
        if field['Token'] in EXTERNAL or field['Token'] not in INTERNAL:
            result['Dependencies'].append(dict(Kind='external_or_unsupported_field',Field=field))
        ref=re.match(r'\s*(?:PAGE|NOTE)?REF\s+(?:"([^"]+)"|([^\s\\]+))',field['Code'],re.I)
        if ref:
            field['Bookmark']=ref.group(1) or ref.group(2)
            if field['Bookmark'] not in result['Bookmarks']: result['Errors'].append('Missing bookmark: '+field['Bookmark'])
    return result

def normalized(text):
    return re.sub(r'[\s\x00-\x1f\u00ad\u200b\ufeff]+','',text)

def code_key(code):
    # Tokenize whitespace OUTSIDE quoted constants only.
    return tuple(re.findall(r'"(?:[^"\\]|\\.)*"|[<>=+*/()\-]|[^\s<>=+*/()\-]+',code.strip()))

def parent_code(code):
    out=[];depth=0
    for char in code:
        if char=='\x13':
            if depth==0:out.append(' ')
            depth+=1
        elif char=='\x15':
            depth-=1
            if depth<0:raise ValueError('UNBALANCED_COM_NESTED_FIELD_CODE')
            if depth==0:out.append(' ')
        elif depth==0:out.append(char)
    if depth:raise ValueError('UNCLOSED_COM_NESTED_FIELD_CODE')
    return ''.join(out)

def cache_text(text):
    return re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f]', '', text).replace('\r','\n').strip('\n')

def compare_flat_packages(before_path,after_path):
    """Compare every content/layout/field/asset/setting value; ignore only RSIDs.

    Word may allocate a new editing-session ID when its ShapeRange/TextFrame
    objects are obtained. These IDs do not encode any formatting or content.
    This is a comparison projection only: no DOCX is modified or scrubbed.
    """
    maps=[];raw=[];ignored=[];pkg='{http://schemas.microsoft.com/office/2006/xmlPackage}'
    for path in (before_path,after_path):
        tree=E.parse(str(path));raw.append({n.get(pkg+'name'):hashlib.sha256(E.tostring(n,method='c14n')).hexdigest() for n in tree.getroot()})
        changes=[]
        for n in tree.iter():
            for key,value in list(n.attrib.items()):
                session_keys={'{'+W+'}'+a for a in ('rsidR','rsidRDefault','rsidRPr','rsidP','rsidDel','rsidSect')}
                identity_keys={'{http://schemas.microsoft.com/office/word/2010/wordml}'+a for a in ('paraId','textId','anchorId')}
                identity_keys|={'{http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing}'+a for a in ('anchorId','editId')}
                if key in session_keys|identity_keys:
                    changes.append(dict(Kind='session_attribute',Name=key,Value=value));del n.attrib[key]
        for n in tree.findall('.//w:rsids/w:rsid',NS):
            changes.append(dict(Kind='session_list_entry',Value=n.get('{'+W+'}val')));n.getparent().remove(n)
        for n in tree.findall('.//{http://schemas.microsoft.com/office/word/2010/wordml}docId'):
            changes.append(dict(Kind='document_identity',Value=dict(n.attrib)));n.getparent().remove(n)
        ignored.append(changes)
        maps.append({n.get(pkg+'name'):hashlib.sha256(E.tostring(n,method='c14n')).hexdigest() for n in tree.getroot()})
    return dict(Before=str(before_path),After=str(after_path),Status='PASS' if maps[0]==maps[1] else 'FAIL',RawChangedParts=[n for n in set(raw[0])|set(raw[1]) if raw[0].get(n)!=raw[1].get(n)],RemainingChangedParts=[n for n in set(maps[0])|set(maps[1]) if maps[0].get(n)!=maps[1].get(n)],OnlyIgnoredMetadata='RSID editing-session attributes/list and Word-generated paraId/textId/anchorId/editId/docId; never text, field codes/results, relationships, fonts, geometry or other settings',IgnoredValues=ignored,NoDocumentRewrite=True,ProjectedPartHashes=maps)

def prepare(job_path):
    job=load(job_path); source=Path(job['InputPath']); work=Path(job['WorkDirectory']); work.mkdir(exist_ok=False)
    before=inventory(source); dump(work/'input_inventory.json',before)
    if before['Errors']: raise ValueError('FIELD_PARSE_OR_BOOKMARK_ERROR: '+json.dumps(before['Errors']))
    if before['Dependencies']: raise ValueError('DEPENDENCY_REQUIRES_OBJECT_SPECIFIC_POLICY: '+json.dumps(before['Dependencies'],ensure_ascii=False))
    target=work/'document.docx'
    if job['Mode']=='ReadOnly':shutil.copyfile(source,target)
    changed=[];replacements={}
    if job['Mode']=='ReadOnly' and (any(v.lower() in ('true','1','on') for v in before['UpdateFields']) or any(str(f['Dirty']).lower() in ('true','1','on') for f in before['Fields'])):
        raise ValueError('READONLY_OPEN_REFRESH_FLAGS_REQUIRE_SEPARATE_UPDATESAVE_COPY')
    if job['Mode']=='UpdateSave':
        locked=[f for f in before['Fields'] if f['Token']!='HYPERLINK' and str(f['Locked']).lower() in ('true','1','on')]
        if locked: raise ValueError('LOCKED_INTERNAL_FIELD_REQUIRES_OBJECT_SPECIFIC_DECISION: '+json.dumps(locked,ensure_ascii=False))
        with zipfile.ZipFile(source) as z:
            data=z.read('word/settings.xml'); tree=E.fromstring(data)
            nodes=tree.findall('w:updateFields',NS)
            if len(nodes)>1: raise ValueError('Duplicate updateFields nodes')
            if nodes and nodes[0].get('{'+W+'}val','true').lower() in ('true','1','on'):
                nodes[0].set('{'+W+'}val','false')
                replacements['word/settings.xml']=E.tostring(tree,encoding='UTF-8',xml_declaration=True,standalone=True)
            with zipfile.ZipFile(target,'x') as out:
                for item in z.infolist():out.writestr(item,replacements.get(item.filename,z.read(item.filename)))
        with zipfile.ZipFile(source) as a,zipfile.ZipFile(target) as b:
            changed=[n for n in a.namelist() if a.read(n)!=b.read(n)]
            if set(changed)-set(replacements): raise ValueError('Unexpected package preprocessing change')
    after=inventory(target)
    if before['Fields']!=after['Fields'] or before['Dirty']!=after['Dirty'] or before['Relationships']!=after['Relationships']:
        raise ValueError('Preprocessing changed field codes, caches, locks, non-TOC dirty flags or relationships')
    from docx import Document
    bootstrap=Document(); bootstrap.add_paragraph('Word export instance ownership bootstrap '+job['JobId'])
    bootstrap.save(work/'bootstrap.docx')
    job.update(SourceSHA256=before['SHA256'],CopySHA256=digest(target),DocumentPath=str(target),PdfPath=str(work/'document.pdf'),ReferencedBookmarks=sorted(set(f['Bookmark'] for f in after['Fields'] if 'Bookmark' in f)),HasTextboxes=after['HasTextboxes'])
    dump(job_path,job)
    dump(work/'preprocessing.json',dict(ChangedParts=changed,BeforeUpdateFields=before['UpdateFields'],AfterUpdateFields=after['UpdateFields'],EveryFieldCodeCacheDirtyLockAndRelationshipUnchanged=True,BeforeSHA256=before['SHA256'],AfterSHA256=job['CopySHA256']))

def validate(job_path):
    job=load(job_path); work=Path(job['WorkDirectory']); result=load(work/'worker_result.json')
    if result['Status']!='PASS': raise ValueError('WORD_WORKER_NOT_PASS')
    pairs=[(p,p.with_name(p.name.replace('_before.xml','_after.xml'))) for p in sorted(work.glob('read_*_before.xml'))]
    pairs.append((work/'export_before.xml',work/'export_after.xml'))
    comparisons=[compare_flat_packages(a,b) for a,b in pairs];dump(work/'package_comparison.json',comparisons)
    if any(c['Status']!='PASS' for c in comparisons):raise ValueError('READ_OR_EXPORT_CHANGED_CONTENT_LAYOUT_OR_SETTINGS: '+repr([(c['Before'],c['RemainingChangedParts']) for c in comparisons if c['Status']!='PASS']))
    if any((work/n).stat().st_size==0 for n in ('document.docx','document.pdf')):raise ValueError('EMPTY_ARTIFACT')
    final=inventory(work/'document.docx'); pdf=PdfReader(work/'document.pdf',strict=True)
    if len(pdf.pages)!=result['WordPages']: raise ValueError('WORD_PDF_PAGE_COUNT_MISMATCH')
    texts=[p.extract_text() or '' for p in pdf.pages]; dump(work/'pdf_text.json',texts)
    if not pdf.pages: raise ValueError('PDF_HAS_NO_PAGES')
    if digest(job['InputPath'])!=job['SourceSHA256']: raise ValueError('SOURCE_CHANGED')
    if job['Mode']=='ReadOnly' and final['SHA256']!=job['SourceSHA256']: raise ValueError('READONLY_COPY_CHANGED')
    if final['Errors'] or final['Dependencies']: raise ValueError('SAVED_PACKAGE_FIELD_OR_DEPENDENCY_ERROR')
    if job['Mode']=='UpdateSave' and final['UpdateFields'] not in ([],['false'],['0']): raise ValueError('SAVE_REINTRODUCED_AUTO_UPDATE')
    pages={b['Name']:b for b in result['Bookmarks']}; refs=[]
    persisted_display=load(work/('saved_display.json' if job['Mode']=='UpdateSave' else 'readonly_display.json'))
    after_export=load(work/'after_export_display.json')
    def display_projection(d):
        return dict(Pages=d['Pages'],Stories=d['Stories'],Fields=[{k:v for k,v in f.items() if k not in ('Start','End','CodeStart')} for f in d['Fields']])
    if display_projection(persisted_display)!=display_projection(after_export):raise ValueError('DISPLAY_OR_FIELD_PAGE_MAP_CHANGED_AFTER_SAVE')
    used=set();mapping=[]
    # Match every persisted field to one distinct COM field in the correct story.
    # Identical repeated codes are consumed in document order, never by result.
    live=sorted(enumerate(after_export['Fields']),key=lambda x:(x[1]['Story'],x[1]['CodeStart']))
    for f in final['Fields']:
        part=f['Part'];textbox='/textbox' in f['Story']
        if part in final['StoryParts']:
            permitted={s['COMStory'] for s in final['StoryParts'][part]}
        else:
            with zipfile.ZipFile(work/'document.docx') as z:kind=E.QName(E.fromstring(z.read(part))).localname
            permitted={str(dict(document=1,footnotes=2,endnotes=3).get(kind,-99))+':0'}
        def same_story(c):
            isbox='/shape' in c['Story'] or c['StoryType']==5
            base=c['Story'].split('/')[0]
            return textbox==isbox and (base in permitted or (textbox and '1:0' in permitted and base.startswith('5:')))
        nested_parent=any(child['ParentId']==f['Id'] for child in final['Fields'])
        candidates=[(i,c) for i,c in live if i not in used and c['Token']==f['Token'] and same_story(c) and code_key(parent_code(c['Code']) if nested_parent else c['Code'])==code_key(f['Code'])]
        if not candidates:raise ValueError('SAVED_FIELD_HAS_NO_DISTINCT_COM_STORY_MATCH: '+repr((part,f['Story'],f['Code'])))
        i,c=candidates[0];used.add(i)
        operand_without_stored_result=f['InParentCode'] and not f['HasResult']
        if not operand_without_stored_result and cache_text(f['Result'])!=cache_text(c['Text']):
            raise ValueError('DISK_FIELD_CACHE_DIFFERS_FROM_EXPORTED_WORD: '+repr((part,f['Code'],f['Result'][:160],c['Text'][:160])))
        mapping.append(dict(Part=part,NodePath=f['NodePath'],Code=f['Code'],COMIndex=i,COMStory=c['Story'],COMSection=c['Section'],COMCodeStart=c['CodeStart'],CacheStatus='NOT_PERSISTED_NESTED_CODE_OPERAND' if operand_without_stored_result else 'EXACT_MATCH',LiveResult=c['Text'],ParentId=f['ParentId']))
    dump(work/'field_cache_mapping.json',mapping)
    for f in final['Fields']:
        if f['Token']=='PAGEREF' and 'Bookmark' in f:
            if f['Bookmark'] not in pages: raise ValueError('MISSING_SAVED_WORD_BOOKMARK_METRIC')
            b=pages[f['Bookmark']]; actual=f['Result'].strip()
            if actual!=str(b['AdjustedPage']): raise ValueError('STALE_PAGEREF_CACHE: '+repr((f['Code'],actual,b)))
            refs.append(dict(Bookmark=f['Bookmark'],CachedPage=actual,WordPage=b['AdjustedPage'],PhysicalPage=b['PhysicalPage']))
    # Bookmark text must be on the physical body page recorded from the saved/reopened Word file.
    for b in result['Bookmarks']:
        text=normalized(b['Text']); page=normalized(texts[b['PhysicalPage']-1])
        if text and text not in page: raise ValueError('BOOKMARK_BODY_TEXT_NOT_ON_PDF_PAGE: '+b['Name'])
    full=''.join(normalized(t) for t in texts)
    for term in job.get('ExpectedText',[]):
        if ''.join(term.split()) not in full: raise ValueError('EXPECTED_TEXT_MISSING: '+term)
    if job['Mode']=='UpdateSave':
        for token in ('STALE_TOC_SENTINEL','STALE_REF_SENTINEL','Error! Reference source not found.','错误!未找到引用源。'):
            if token in full or any(token in f['Result'] for f in final['Fields']): raise ValueError('STALE_OR_ERROR_FIELD_RESULT: '+token)
    dump(work/'saved_inventory.json',final)
    dump(work/'verification.json',dict(Status='PASS',PDFPages=len(pdf.pages),SourceUnchanged=True,PageReferences=refs,FieldCount=len(final['Fields']),EveryDiskFieldCacheMatchesExportedWord=True,ReopenAndExportFieldPageMapsUnchanged=True,ReadAndExportPackageComparison='PASS_EXCEPT_EXPLICIT_NONDISPLAY_SESSION_AND_IDENTITY_METADATA',TOCs=sum(f['Token']=='TOC' for f in final['Fields']),DOCXSHA256=final['SHA256'],PDFSHA256=digest(work/'document.pdf'),DOCXBytes=(work/'document.docx').stat().st_size,PDFBytes=(work/'document.pdf').stat().st_size))

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('operation',choices=['prepare','validate','inventory']); parser.add_argument('path'); args=parser.parse_args()
    if args.operation=='inventory': print(json.dumps(inventory(args.path),ensure_ascii=False))
    else: globals()[args.operation](Path(args.path))
