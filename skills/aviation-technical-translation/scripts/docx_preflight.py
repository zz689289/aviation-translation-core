"""Read-only DOCX guards for raw editable text and property placement.

Run before Word and again on its saved output. This is not visual or semantic QA.
Only U+FEFF within a word is rejected; legitimate ZWJ/ZWNJ, NBSP, mathematical
symbols and source punctuation are not globally stripped or normalized.
"""
from __future__ import annotations
import argparse
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
def q(name): return f"{{{W}}}{name}"

def inspect_docx(path):
    path=Path(path)
    failures=[]; paragraphs=0; parts=[]
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError("Duplicate ZIP members")
        if "word/document.xml" not in names:raise ValueError("Missing document.xml")
        for name in sorted(names):
            if not name.startswith("word/") or not name.endswith(".xml"):
                continue
            root=ET.fromstring(z.read(name))
            ps=list(root.iter(q("p")))
            if not ps:continue
            parts.append(name)
            for index,p in enumerate(ps,1):
                paragraphs+=1
                # Direct paragraph runs, including hyperlink content. Nested
                # text-box paragraphs are inspected independently.
                texts=[]
                def collect(node):
                    for child in node:
                        if child.tag==q("p"):continue
                        if child.tag==q("t"):texts.append(child.text or "")
                        else:collect(child)
                collect(p)
                raw="".join(texts)
                for match in re.finditer(r"(?<=\w)\ufeff+(?=\w)",raw):
                    failures.append(dict(code="INTRAWORD_FEFF",part=name,paragraph=index,
                                         offset=match.start(),context=raw[max(0,match.start()-10):match.end()+10]))
                props=p.findall(q("pPr"))
                if len(props)>1 or (props and list(p).index(props[0])!=0):
                    failures.append(dict(code="PARAGRAPH_PROPERTIES_POSITION",part=name,paragraph=index))
            for index,r in enumerate(root.iter(q("r")),1):
                props=r.findall(q("rPr"))
                if len(props)>1 or (props and list(r).index(props[0])!=0):
                    failures.append(dict(code="RUN_PROPERTIES_POSITION",part=name,run=index))
    return dict(status="FAIL" if failures else "PASS",checked_parts=parts,
                paragraphs=paragraphs,failures=failures,semantic_qa="NOT_PERFORMED",
                visual_qa="NOT_PERFORMED",repairs_performed=False)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--docx",type=Path,required=True)
    p.add_argument("--report",type=Path,required=True)
    args=p.parse_args()
    try:
        if args.report.exists() or args.report.resolve()==args.docx.resolve():
            raise ValueError("Refuse overwrite")
        r=inspect_docx(args.docx)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        # Exclusive create also protects against a concurrent writer.
        with args.report.open("x",encoding="utf-8") as f:json.dump(r,f,ensure_ascii=False,indent=2)
        print(r["status"])
        return 0 if r["status"]=="PASS" else 1
    except (OSError,ValueError,ET.ParseError,zipfile.BadZipFile) as exc:
        print("INVALID: "+str(exc))
        return 2
if __name__=="__main__":raise SystemExit(main())
