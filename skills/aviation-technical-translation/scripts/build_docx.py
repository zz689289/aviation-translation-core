"""Build a structured Chinese DOCX plus Word postprocessing actions.

Usage:
    python build_docx.py --project PROJECT/project.json --output WORK/draft.docx \
        --actions WORK/draft.actions.json --ledger WORK/draft.ledger.json

All paths and object counts come from the project data. The generated DOCX may
contain temporary math/footnote action markers and is not a final deliverable
until the Word postprocessor succeeds and marker leakage is verified as zero.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from common import (
    SKILL_ROOT,
    atomic_write_json,
    load_json,
    load_jsonl,
    relative_posix,
    require_package,
    resolve_layout_profile,
    resolve_relative,
    sha256_file,
)
from validate_project import load_objects, schema_errors, validate_project


def color_value(value: str):
    from docx.shared import RGBColor

    value = value.lstrip("#")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def set_run_fonts(run: Any, latin: str, cjk: str, size_pt: float | None = None) -> None:
    from docx.oxml.ns import qn
    from docx.shared import Pt

    run.font.name = latin
    fonts = run._element.get_or_add_rPr().rFonts
    fonts.set(qn("w:ascii"), latin)
    fonts.set(qn("w:hAnsi"), latin)
    fonts.set(qn("w:eastAsia"), cjk)
    fonts.set(qn("w:cs"), latin)
    if size_pt:
        run.font.size = Pt(size_pt)


def remove_outline(style: Any) -> None:
    from docx.oxml.ns import qn

    p_pr = style._element.get_or_add_pPr()
    for node in list(p_pr.findall(qn("w:outlineLvl"))):
        p_pr.remove(node)


def clone_no_toc_style(document: Any, name: str, base_name: str) -> Any:
    """Clone visible style properties without inheriting a heading outline level."""

    from copy import deepcopy

    from docx.enum.style import WD_STYLE_TYPE
    from docx.oxml.ns import qn

    if base_name not in [style.name for style in document.styles]:
        raise ValueError(f"Cannot derive NoTOC style {name!r}; base style {base_name!r} is missing.")
    target = document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    source = document.styles[base_name]
    for tag in ("w:basedOn", "w:pPr", "w:rPr"):
        for existing in list(target._element.findall(qn(tag))):
            target._element.remove(existing)
    if source._element.pPr is not None:
        paragraph_properties = deepcopy(source._element.pPr)
        for outline in list(paragraph_properties.findall(qn("w:outlineLvl"))):
            paragraph_properties.remove(outline)
        target._element.append(paragraph_properties)
    if source._element.rPr is not None:
        target._element.append(deepcopy(source._element.rPr))
    remove_outline(target)
    return target


def configure_style(document: Any, name: str, spec: dict[str, Any], *, no_toc: bool = False) -> Any:
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    exact = [item for item in document.styles if item.name == name]
    style = exact[0] if exact else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.font.name = spec["font_latin"]
    fonts = style._element.get_or_add_rPr().rFonts
    fonts.set(qn("w:ascii"), spec["font_latin"])
    fonts.set(qn("w:hAnsi"), spec["font_latin"])
    fonts.set(qn("w:eastAsia"), spec["font_cjk"])
    fonts.set(qn("w:cs"), spec["font_latin"])
    style.font.size = Pt(spec["size_pt"])
    style.font.bold = spec.get("bold")
    style.font.italic = spec.get("italic")
    if spec.get("color"):
        style.font.color.rgb = color_value(spec["color"])
    paragraph = style.paragraph_format
    alignments = {
        "left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }
    if spec.get("alignment"):
        paragraph.alignment = alignments[spec["alignment"]]
    if spec.get("line_spacing"):
        paragraph.line_spacing = spec["line_spacing"]
    paragraph.space_before = Pt(spec.get("space_before_pt", 0))
    paragraph.space_after = Pt(spec.get("space_after_pt", 0))
    if "left_indent_cm" in spec:
        paragraph.left_indent = Cm(spec["left_indent_cm"])
    if "first_line_indent_cm" in spec:
        paragraph.first_line_indent = Cm(spec["first_line_indent_cm"])
    if "tab_stop_cm" in spec:
        paragraph.tab_stops.add_tab_stop(Cm(spec["tab_stop_cm"]))
    paragraph.keep_with_next = spec.get("keep_with_next")
    paragraph.keep_together = spec.get("keep_lines_together")
    p_pr = style._element.get_or_add_pPr()
    for old in list(p_pr.findall(qn("w:outlineLvl"))):
        p_pr.remove(old)
    if spec.get("outline_level") is not None and not no_toc:
        node = OxmlElement("w:outlineLvl")
        node.set(qn("w:val"), str(spec["outline_level"]))
        p_pr.append(node)
    return style


def apply_paragraph_spacing_override(paragraph: Any, override: dict[str, Any]) -> None:
    from docx.shared import Cm, Pt

    formatting = paragraph.paragraph_format
    if "space_before_pt" in override:
        formatting.space_before = Pt(override["space_before_pt"])
    if "space_after_pt" in override:
        formatting.space_after = Pt(override["space_after_pt"])
    if "line_spacing" in override:
        formatting.line_spacing = override["line_spacing"]
    if "left_indent_cm" in override:
        formatting.left_indent = Cm(override["left_indent_cm"])
    if "first_line_indent_cm" in override:
        formatting.first_line_indent = Cm(override["first_line_indent_cm"])
    if "tab_stop_cm" in override:
        formatting.tab_stops.clear_all()
        formatting.tab_stops.add_tab_stop(Cm(override["tab_stop_cm"]))


def add_caption(
    document: Any,
    text: str,
    style_name: str,
    object_id: str,
    *,
    keep_with_next: bool = False,
) -> str:
    if style_name not in [style.name for style in document.styles]:
        raise ValueError(f"Caption {object_id} references missing semantic style {style_name!r}.")
    paragraph = document.add_paragraph(text, style=style_name)
    paragraph.paragraph_format.keep_with_next = keep_with_next
    return f"paragraph:caption:{object_id}"


def configure_page(section: Any, page: dict[str, Any]) -> None:
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm

    orientation = page.get("orientation", "portrait")
    section.orientation = WD_ORIENT.LANDSCAPE if orientation == "landscape" else WD_ORIENT.PORTRAIT
    section.page_width = Cm(page["width_cm"])
    section.page_height = Cm(page["height_cm"])
    margins = page["margins"]
    section.top_margin = Cm(margins["top"])
    section.bottom_margin = Cm(margins["bottom"])
    section.left_margin = Cm(margins["left"])
    section.right_margin = Cm(margins["right"])
    if "header_distance_cm" in page:
        section.header_distance = Cm(page["header_distance_cm"])
    if "footer_distance_cm" in page:
        section.footer_distance = Cm(page["footer_distance_cm"])


def set_page_number_start(section: Any, start: int | None) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    sect_pr = section._sectPr
    for old in list(sect_pr.findall(qn("w:pgNumType"))):
        sect_pr.remove(old)
    if start is not None:
        node = OxmlElement("w:pgNumType")
        node.set(qn("w:start"), str(start))
        sect_pr.append(node)


def add_field(paragraph: Any, instruction: str, placeholder: str = "") -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    begin.set(qn("w:dirty"), "true")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = placeholder
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.extend([begin, instr, separate, text, end])


def configure_word_settings(document: Any, render_policy: dict[str, Any], math_font: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    settings = document.settings._element
    for old in list(settings.findall(qn("w:updateFields"))):
        settings.remove(old)
    # The export UpdateSave mode owns all internal field/TOC calculation.
    node = OxmlElement("w:updateFields")
    node.set(qn("w:val"), "false")
    settings.append(node)
    for old in list(settings.findall(qn("w:doNotAutoCompressPictures"))):
        settings.remove(old)
    if render_policy.get("disable_image_compression", False):
        settings.append(OxmlElement("w:doNotAutoCompressPictures"))
    for old in list(settings.findall(qn("w14:defaultImageDpi"))):
        settings.remove(old)
    if render_policy.get("image_dpi") is not None:
        dpi = OxmlElement("w14:defaultImageDpi")
        dpi.set(qn("w14:val"), str(int(render_policy["image_dpi"])))
        settings.append(dpi)
    for old in list(settings.findall(qn("m:mathPr"))):
        settings.remove(old)
    math_properties = OxmlElement("m:mathPr")
    math_font_node = OxmlElement("m:mathFont")
    math_font_node.set(qn("m:val"), math_font)
    math_properties.append(math_font_node)
    settings.append(math_properties)


def set_repeat_table_header(row: Any) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    tr_pr.append(node)


def prevent_row_split(row: Any) -> None:
    from docx.oxml import OxmlElement

    tr_pr = row._tr.get_or_add_trPr()
    tr_pr.append(OxmlElement("w:cantSplit"))


def add_math_marker(paragraph: Any, formula: dict[str, Any], actions: list[dict[str, Any]]) -> str:
    marker = f"[[MATH:{len(actions) + 1:04d}]]"
    paragraph.add_run(marker)
    actions.append({
        "marker": marker,
        "formula_id": formula["id"],
        "expression": formula["normalized_expression"],
        "placement": formula["placement"],
    })
    return marker


def add_table(
    document: Any,
    table_data: dict[str, Any],
    formulas: dict[str, dict[str, Any]],
    math_actions: list[dict[str, Any]],
    caption_style: str,
    body_style: str,
) -> list[str]:
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    outputs: list[str] = []
    caption = table_data.get("caption", {})
    if caption.get("position") == "above" and caption.get("target"):
        outputs.append(
            add_caption(
                document,
                caption["target"],
                caption_style,
                table_data["id"],
                keep_with_next=True,
            )
        )
    columns = table_data["columns"]
    rows = table_data["rows"]
    word_table = document.add_table(rows=1 + len(rows), cols=len(columns))
    word_table.autofit = False
    word_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    widths = [column.get("width_cm") for column in columns]
    header = word_table.rows[0]
    for index, column in enumerate(columns):
        cell = header.cells[index]
        cell.text = column["target_text"]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cell.paragraphs[0].style = body_style
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if widths[index]:
            cell.width = Cm(widths[index])
    for row_index, row_data in enumerate(rows, 1):
        row = word_table.rows[row_index]
        if not table_data.get("allow_row_break", False):
            prevent_row_split(row)
        for column_index, cell_data in enumerate(row_data["cells"]):
            cell = row.cells[column_index]
            paragraph = cell.paragraphs[0]
            paragraph.style = body_style
            if cell_data.get("kind") == "formula":
                formula_id = cell_data.get("formula_id")
                if formula_id not in formulas:
                    raise ValueError(f"Table {table_data['id']} references unknown formula {formula_id}")
                add_math_marker(paragraph, formulas[formula_id], math_actions)
            else:
                paragraph.add_run(cell_data["target_text"])
            alignment = columns[column_index].get("alignment", "left")
            paragraph.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.RIGHT}[alignment]
            if widths[column_index]:
                cell.width = Cm(widths[column_index])
    for header_index in range(min(table_data.get("header_row_count", 0), len(word_table.rows))):
        set_repeat_table_header(word_table.rows[header_index])
    for row_index, row_data in enumerate(rows, 1):
        for column_index, cell_data in enumerate(row_data["cells"]):
            rowspan = int(cell_data.get("rowspan", 1))
            colspan = int(cell_data.get("colspan", 1))
            if rowspan > 1 or colspan > 1:
                word_table.cell(row_index, column_index).merge(word_table.cell(row_index + rowspan - 1, column_index + colspan - 1))
    outputs.append(f"table:{table_data['id']}")
    if caption.get("position") == "below" and caption.get("target"):
        outputs.append(add_caption(document, caption["target"], caption_style, table_data["id"]))
    separator = document.add_paragraph()
    separator.paragraph_format.space_before = Pt(0)
    separator.paragraph_format.space_after = Pt(0)
    separator.paragraph_format.line_spacing = 1
    outputs.append(f"paragraph:table-separator:{table_data['id']}")
    return outputs


def _canonical(path: Path) -> str:
    """Return a case-normalized absolute key suitable for collision checks."""

    return os.path.normcase(str(path.resolve()))


def ensure_safe_output_paths(
    project_path: Path,
    project: dict[str, Any],
    paths: dict[str, Path],
    output: Path,
    actions_path: Path,
    ledger_path: Path,
) -> None:
    """Refuse to overwrite project evidence, structured sources, or each other."""

    requested = {
        "DOCX output": (output, ".docx"),
        "action file": (actions_path, ".json"),
        "ledger file": (ledger_path, ".json"),
    }
    for label, (path, suffix) in requested.items():
        if path.suffix.lower() != suffix:
            raise ValueError(f"{label} must use the {suffix} extension: {path}")

    output_keys = [_canonical(path) for path, _ in requested.values()]
    if len(set(output_keys)) != len(output_keys):
        raise ValueError("DOCX output, action file, and ledger file must be three distinct paths.")

    protected_exact: dict[str, str] = {_canonical(project_path): "project configuration"}
    protected_dirs: dict[str, str] = {}
    for key, path in paths.items():
        if path.is_dir():
            protected_dirs[_canonical(path)] = f"project path '{key}'"
        else:
            protected_exact[_canonical(path)] = f"project path '{key}'"
    # Content and figure registries define protected source trees. This also
    # protects table and asset subdirectories even when an output does not yet
    # exist and therefore cannot appear in a recursive file list.
    for key in ("content", "figures"):
        if key in paths:
            source_parent = paths[key].parent.resolve()
            if source_parent != project_path.parent.resolve():
                protected_dirs[_canonical(source_parent)] = f"source tree for '{key}'"
    for item in project.get("inputs", []):
        input_path = resolve_relative(project_path.parent, item["path"])
        protected_exact[_canonical(input_path)] = f"declared input '{item['id']}'"

    for label, (candidate, _) in requested.items():
        candidate_key = _canonical(candidate)
        if candidate_key in protected_exact:
            raise ValueError(f"{label} collides with protected {protected_exact[candidate_key]}: {candidate}")
        candidate_path = candidate.resolve()
        for directory_key, description in protected_dirs.items():
            directory = Path(directory_key)
            try:
                candidate_path.relative_to(directory)
            except ValueError:
                continue
            raise ValueError(f"{label} is inside protected {description}: {candidate}")


def collect_build_inputs(
    project_path: Path,
    project: dict[str, Any],
    paths: dict[str, Path],
) -> list[dict[str, str]]:
    """Hash all declared evidence and structured build inputs used by a build."""

    base = project_path.parent.resolve()
    candidates: list[tuple[str, Path]] = []
    for item in project.get("inputs", []):
        candidates.append((item["id"], resolve_relative(base, item["path"])))
    for key, path in sorted(paths.items()):
        if path.is_file():
            candidates.append((f"path:{key}", path))
        elif path.is_dir():
            for child in sorted(item for item in path.rglob("*") if item.is_file()):
                candidates.append((f"path:{key}:{relative_posix(child, path)}", child))
    if "figures" in paths:
        for figure in load_objects(paths["figures"]):
            asset = resolve_relative(paths["figures"].parent, figure["path"])
            candidates.append((f"figure:{figure['id']}", asset))

    seen: set[str] = set()
    records: list[dict[str, str]] = []
    for input_id, path in candidates:
        key = _canonical(path)
        if key in seen:
            continue
        seen.add(key)
        records.append({"id": input_id, "path": relative_posix(path, base), "sha256": sha256_file(path)})
    return sorted(records, key=lambda item: (item["path"], item["id"]))


def build(project_path: Path, output: Path, actions_path: Path, ledger_path: Path) -> None:
    require_package("docx", "python-docx")
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    validation = validate_project(project_path)
    if validation["status"] != "PASS":
        raise RuntimeError("Project validation failed:\n- " + "\n- ".join(validation["errors"]))

    project = load_json(project_path)
    base = project_path.resolve().parent
    paths = {key: resolve_relative(base, value) for key, value in project["paths"].items()}
    ensure_safe_output_paths(project_path, project, paths, output, actions_path, ledger_path)
    existing_outputs = [path for path in (output, actions_path, ledger_path) if path.exists()]
    if existing_outputs:
        raise FileExistsError(
            "Refusing to overwrite an existing build artifact; choose fresh versioned paths: "
            + ", ".join(str(path) for path in existing_outputs)
        )
    build_inputs = collect_build_inputs(project_path, project, paths)
    project_config_sha256 = sha256_file(project_path)
    blocks = load_jsonl(paths["content"])
    tables = {item["id"]: item for item in (load_json(path) for path in sorted(paths["tables_dir"].glob("*.json")))} if "tables_dir" in paths else {}
    formulas = {item["id"]: item for item in load_objects(paths["formulas"])} if "formulas" in paths else {}
    footnotes = {item["id"]: item for item in load_objects(paths["footnotes"])} if "footnotes" in paths else {}
    toc = load_json(paths["toc"]) if "toc" in paths else {"entries": [{"block_id": block["id"], "include": block.get("toc_policy") == "include", "target_style": block.get("style_ref", "")} for block in blocks if block["block_type"] == "heading"]}
    toc_by_block = {entry["block_id"]: entry for entry in toc["entries"]}
    included_toc_styles = {entry.get("target_style") for entry in toc["entries"] if entry.get("include")}
    figures = {item["id"]: item for item in load_objects(paths["figures"])} if "figures" in paths else {}
    raw_layout = load_json(paths["layout"]) if "layout" in paths else {
        "profile_id": "source_faithful",
        "page_defaults": {"width_cm": 21.0, "height_cm": 29.7, "orientation": "portrait", "margins": {"top": 2.54, "bottom": 2.54, "left": 2.54, "right": 2.54}},
        "styles": {}, "sections": [], "toc": {"field_code": "TOC \\o \"1-3\" \\h \\z \\u", "levels": 3},
    }
    layout = resolve_layout_profile(raw_layout)

    document = Document()
    configure_page(document.sections[0], layout["page_defaults"])
    for name, spec in layout.get("styles", {}).items():
        configure_style(document, name, spec)
    configure_word_settings(document, layout.get("render_policy", {}), layout["math_font"])

    metadata = project.get("document", {})
    document.core_properties.title = metadata.get("title", project.get("title", ""))
    document.core_properties.subject = metadata.get("subject", "")
    document.core_properties.author = metadata.get("creator", "")
    document.core_properties.language = metadata.get("language", "zh-CN")

    section_profiles = {item["id"]: item for item in layout.get("sections", [])}
    style_roles = layout.get("style_roles", {})
    body_style = style_roles.get("body", "Normal")
    list_style = style_roles.get("list", body_style)
    requirement_style = style_roles.get("requirement", body_style)
    bibliography_style = style_roles.get("bibliography", body_style)
    figure_caption_style = style_roles.get("figure_caption", "Caption")
    table_caption_style = style_roles.get("table_caption", figure_caption_style)
    math_actions: list[dict[str, Any]] = []
    footnote_actions: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    output_serial = 0
    pending_title_spacing_override: dict[str, Any] | None = None

    def output_id(kind: str, block_id: str) -> str:
        nonlocal output_serial
        output_serial += 1
        return f"{kind}:{output_serial:05d}:{block_id}"

    for block in blocks:
        block_id = block["id"]
        if block.get("merge_into"):
            records.append({"source_block_ids": [block_id], "output_object_ids": [], "status": "merged", "merged_into": block["merge_into"], "target": block["merge_into"]})
            continue
        kind = block["block_type"]
        outputs: list[str] = []
        paragraph = None
        if kind == "heading":
            toc_entry = toc_by_block[block_id]
            base_style_name = block.get("style_ref") or f"Heading {block['heading_level']}"
            style_name = toc_entry.get("target_style") or base_style_name
            if not toc_entry["include"]:
                no_toc_name = style_name or f"{base_style_name} NoTOC"
                if no_toc_name == base_style_name or no_toc_name in included_toc_styles:
                    raise ValueError(
                        f"Excluded TOC block {block_id} must use a dedicated NoTOC style; got {no_toc_name!r}."
                    )
                if no_toc_name not in [style.name for style in document.styles]:
                    spec = layout.get("styles", {}).get(base_style_name)
                    if spec:
                        configure_style(document, no_toc_name, spec, no_toc=True)
                    else:
                        clone_no_toc_style(document, no_toc_name, base_style_name)
                else:
                    remove_outline(document.styles[no_toc_name])
                style_name = no_toc_name
            paragraph = document.add_paragraph(style=style_name)
            paragraph.add_run(block["target_text"])
            if pending_title_spacing_override:
                apply_paragraph_spacing_override(paragraph, pending_title_spacing_override)
                pending_title_spacing_override = None
            outputs.append(output_id("paragraph", block_id))
        elif kind in {"paragraph", "list_item", "bibliography"}:
            default_style = list_style if kind == "list_item" else bibliography_style if kind == "bibliography" else body_style
            style_name = block.get("style_ref") or default_style
            paragraph = document.add_paragraph(style=style_name)
            if kind == "list_item":
                paragraph.add_run(block.get("list", {}).get("marker", "•") + " ")
            paragraph.add_run(block["target_text"])
            if kind == "bibliography":
                bibliography_profile = layout.get("object_profiles", {}).get("bibliography", {})
                if "left_indent_cm" in bibliography_profile:
                    paragraph.paragraph_format.left_indent = Cm(bibliography_profile["left_indent_cm"])
                if "hanging_indent_cm" in bibliography_profile:
                    paragraph.paragraph_format.first_line_indent = Cm(-bibliography_profile["hanging_indent_cm"])
                if "tab_stop_cm" in bibliography_profile:
                    paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(bibliography_profile["tab_stop_cm"]))
            outputs.append(output_id("paragraph", block_id))
        elif kind in {"requirement", "regulatory_quote"}:
            table = document.add_table(rows=1, cols=1)
            table.autofit = False
            requirement_paragraph = table.cell(0, 0).paragraphs[0]
            requirement_paragraph.style = block.get("style_ref") or requirement_style
            requirement_paragraph.add_run(block["target_text"])
            outputs.append(output_id("requirement-table", block_id))
            document.add_paragraph().paragraph_format.space_after = Pt(0)
        elif kind == "table":
            outputs.extend(
                add_table(
                    document,
                    tables[block["table_id"]],
                    formulas,
                    math_actions,
                    table_caption_style,
                    body_style,
                )
            )
        elif kind == "figure":
            figure = figures[block["figure_id"]]
            asset = resolve_relative(paths["figures"].parent, figure["path"])
            figure_profile = layout.get("object_profiles", {}).get("figure", {}).get(figure.get("placement_profile", ""), {})
            width_cm = figure.get("width_cm") or figure_profile.get("width_cm")
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run()
            run.add_picture(str(asset), width=Cm(width_cm) if width_cm else None)
            outputs.append(output_id("figure", block_id))
            if not figure.get("caption_embedded") and figure.get("target_caption"):
                add_caption(document, figure["target_caption"], figure_caption_style, figure["id"])
                outputs.append(output_id("figure-caption", block_id))
        elif kind == "formula":
            paragraph = document.add_paragraph()
            formula = formulas[block["formula_id"]]
            add_math_marker(paragraph, formula, math_actions)
            if formula["placement"] == "display":
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            outputs.append(output_id("formula", block_id))
        elif kind == "footnote_anchor":
            paragraph = document.add_paragraph(style=block.get("style_ref") or body_style)
            paragraph.add_run(block["target_text"])
            footnote = footnotes[block["footnote_id"]]
            marker = f"[[FOOTNOTE:{len(footnote_actions) + 1:04d}]]"
            paragraph.add_run(marker)
            footnote_actions.append({
                "marker": marker, "footnote_id": footnote["id"], "expected_number": footnote["number"],
                "numbering_scope": footnote["numbering_scope"], "text": footnote["target_text"],
            })
            outputs.append(output_id("paragraph-with-footnote", block_id))
        elif kind == "toc":
            paragraph = document.add_paragraph()
            add_field(paragraph, layout["toc"]["field_code"], "目录将在 Microsoft Word 中更新")
            outputs.append(output_id("toc-field", block_id))
        elif kind == "page_break":
            document.add_page_break()
            outputs.append(output_id("page-break", block_id))
        elif kind == "section_break":
            profile = section_profiles[block["section_id"]]
            break_type = {
                "continuous": WD_SECTION.CONTINUOUS, "new_page": WD_SECTION.NEW_PAGE,
                "odd_page": WD_SECTION.ODD_PAGE, "even_page": WD_SECTION.EVEN_PAGE,
            }[profile["break_type"]]
            section = document.add_section(break_type)
            configure_page(section, profile.get("page", layout["page_defaults"]))
            set_page_number_start(section, profile.get("page_number_start"))
            if "header_link_to_previous" in profile:
                section.header.is_linked_to_previous = bool(profile["header_link_to_previous"])
            if "footer_link_to_previous" in profile:
                section.footer.is_linked_to_previous = bool(profile["footer_link_to_previous"])
            if profile.get("header_text"):
                if "header_link_to_previous" not in profile:
                    section.header.is_linked_to_previous = False
                section.header.paragraphs[0].text = profile["header_text"]
            if profile.get("footer_text"):
                if "footer_link_to_previous" not in profile:
                    section.footer.is_linked_to_previous = False
                section.footer.paragraphs[0].text = profile["footer_text"]
            pending_title_spacing_override = profile.get("title_spacing_override")
            outputs.append(output_id("section-break", block_id))
        else:
            raise ValueError(f"Unsupported block type: {kind}")
        if paragraph is not None and block.get("keep_with_next"):
            paragraph.paragraph_format.keep_with_next = True
        record = {"source_block_ids": [block_id], "output_object_ids": outputs, "status": "converted" if kind in {"formula", "footnote_anchor"} else "written", "target": outputs[0] if outputs else ""}
        if kind in {"requirement", "regulatory_quote"}:
            record["owner_heading_id"] = block["owner_ref"]["id"]
        records.append(record)

    seen = [source_id for record in records for source_id in record["source_block_ids"]]
    source_ids = [block["id"] for block in blocks]
    if Counter(seen) != Counter(source_ids):
        missing = sorted(set(source_ids) - set(seen))
        repeated = sorted(item for item, count in Counter(seen).items() if count > 1)
        raise RuntimeError(f"Consumption invariant failed; missing={missing}, repeated={repeated}")

    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".docx", dir=output.parent)
    os.close(fd)
    try:
        document.save(temporary_name)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise

    actions = {
        "schema_version": "1.0", "math_actions": math_actions, "footnote_actions": footnote_actions,
        "expected_markers": {"math": len(math_actions), "footnotes": len(footnote_actions)},
    }
    status_counts = Counter(record["status"] for record in records)
    seed_material = project_config_sha256 + "".join(item["sha256"] for item in build_inputs)
    build_seed = hashlib.sha256(seed_material.encode("ascii")).hexdigest()[:16]
    ledger = {
        "schema_version": "1.0", "build_id": f"build-{build_seed}", "project_id": project["project_id"],
        "mode": validation["selected_mode"], "project_config_sha256": project_config_sha256,
        "cost_profile": project.get("cost_profile", "balanced"),
        "layout_profile_id": layout["profile_id"],
        "layout_profile_sha256": sha256_file(SKILL_ROOT / "profiles" / f"{layout['profile_id']}.json"),
        "input_files": build_inputs, "records": records,
        "derived_summary": {
            "source_total": len(source_ids), "recorded_total": len(seen), "unconsumed": 0,
            "written": status_counts["written"], "converted": status_counts["converted"],
            "merged": status_counts["merged"], "intentional_skip": status_counts["intentional_skip"],
        },
    }
    if "source_manifest" in paths:
        ledger["source_manifest_sha256"] = sha256_file(paths["source_manifest"])
    ledger_errors = schema_errors(ledger, "build_record.schema.json", "build ledger")
    if ledger_errors:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise RuntimeError("Generated build ledger failed schema validation:\n- " + "\n- ".join(ledger_errors))
    current_inputs = collect_build_inputs(project_path, project, paths)
    if current_inputs != build_inputs or sha256_file(project_path) != project_config_sha256:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise RuntimeError("A protected input changed during the build; no artifacts were published.")
    published_sidecars: list[Path] = []
    try:
        atomic_write_json(actions_path, actions)
        published_sidecars.append(actions_path)
        atomic_write_json(ledger_path, ledger)
        published_sidecars.append(ledger_path)
        os.replace(temporary_name, output)
    except Exception:
        for path in published_sidecars:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    print(f"Built {output} with {len(records)} source-block ledger records.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    build(args.project.resolve(), args.output.resolve(), args.actions.resolve(), args.ledger.resolve())


if __name__ == "__main__":
    main()
