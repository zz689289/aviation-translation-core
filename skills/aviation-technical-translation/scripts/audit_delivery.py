"""Compare DOCX semantics and, when supplied, rendered page pixels.

Usage:
    python audit_delivery.py --baseline approved.docx --candidate delivery.docx \
        --baseline-render approved_pages --candidate-render delivery_pages \
        --baseline-render-report approved_render_report.json \
        --candidate-render-report delivery_render_report.json \
        --report delivery_audit.json

The default render policy is exact pixel equality. A reviewed delivery profile
may explicitly set a per-channel ``--pixel-tolerance`` and a maximum changed-
pixel ratio. Volatile Word IDs are removed before XML comparison. All other
changed package members are blocking unless explicitly allowlisted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from common import (
    atomic_write_json,
    canonical_path,
    ensure_distinct_paths,
    load_json,
    require_package,
    require_suffix,
    sha256_file,
)


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W_NS, "m": M_NS, "r": R_NS}
VOLATILE_ATTRS = {
    "rsidR", "rsidRDefault", "rsidP", "rsidRPr", "rsidSect", "paraId",
    "textId", "durableId",
}
TOC_BOOKMARK_PATTERN = re.compile(r"_Toc[A-Za-z0-9_]+")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _toc_bookmark_name_map(root: Any) -> dict[str, str]:
    """Map Word-generated TOC bookmark names to deterministic document-order names."""

    mapping: dict[str, str] = {}
    toc_index = 0
    for node in root.xpath("//*[local-name()='bookmarkStart']"):
        name = node.attrib.get(f"{{{W_NS}}}name", "")
        if not name.startswith("_Toc"):
            continue
        if name in mapping:
            raise ValueError(f"Duplicate TOC bookmark name in DOCX: {name}")
        toc_index += 1
        mapping[name] = f"_TocNormalized_{toc_index}"
    return mapping


def _rewrite_toc_bookmark_tokens(value: str, mapping: dict[str, str]) -> str:
    return TOC_BOOKMARK_PATTERN.sub(lambda match: mapping.get(match.group(0), match.group(0)), value)


def _normalize_toc_bookmark_references(root: Any, mapping: dict[str, str]) -> None:
    """Normalize TOC bookmark definitions and every common reference to them."""

    for node in root.xpath("//*[local-name()='bookmarkStart']"):
        name_key = f"{{{W_NS}}}name"
        name = node.attrib.get(name_key, "")
        if name in mapping:
            node.attrib[name_key] = mapping[name]
    for node in root.xpath("//*[local-name()='hyperlink']"):
        anchor_key = f"{{{W_NS}}}anchor"
        anchor = node.attrib.get(anchor_key, "")
        if anchor in mapping:
            node.attrib[anchor_key] = mapping[anchor]
    for node in root.xpath("//*[local-name()='instrText']"):
        if node.text:
            node.text = _rewrite_toc_bookmark_tokens(node.text, mapping)
    for node in root.xpath("//*[local-name()='fldSimple']"):
        instruction_key = f"{{{W_NS}}}instr"
        instruction = node.attrib.get(instruction_key)
        if instruction:
            node.attrib[instruction_key] = _rewrite_toc_bookmark_tokens(instruction, mapping)


def _strip_volatile(root: Any) -> None:
    for node in root.iter():
        for key in list(node.attrib):
            if _local_name(key) in VOLATILE_ATTRS:
                del node.attrib[key]
    for node in list(root.xpath("//*[local-name()='proofErr']")):
        node.getparent().remove(node)
    bookmark_name_map = _toc_bookmark_name_map(root)
    _normalize_toc_bookmark_references(root, bookmark_name_map)
    bookmark_ids: dict[str, str] = {}
    for index, node in enumerate(root.xpath("//*[local-name()='bookmarkStart']"), 1):
        old_id = node.attrib.get(f"{{{W_NS}}}id", str(index))
        normalized_id = str(index)
        bookmark_ids[old_id] = normalized_id
        node.attrib[f"{{{W_NS}}}id"] = normalized_id
    next_id = len(bookmark_ids) + 1
    for node in root.xpath("//*[local-name()='bookmarkEnd']"):
        old_id = node.attrib.get(f"{{{W_NS}}}id", "")
        if old_id not in bookmark_ids:
            bookmark_ids[old_id] = str(next_id)
            next_id += 1
        node.attrib[f"{{{W_NS}}}id"] = bookmark_ids[old_id]


def normalize_xml(data: bytes) -> bytes:
    etree = require_package("lxml.etree", "lxml")
    parser = etree.XMLParser(remove_blank_text=True, recover=False)
    root = etree.fromstring(data, parser)
    _strip_volatile(root)
    return etree.tostring(root, method="c14n", exclusive=False, with_comments=False)


def _element_hash(node: Any) -> str:
    etree = require_package("lxml.etree", "lxml")
    clone = etree.fromstring(etree.tostring(node))
    _strip_volatile(clone)
    canonical = etree.tostring(clone, method="c14n", exclusive=False, with_comments=False)
    return _sha256_bytes(canonical)


def _attribute_map(node: Any | None) -> dict[str, str]:
    if node is None:
        return {}
    return {_local_name(key): value for key, value in sorted(node.attrib.items())}


def _paragraph_texts(root: Any) -> list[str]:
    return ["".join(p.xpath(".//w:t/text()", namespaces=NS)) for p in root.xpath("//w:p", namespaces=NS)]


def _omml_snapshot(document: Any) -> dict[str, Any]:
    expressions = []
    for index, node in enumerate(document.xpath("//m:oMath", namespaces=NS), 1):
        semantic_text = "".join(node.xpath(".//m:t/text()", namespaces=NS))
        expressions.append(
            {
                "index": index,
                "semantic_text": semantic_text,
                "semantic_text_sha256": _sha256_bytes(semantic_text.encode("utf-8")),
                "canonical_xml_sha256": _element_hash(node),
            }
        )
    return {"count": len(expressions), "expressions": expressions}


def _section_snapshot(document: Any) -> dict[str, Any]:
    sections = []
    for index, node in enumerate(document.xpath("//w:sectPr", namespaces=NS), 1):
        page_size = node.find(f"{{{W_NS}}}pgSz")
        margins = node.find(f"{{{W_NS}}}pgMar")
        columns = node.find(f"{{{W_NS}}}cols")
        page_numbers = node.find(f"{{{W_NS}}}pgNumType")
        section_type = node.find(f"{{{W_NS}}}type")
        geometry = {
            "page_size": _attribute_map(page_size),
            "margins": _attribute_map(margins),
            "columns": _attribute_map(columns),
            "page_numbering": _attribute_map(page_numbers),
            "section_type": _attribute_map(section_type),
            "title_page": node.find(f"{{{W_NS}}}titlePg") is not None,
        }
        header_references = [
            {"type": ref.get(f"{{{W_NS}}}type", "default"), "relationship_id": ref.get(f"{{{R_NS}}}id", "")}
            for ref in node.findall(f"{{{W_NS}}}headerReference")
        ]
        footer_references = [
            {"type": ref.get(f"{{{W_NS}}}type", "default"), "relationship_id": ref.get(f"{{{R_NS}}}id", "")}
            for ref in node.findall(f"{{{W_NS}}}footerReference")
        ]
        sections.append(
            {
                "index": index,
                "geometry": geometry,
                "geometry_sha256": _sha256_json(geometry),
                "header_references": header_references,
                "footer_references": footer_references,
                "canonical_xml_sha256": _element_hash(node),
            }
        )
    return {"count": len(sections), "sections": sections}


def _normalize_field_instruction(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_field_result(value: str) -> str:
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _toc_snapshot(document: Any) -> dict[str, Any]:
    """Extract TOC fields and the bookmark graph they depend on.

    Word is free to regenerate bookmark names on save.  The graph is therefore
    compared using deterministic names, while retaining the relationship between
    each hyperlink/PAGEREF and the paragraph that owns the target bookmark.
    """
    etree = require_package("lxml.etree", "lxml")
    fields: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for event, node in etree.iterwalk(document, events=("start", "end")):
        if not isinstance(node.tag, str):
            continue
        local = _local_name(node.tag)
        if event == "start":
            if local == "fldChar":
                field_type = node.get(f"{{{W_NS}}}fldCharType", "")
                if field_type == "begin":
                    stack.append({"phase": "instruction", "instruction": [], "result": []})
                elif field_type == "separate" and stack:
                    stack[-1]["phase"] = "result"
                elif field_type == "end" and stack:
                    completed = stack.pop()
                    instruction = _normalize_field_instruction("".join(completed["instruction"]))
                    if re.match(r"^TOC(?:\s|$)", instruction, re.IGNORECASE):
                        result = _normalize_field_result("".join(completed["result"]))
                        fields.append(
                            {
                                "instruction": instruction,
                                "instruction_sha256": _sha256_bytes(instruction.encode("utf-8")),
                                "result_text": result,
                                "result_text_sha256": _sha256_bytes(result.encode("utf-8")),
                            }
                        )
            elif local == "instrText" and stack:
                stack[-1]["instruction"].append(node.text or "")
            elif local == "t":
                for field in stack:
                    if field["phase"] == "result":
                        field["result"].append(node.text or "")
            elif local == "tab":
                for field in stack:
                    if field["phase"] == "result":
                        field["result"].append("\t")
            elif local == "br":
                for field in stack:
                    if field["phase"] == "result":
                        field["result"].append("\n")
        elif local == "p":
            for field in stack:
                if field["phase"] == "result":
                    field["result"].append("\n")

    for node in document.xpath("//w:fldSimple", namespaces=NS):
        instruction = _normalize_field_instruction(node.get(f"{{{W_NS}}}instr", ""))
        if re.match(r"^TOC(?:\s|$)", instruction, re.IGNORECASE):
            result = _normalize_field_result("".join(node.xpath(".//w:t/text()", namespaces=NS)))
            fields.append(
                {
                    "instruction": instruction,
                    "instruction_sha256": _sha256_bytes(instruction.encode("utf-8")),
                    "result_text": result,
                    "result_text_sha256": _sha256_bytes(result.encode("utf-8")),
                }
            )
    for index, field in enumerate(fields, 1):
        field["index"] = index
    mapping = _toc_bookmark_name_map(document)
    paragraphs = document.xpath("//w:body//w:p", namespaces=NS)
    paragraph_index = {id(node): index for index, node in enumerate(paragraphs, 1)}

    def owning_paragraph(node: Any) -> Any | None:
        current = node
        while current is not None:
            if _local_name(current.tag) == "p":
                return current
            current = current.getparent()
        return None

    bookmark_bindings: list[dict[str, Any]] = []
    target_text_by_name: dict[str, str] = {}
    for node in document.xpath("//*[local-name()='bookmarkStart']"):
        name = node.get(f"{{{W_NS}}}name", "")
        if not name.startswith("_Toc"):
            continue
        normalized = mapping.get(name, name)
        paragraph = owning_paragraph(node)
        text = "" if paragraph is None else "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
        target_text_by_name[normalized] = text
        bookmark_bindings.append(
            {
                "name": normalized,
                "target_text": text,
                "paragraph_index": paragraph_index.get(id(paragraph)),
            }
        )

    hyperlink_bindings: list[dict[str, Any]] = []
    for node in document.xpath("//*[local-name()='hyperlink']"):
        anchor = node.get(f"{{{W_NS}}}anchor", "")
        if anchor not in mapping and not anchor.startswith("_Toc"):
            continue
        normalized = mapping.get(anchor, anchor)
        paragraph = owning_paragraph(node)
        text = "".join(node.xpath(".//w:t/text()", namespaces=NS))
        hyperlink_bindings.append(
            {
                "anchor": normalized,
                "target_text": target_text_by_name.get(normalized),
                "display_text": text,
                "paragraph_index": paragraph_index.get(id(paragraph)),
            }
        )

    pageref_bindings: list[dict[str, Any]] = []
    for node in document.xpath("//*[local-name()='instrText']"):
        instruction = node.text or ""
        for match in re.finditer(r"\b(PAGEREF|REF)\s+(_Toc[A-Za-z0-9_]+)", instruction, re.IGNORECASE):
            paragraph = owning_paragraph(node)
            normalized = mapping.get(match.group(2), match.group(2))
            pageref_bindings.append(
                {
                    "field": match.group(1).upper(),
                    "anchor": normalized,
                    "target_text": target_text_by_name.get(normalized),
                    "paragraph_index": paragraph_index.get(id(paragraph)),
                }
            )
    return {
        "count": len(fields),
        "fields": fields,
        "bookmark_bindings": bookmark_bindings,
        "hyperlink_bindings": hyperlink_bindings,
        "pageref_bindings": pageref_bindings,
    }


def _headers_footers_snapshot(data: dict[str, bytes]) -> dict[str, Any]:
    etree = require_package("lxml.etree", "lxml")
    members: dict[str, Any] = {}
    for name in sorted(data):
        if not re.fullmatch(r"word/(?:header|footer)\d+\.xml", name):
            continue
        root = etree.fromstring(data[name])
        paragraphs = _paragraph_texts(root)
        text = "\n".join(paragraphs)
        members[name] = {
            "kind": "header" if "/header" in name else "footer",
            "paragraphs": paragraphs,
            "text_sha256": _sha256_bytes(text.encode("utf-8")),
            "canonical_xml_sha256": _sha256_bytes(normalize_xml(data[name])),
        }
    return {"count": len(members), "members": members}


def _styles_snapshot(data: dict[str, bytes]) -> dict[str, Any]:
    if "word/styles.xml" not in data:
        return {"present": False, "canonical_xml_sha256": None, "definitions": []}
    etree = require_package("lxml.etree", "lxml")
    root = etree.fromstring(data["word/styles.xml"])
    definitions = []
    for node in root.xpath("//w:style", namespaces=NS):
        def scalar(child: str, attribute: str = "val") -> str | None:
            match = node.find(f"{{{W_NS}}}{child}")
            return None if match is None else match.get(f"{{{W_NS}}}{attribute}")

        ppr = node.find(f"{{{W_NS}}}pPr")
        outline = None if ppr is None else ppr.find(f"{{{W_NS}}}outlineLvl")
        num_pr = None if ppr is None else ppr.find(f"{{{W_NS}}}numPr")
        num_id = None if num_pr is None else num_pr.find(f"{{{W_NS}}}numId")
        definitions.append(
            {
                "style_id": node.get(f"{{{W_NS}}}styleId", ""),
                "type": node.get(f"{{{W_NS}}}type", ""),
                "default": node.get(f"{{{W_NS}}}default", ""),
                "custom_style": node.get(f"{{{W_NS}}}customStyle", ""),
                "name": scalar("name"),
                "based_on": scalar("basedOn"),
                "next": scalar("next"),
                "linked_style": scalar("link"),
                "ui_priority": scalar("uiPriority"),
                "quick_format": node.find(f"{{{W_NS}}}qFormat") is not None,
                "outline_level": None if outline is None else outline.get(f"{{{W_NS}}}val"),
                "numbering_id": None if num_id is None else num_id.get(f"{{{W_NS}}}val"),
                "definition_sha256": _element_hash(node),
            }
        )
    definitions.sort(key=lambda item: (item["type"], item["style_id"]))
    return {
        "present": True,
        "canonical_xml_sha256": _sha256_bytes(normalize_xml(data["word/styles.xml"])),
        "definitions": definitions,
    }


def _metadata_snapshot(data: dict[str, bytes]) -> dict[str, Any]:
    etree = require_package("lxml.etree", "lxml")
    members: dict[str, Any] = {}
    for name in ("docProps/core.xml", "docProps/app.xml", "docProps/custom.xml"):
        if name not in data:
            continue
        root = etree.fromstring(data[name])
        properties = []
        for child in root:
            properties.append(
                {
                    "name": child.get("name") or _local_name(child.tag),
                    "value": "".join(child.itertext()),
                    "attributes": _attribute_map(child),
                    "value_type": _local_name(child[0].tag) if len(child) else None,
                }
            )
        members[name] = {
            "canonical_xml_sha256": _sha256_bytes(normalize_xml(data[name])),
            "properties": properties,
        }
    return {"count": len(members), "members": members}


def package_snapshot(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"DOCX contains duplicate ZIP members: {', '.join(duplicates)}")
        data = {name: archive.read(name) for name in names}
    if "word/document.xml" not in data:
        raise ValueError(f"DOCX has no word/document.xml: {path}")
    hashes = {}
    for name, content in data.items():
        normalized = normalize_xml(content) if name.endswith((".xml", ".rels")) else content
        hashes[name] = _sha256_bytes(normalized)

    etree = require_package("lxml.etree", "lxml")
    document = etree.fromstring(data["word/document.xml"])
    paragraphs = []
    for paragraph in document.xpath("//w:body//w:p", namespaces=NS):
        text = "".join(paragraph.xpath(".//w:t/text()", namespaces=NS))
        style = paragraph.xpath("string(./w:pPr/w:pStyle/@w:val)", namespaces=NS)
        paragraphs.append({"style": style, "text": text})
    table_cells = [
        "".join(cell.xpath(".//w:t/text()", namespaces=NS))
        for cell in document.xpath("//w:tbl//w:tc", namespaces=NS)
    ]
    images = {
        name: _sha256_bytes(content) for name, content in data.items() if name.startswith("word/media/")
    }
    footnote_texts = []
    if "word/footnotes.xml" in data:
        footnotes = etree.fromstring(data["word/footnotes.xml"])
        footnote_texts = [
            "".join(node.xpath(".//w:t/text()", namespaces=NS))
            for node in footnotes.xpath("//w:footnote[number(@w:id) >= 0]", namespaces=NS)
        ]
    return {
        "members": sorted(data),
        "member_hashes": hashes,
        "paragraphs": paragraphs,
        "table_cells": table_cells,
        "images": images,
        "footnotes": footnote_texts,
        "omml": _omml_snapshot(document),
        "sections": _section_snapshot(document),
        "toc": _toc_snapshot(document),
        "headers_footers": _headers_footers_snapshot(data),
        "styles": _styles_snapshot(data),
        "metadata": _metadata_snapshot(data),
    }


def _natural_page_key(path: Path) -> tuple[Any, ...]:
    return tuple(int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.name))


def _render_pages(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Render directory does not exist: {directory}")
    pages = {path.resolve() for pattern in ("page_*.png", "page-*.png") for path in directory.glob(pattern)}
    return sorted(pages, key=_natural_page_key)


def _changed_pixel_count(baseline_image: Any, candidate_image: Any, pixel_tolerance: int) -> int:
    image_chops = require_package("PIL.ImageChops", "Pillow")
    difference = image_chops.difference(baseline_image, candidate_image)
    masks = [band.point(lambda value: 255 if value > pixel_tolerance else 0) for band in difference.split()]
    combined = masks[0]
    for mask in masks[1:]:
        combined = image_chops.lighter(combined, mask)
    return combined.histogram()[255]


def compare_renders(
    baseline_directory: Path,
    candidate_directory: Path,
    *,
    pixel_tolerance: int,
    max_different_pixel_ratio: float,
    approved_changed_pages: set[int] | None = None,
) -> dict[str, Any]:
    image_module = require_package("PIL.Image", "Pillow")
    approved_changed_pages = set(approved_changed_pages or set())
    effective_pixel_tolerance = 0 if approved_changed_pages else pixel_tolerance
    baseline_pages = _render_pages(baseline_directory)
    candidate_pages = _render_pages(candidate_directory)
    details = []
    for index in range(max(len(baseline_pages), len(candidate_pages))):
        baseline_page = baseline_pages[index] if index < len(baseline_pages) else None
        candidate_page = candidate_pages[index] if index < len(candidate_pages) else None
        detail: dict[str, Any] = {
            "page_index": index + 1,
            "approved_to_change": index + 1 in approved_changed_pages,
            "baseline_file": baseline_page.name if baseline_page else None,
            "candidate_file": candidate_page.name if candidate_page else None,
        }
        if baseline_page is None or candidate_page is None:
            detail.update(
                {
                    "dimensions_equal": False,
                    "baseline_dimensions": None,
                    "candidate_dimensions": None,
                    "different_pixels": None,
                    "total_pixels": None,
                    "different_pixel_ratio": None,
                    "exact_file_hash_equal": False,
                    "passed": False,
                    "reason": "MISSING_PAGE",
                }
            )
            details.append(detail)
            continue
        exact_hash_equal = sha256_file(baseline_page) == sha256_file(candidate_page)
        with image_module.open(baseline_page) as left_source, image_module.open(candidate_page) as right_source:
            left_size = left_source.size
            right_size = right_source.size
            dimensions_equal = left_size == right_size
            detail.update(
                {
                    "dimensions_equal": dimensions_equal,
                    "baseline_dimensions": list(left_size),
                    "candidate_dimensions": list(right_size),
                    "exact_file_hash_equal": exact_hash_equal,
                }
            )
            if not dimensions_equal:
                detail.update(
                    {
                        "different_pixels": None,
                        "total_pixels": None,
                        "different_pixel_ratio": None,
                        "passed": False,
                        "reason": "DIMENSION_MISMATCH",
                    }
                )
            else:
                left = left_source.convert("RGBA")
                right = right_source.convert("RGBA")
                total_pixels = left_size[0] * left_size[1]
                changed = _changed_pixel_count(left, right, effective_pixel_tolerance)
                ratio = changed / total_pixels if total_pixels else 0.0
                if approved_changed_pages:
                    passed = bool(detail["approved_to_change"] or changed == 0)
                    reason = None if passed else "UNAPPROVED_PAGE_PIXEL_CHANGE"
                else:
                    passed = ratio <= max_different_pixel_ratio
                    reason = None if passed else "PIXEL_RATIO_EXCEEDED"
                detail.update(
                    {
                        "different_pixels": changed,
                        "total_pixels": total_pixels,
                        "different_pixel_ratio": ratio,
                        "passed": passed,
                        "reason": reason,
                    }
                )
        details.append(detail)
    page_count_equal = len(baseline_pages) == len(candidate_pages)
    pages_present = bool(baseline_pages) and bool(candidate_pages)
    passed = pages_present and page_count_equal and all(page["passed"] for page in details)
    return {
        "policy": (
            "approved_changed_pages_exact_elsewhere"
            if approved_changed_pages
            else ("exact" if pixel_tolerance == 0 and max_different_pixel_ratio == 0 else "declared_tolerance")
        ),
        "approved_changed_pages": sorted(approved_changed_pages),
        "changed_approved_pages": [
            page["page_index"] for page in details
            if page.get("approved_to_change") and (page.get("different_pixels") or not page.get("dimensions_equal"))
        ],
        "changed_unapproved_pages": [
            page["page_index"] for page in details
            if not page.get("approved_to_change") and (page.get("different_pixels") or not page.get("dimensions_equal"))
        ],
        "pixel_tolerance": effective_pixel_tolerance,
        "max_different_pixel_ratio": max_different_pixel_ratio,
        "baseline_pages": len(baseline_pages),
        "candidate_pages": len(candidate_pages),
        "pages_present": pages_present,
        "page_count_equal": page_count_equal,
        "dimensions_equal": bool(details) and all(page["dimensions_equal"] for page in details),
        "exact_file_hash_equal": page_count_equal and all(page["exact_file_hash_equal"] for page in details),
        "exact_pixel_equal": bool(details) and all(page.get("different_pixel_ratio") == 0 for page in details),
        "pages": details,
        "passed": passed,
    }


def _ensure_render_directories_distinct(baseline_directory: Path, candidate_directory: Path) -> None:
    baseline = baseline_directory.resolve()
    candidate = candidate_directory.resolve()
    if canonical_path(baseline) == canonical_path(candidate):
        raise ValueError("Baseline and candidate render directories must differ.")
    for label, left, right in (("baseline", baseline, candidate), ("candidate", candidate, baseline)):
        try:
            right.relative_to(left)
        except ValueError:
            continue
        raise ValueError(f"{label} render directory must not contain the other render directory: {left}")


def _verify_render_report(report_path: Path, pages_directory: Path, docx_path: Path, label: str) -> dict[str, Any]:
    report = load_json(report_path)
    if not isinstance(report, dict) or report.get("status") != "PASS" or not report.get("stable") or not report.get("structure_pass"):
        raise ValueError(f"{label} render report is not a stable PASS: {report_path}")
    runs = report.get("runs")
    if not isinstance(runs, list):
        raise ValueError(f"{label} render report has no runs list: {report_path}")
    pages_directory = pages_directory.resolve()
    matches = []
    for run in runs:
        relative = run.get("pages_relative") if isinstance(run, dict) else None
        if not isinstance(relative, str):
            continue
        if (report_path.parent / Path(relative)).resolve() == pages_directory:
            matches.append(run)
    if len(matches) != 1:
        raise ValueError(f"{label} pages directory is not uniquely bound to a run in {report_path}: {pages_directory}")
    run = matches[0]
    actual_docx_sha = sha256_file(docx_path)
    accepted_docx_shas = {run.get("docx_sha256"), report.get("input_sha256")}
    if actual_docx_sha not in accepted_docx_shas:
        raise ValueError(f"{label} DOCX SHA-256 is not the input or postprocessed working DOCX recorded by {report_path}.")
    pages = _render_pages(pages_directory)
    expected_files = run.get("page_files")
    expected_hashes = run.get("page_sha256")
    if not isinstance(expected_files, list) or not isinstance(expected_hashes, list) or len(expected_files) != len(expected_hashes):
        raise ValueError(f"{label} render report has incomplete page identity data: {report_path}")
    if [path.name for path in pages] != expected_files:
        raise ValueError(f"{label} page file list differs from the bound render report: {pages_directory}")
    actual_hashes = [sha256_file(path) for path in pages]
    if actual_hashes != expected_hashes:
        raise ValueError(f"{label} page hashes differ from the bound render report: {pages_directory}")
    return {"report": report_path.name, "run": run.get("run"), "docx_sha256": actual_docx_sha, "pages_sha256": actual_hashes}


def _semantic_members(key: str, baseline: dict[str, Any], candidate: dict[str, Any]) -> set[str]:
    if key in {
        "paragraphs_equal", "table_cells_equal", "omath_count_equal", "omml_equal",
        "section_count_equal", "sections_equal", "toc_equal",
    }:
        return {"word/document.xml"}
    if key == "images_equal":
        return set(baseline["images"]) | set(candidate["images"])
    if key == "footnotes_equal":
        return {"word/footnotes.xml"}
    if key == "headers_footers_equal":
        return set(baseline["headers_footers"]["members"]) | set(candidate["headers_footers"]["members"])
    if key == "styles_equal":
        return {"word/styles.xml"}
    if key == "metadata_equal":
        return set(baseline["metadata"]["members"]) | set(candidate["metadata"]["members"])
    return set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--baseline-render", type=Path)
    parser.add_argument("--candidate-render", type=Path)
    parser.add_argument("--baseline-render-report", type=Path)
    parser.add_argument("--candidate-render-report", type=Path)
    parser.add_argument("--pixel-tolerance", type=int, default=0, help="Allowed per-channel difference, 0-255; default 0.")
    parser.add_argument(
        "--max-different-pixel-ratio",
        type=float,
        default=0.0,
        help="Maximum fraction of pixels exceeding --pixel-tolerance, 0-1; default 0.",
    )
    parser.add_argument(
        "--approved-changed-page",
        type=int,
        action="append",
        default=[],
        help=(
            "One-based page allowed to change in a local layout revision; repeatable. "
            "When supplied, every other page must be decoded-pixel identical."
        ),
    )
    parser.add_argument("--allow-member", action="append", default=[])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--overwrite-report", action="store_true", help="Explicitly authorize replacing an existing audit report.")
    args = parser.parse_args()

    if not 0 <= args.pixel_tolerance <= 255:
        parser.error("--pixel-tolerance must be between 0 and 255.")
    if not 0.0 <= args.max_different_pixel_ratio <= 1.0:
        parser.error("--max-different-pixel-ratio must be between 0 and 1.")
    if any(page < 1 for page in args.approved_changed_page):
        parser.error("--approved-changed-page values must be positive one-based page numbers.")
    if len(args.approved_changed_page) != len(set(args.approved_changed_page)):
        parser.error("--approved-changed-page values must be unique.")
    if bool(args.baseline_render) != bool(args.candidate_render):
        parser.error("--baseline-render and --candidate-render are required together.")
    if bool(args.baseline_render_report) != bool(args.candidate_render_report):
        parser.error("--baseline-render-report and --candidate-render-report are required together.")
    if bool(args.baseline_render) != bool(args.baseline_render_report):
        parser.error("Render directories require matching render reports so pixels are bound to the audited DOCX files.")
    if (args.pixel_tolerance or args.max_different_pixel_ratio) and not args.baseline_render:
        parser.error("Pixel tolerance options require both render directories.")
    if args.approved_changed_page and not args.baseline_render:
        parser.error("--approved-changed-page requires both render directories and their reports.")
    if args.approved_changed_page and (args.pixel_tolerance or args.max_different_pixel_ratio):
        parser.error("Approved-page regression is exact outside the allowlist and cannot be combined with pixel tolerances.")

    baseline_path = args.baseline.resolve()
    candidate_path = args.candidate.resolve()
    report_path = args.report.resolve()
    baseline_render_path = args.baseline_render.resolve() if args.baseline_render else None
    candidate_render_path = args.candidate_render.resolve() if args.candidate_render else None
    baseline_render_report_path = args.baseline_render_report.resolve() if args.baseline_render_report else None
    candidate_render_report_path = args.candidate_render_report.resolve() if args.candidate_render_report else None
    try:
        require_suffix(baseline_path, ".docx", "--baseline")
        require_suffix(candidate_path, ".docx", "--candidate")
        require_suffix(report_path, ".json", "--report")
        if baseline_render_report_path:
            require_suffix(baseline_render_report_path, ".json", "--baseline-render-report")
            require_suffix(candidate_render_report_path, ".json", "--candidate-render-report")
        named_paths = {"baseline DOCX": baseline_path, "candidate DOCX": candidate_path, "JSON report": report_path}
        if baseline_render_report_path:
            named_paths["baseline render report"] = baseline_render_report_path
            named_paths["candidate render report"] = candidate_render_report_path
        ensure_distinct_paths(named_paths)
        if baseline_render_path and candidate_render_path:
            _ensure_render_directories_distinct(baseline_render_path, candidate_render_path)
            for label, report_file, render_dir in (
                ("baseline", baseline_render_report_path, baseline_render_path),
                ("candidate", candidate_render_report_path, candidate_render_path),
            ):
                if report_file is None:
                    raise ValueError(f"Missing {label} render report")
                if report_path == report_file:
                    raise ValueError("Audit report must not overwrite a render report.")
                try:
                    report_path.relative_to(render_dir)
                except ValueError:
                    pass
                else:
                    raise ValueError("Audit report must be outside both render directories.")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if report_path.exists() and not args.overwrite_report:
        raise SystemExit(f"Refusing to overwrite existing audit report without --overwrite-report: {report_path}")
    baseline = package_snapshot(baseline_path)
    candidate = package_snapshot(candidate_path)
    allowed = set(args.allow_member)
    member_set_changed = sorted(set(baseline["members"]) ^ set(candidate["members"]))
    changed = sorted(
        name
        for name in set(baseline["member_hashes"]) & set(candidate["member_hashes"])
        if baseline["member_hashes"][name] != candidate["member_hashes"][name]
    )
    changed_package_members = set(member_set_changed) | set(changed)
    unexpected_members = sorted(name for name in changed_package_members if name not in allowed)

    semantic = {
        "paragraphs_equal": baseline["paragraphs"] == candidate["paragraphs"],
        "table_cells_equal": baseline["table_cells"] == candidate["table_cells"],
        "images_equal": baseline["images"] == candidate["images"],
        "footnotes_equal": baseline["footnotes"] == candidate["footnotes"],
        "omath_count_equal": baseline["omml"]["count"] == candidate["omml"]["count"],
        "omml_equal": baseline["omml"] == candidate["omml"],
        "section_count_equal": baseline["sections"]["count"] == candidate["sections"]["count"],
        "sections_equal": baseline["sections"] == candidate["sections"],
        "toc_equal": baseline["toc"] == candidate["toc"],
        "headers_footers_equal": baseline["headers_footers"] == candidate["headers_footers"],
        "styles_equal": baseline["styles"] == candidate["styles"],
        "metadata_equal": baseline["metadata"] == candidate["metadata"],
    }
    semantic_mismatches = sorted(key for key, equal in semantic.items() if not equal)
    unexpected_semantic_mismatches = []
    semantic_enforcement: dict[str, Any] = {}
    for key in semantic:
        relevant = _semantic_members(key, baseline, candidate)
        changed_relevant = sorted(relevant & changed_package_members)
        unapproved = sorted(member for member in changed_relevant if member not in allowed)
        enforced_pass = semantic[key] or (bool(changed_relevant) and not unapproved)
        semantic_enforcement[key] = {
            "equal": semantic[key],
            "relevant_members": sorted(relevant),
            "changed_members": changed_relevant,
            "unapproved_changed_members": unapproved,
            "passed": enforced_pass,
        }
        if not enforced_pass:
            unexpected_semantic_mismatches.append(key)

    render_detail = None
    render_binding = None
    if args.baseline_render:
        try:
            render_binding = {
                "baseline": _verify_render_report(baseline_render_report_path, baseline_render_path, baseline_path, "Baseline"),
                "candidate": _verify_render_report(candidate_render_report_path, candidate_render_path, candidate_path, "Candidate"),
            }
        except (ValueError, FileNotFoundError, KeyError) as exc:
            raise SystemExit(str(exc)) from exc
        render_detail = compare_renders(
            baseline_render_path,
            candidate_render_path,
            pixel_tolerance=args.pixel_tolerance,
            max_different_pixel_ratio=args.max_different_pixel_ratio,
            approved_changed_pages=set(args.approved_changed_page),
        )
    render_passed = render_detail is None or render_detail["passed"]
    passed = not unexpected_members and not unexpected_semantic_mismatches and render_passed
    report = {
        "schema_version": "2.0",
        "status": "PASS" if passed else "FAIL",
        "baseline_sha256": sha256_file(baseline_path),
        "candidate_sha256": sha256_file(candidate_path),
        "allowed_members": sorted(allowed),
        "changed_members": changed,
        "member_set_delta": member_set_changed,
        "unexpected_members": unexpected_members,
        "semantic": semantic,
        "semantic_mismatches": semantic_mismatches,
        "unexpected_semantic_mismatches": unexpected_semantic_mismatches,
        "semantic_enforcement": semantic_enforcement,
        "semantic_details": {
            "baseline": {
                "omml": baseline["omml"],
                "sections": baseline["sections"],
                "toc": baseline["toc"],
                "headers_footers": baseline["headers_footers"],
                "styles": baseline["styles"],
                "metadata": baseline["metadata"],
            },
            "candidate": {
                "omml": candidate["omml"],
                "sections": candidate["sections"],
                "toc": candidate["toc"],
                "headers_footers": candidate["headers_footers"],
                "styles": candidate["styles"],
                "metadata": candidate["metadata"],
            },
        },
        "render": render_detail,
        "render_binding": render_binding,
    }
    atomic_write_json(report_path, report)
    print(
        f"{report['status']}: unexpected package changes={len(unexpected_members)}, "
        f"unexpected semantic changes={len(unexpected_semantic_mismatches)} -> {report_path}"
    )
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
