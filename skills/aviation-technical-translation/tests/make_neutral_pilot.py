"""Original bilingual source/target fixtures. Never derived from a publication.

Requires the existing python-docx library. Writes only to a NEW directory.
source.docx is the authoritative original; target-a.docx and target-b.docx
are deliberately unlabeled for source-first review. expectations.json is for
the executor and should be withheld until the reviewer's initial inspection.
"""
import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

CODE = "if check_a and check_b:\n    record(sample)\nelse:\n    retain_previous()"
SOURCE = "The monitor shall record a valid sample only when both input checks pass."
TARGET = "仅在两项输入检查均通过时，监视器才应记录有效样本。"

def font(run, size=10.5, bold=False, heading=False):
    run.font.name = "Times New Roman"
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "黑体" if heading else "宋体")
    run.font.size = Pt(size)
    run.bold = bold
    return run

def create(path, zh=False):
    doc=Document()
    doc.core_properties.author="Neutral fixture"
    doc.core_properties.last_modified_by="Neutral fixture"
    sec=doc.sections[0]
    sec.page_width=Cm(21);sec.page_height=Cm(29.7)
    sec.top_margin=Cm(2);sec.bottom_margin=Cm(2)
    sec.left_margin=Cm(2.3);sec.right_margin=Cm(2.3)
    normal=doc.styles["Normal"]
    normal.font.name="Times New Roman";normal.font.size=Pt(10.5)
    normal.paragraph_format.space_after=Pt(8)
    normal.paragraph_format.line_spacing=1.25
    title=doc.add_paragraph()
    title.alignment=WD_ALIGN_PARAGRAPH.CENTER
    font(title.add_run("样本记录说明" if zh else "Sample recording note"),16,True,True)
    p=doc.add_paragraph();font(p.add_run(TARGET if zh else SOURCE))
    p=doc.add_paragraph()
    font(p.add_run("已验证输入" if zh else "Validated input")).font.color.rgb=RGBColor.from_string("0066CC")
    font(p.add_run(" (VI)"))
    font(p.add_run("：两项检查均通过的输入。" if zh else ": input that passes both checks."))
    p=doc.add_paragraph()
    r=font(p.add_run("审查范围" if zh else "Review boundary"),12,True,True)
    r.underline=True
    p=doc.add_paragraph()
    pp=p.paragraph_format;pp.left_indent=Cm(.7);pp.first_line_indent=Cm(-.7)
    pp.tab_stops.add_tab_stop(Cm(.7),WD_TAB_ALIGNMENT.LEFT)
    font(p.add_run("1.\t"))
    font(p.add_run("记录输入检查结果，并保留必要的上下文。" if zh else "Record the input-check results and keep the necessary context."))
    p.add_run().add_break(WD_BREAK.LINE)
    font(p.add_run("该续行应与文字起点对齐。" if zh else "This continuation aligns with the start of the item text."))
    p=doc.add_paragraph()
    borders=OxmlElement("w:pBdr");left=OxmlElement("w:left")
    for k,v in (("val","single"),("sz","12"),("space","6"),("color","0066CC")):left.set(qn("w:"+k),v)
    borders.append(left);p._p.get_or_add_pPr().append(borders)
    font(p.add_run("说明：检查未通过时保留前一个样本。" if zh else "Note: keep the previous sample when a check fails."))
    p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    font(p.add_run("表 1  样本记录条件" if zh else "Table 1  Sample recording conditions"),10.5,True)
    table=doc.add_table(rows=1,cols=2);table.style="Table Grid"
    for cell,txt in zip(table.rows[0].cells,["检查状态","处理"] if zh else ["Check status","Action"]):
        font(cell.paragraphs[0].add_run(txt),10.5,True)
    for vals in ([["均通过","记录有效样本"],["至少一项未通过","保留前一个样本"]] if zh else [["Both pass","Record the valid sample"],["At least one fails","Keep the previous sample"]]):
        for c,t in zip(table.add_row().cells,vals):font(c.paragraphs[0].add_run(t))
    p=doc.add_paragraph()
    font(p.add_run("示例代码" if zh else "Example code"),12,True,True)
    for line in CODE.splitlines():
        p=doc.add_paragraph()
        p.paragraph_format.space_after=Pt(0)
        r=font(p.add_run(line),9);r.font.name="Consolas"
    p=doc.add_paragraph()
    font(p.add_run("校验值：" if zh else "Check value: "))
    r=font(p.add_run("v"));r=font(p.add_run("t"));r.font.subscript=True
    font(p.add_run(" = (a + b)/2"))
    doc.save(path)

def make(output):
    output.mkdir(parents=True,exist_ok=False)
    create(output/"source.docx")
    create(output/"target-a.docx",True)
    with zipfile.ZipFile(output/"target-a.docx") as z:
        entries={x.filename:z.read(x.filename) for x in z.infolist()}
    root=ET.fromstring(entries["word/document.xml"])
    ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for t in root.findall(".//w:t",ns):
        if t.text==TARGET:t.text="监视器可以记录有效样本。" # lost condition + weakened shall
        if t.text=="已验证输入":t.text="已验证\ufeff输入"
    for r in root.findall(".//w:r",ns):
        if r.find("w:rPr/w:u",ns) is not None:
            pr=r.find("w:rPr",ns);r.remove(pr);r.append(pr)
    entries["word/document.xml"]=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    with zipfile.ZipFile(output/"target-b.docx","x",zipfile.ZIP_DEFLATED) as z:
        for n,b in entries.items():z.writestr(n,b)
    expected={
      "original_fixture":True,
      "source":SOURCE,"correct_target":TARGET,
      "target-a":{"structural":"PASS","semantic":"SOURCE_CONDITION_AND_MODALITY_RETAINED"},
      "target-b":{"structural":["INTRAWORD_FEFF","RUN_PROPERTIES_POSITION"],
                  "semantic":["MISSING_ONLY_WHEN_BOTH_CHECKS_PASS","SHALL_WEAKENED_TO_CAN"]},
      "visual_checks":["blue translated label; black parenthetical alias","underline survives save",
          "hanging continuation aligns with text","left border","table/caption fit","inline subscript","code unchanged"],
      "limitations":"Structural PASS is not semantic/visual acceptance."
    }
    (output/"expectations.json").write_text(json.dumps(expected,ensure_ascii=False,indent=2),encoding="utf8")
    return output

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    print(make(args.output))
