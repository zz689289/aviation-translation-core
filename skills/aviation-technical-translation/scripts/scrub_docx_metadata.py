"""Scrub DOCX metadata on a copy and verify prohibited strings.

Usage:
    python scrub_docx_metadata.py input.docx --output delivery.docx \
        --title "Public title" --subject "Chinese translation" \
        --prohibit internal-pipeline --report scrub.json

The input is never overwritten. The ZIP is written to a temporary file, tested,
and atomically moved to the requested output.
"""

from __future__ import annotations

import argparse
import os
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from common import atomic_write_json, ensure_distinct_paths, require_suffix, sha256_file


CORE_NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
}
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
COMMENT_PART_BASENAMES = {
    "comments.xml",
    "commentsextended.xml",
    "commentsextensible.xml",
    "commentsids.xml",
    "commentauthors.xml",
    "people.xml",
}
COMMENT_MARKERS = {"commentRangeStart", "commentRangeEnd", "commentReference"}


def clear_core(data: bytes, clear: set[str], values: dict[str, str | None]) -> bytes:
    root = ET.fromstring(data)
    elements = {
        "title": root.find("dc:title", CORE_NS), "subject": root.find("dc:subject", CORE_NS),
        "creator": root.find("dc:creator", CORE_NS), "description": root.find("dc:description", CORE_NS),
        "lastModifiedBy": root.find("cp:lastModifiedBy", CORE_NS), "keywords": root.find("cp:keywords", CORE_NS),
        "revision": root.find("cp:revision", CORE_NS), "created": root.find("dcterms:created", CORE_NS),
        "modified": root.find("dcterms:modified", CORE_NS),
    }
    for name in clear:
        if elements.get(name) is not None:
            if name in {"created", "modified"}:
                root.remove(elements[name])
                elements[name] = None
            else:
                elements[name].text = ""
    for name, value in values.items():
        if value is not None and elements.get(name) is not None:
            elements[name].text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def clear_extended(data: bytes) -> bytes:
    root = ET.fromstring(data)
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] in {"Company", "Manager", "HyperlinkBase"}:
            node.text = ""
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def remove_custom_relationships(data: bytes) -> bytes:
    root = ET.fromstring(data)
    for node in list(root):
        target = (node.attrib.get("Target") or "").replace("\\", "/")
        rel_type = node.attrib.get("Type") or ""
        if target.endswith("docProps/custom.xml") or rel_type.endswith("/custom-properties"):
            root.remove(node)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def remove_custom_content_type(data: bytes) -> bytes:
    root = ET.fromstring(data)
    for node in list(root):
        if (node.attrib.get("PartName") or "").lower() == "/docprops/custom.xml":
            root.remove(node)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def is_comment_part(name: str) -> bool:
    normalized = name.replace("\\", "/").lower().lstrip("/")
    return normalized.startswith("word/") and normalized.rsplit("/", 1)[-1] in COMMENT_PART_BASENAMES


def is_comment_relationship(node: ET.Element) -> bool:
    target = (node.attrib.get("Target") or "").replace("\\", "/").lower()
    rel_type = (node.attrib.get("Type") or "").lower()
    target_name = target.rsplit("/", 1)[-1]
    return target_name in COMMENT_PART_BASENAMES or any(
        token in rel_type
        for token in ("/comments", "/commentsextended", "/commentsids", "/commentsextensible", "/people")
    )


def remove_comment_relationships(data: bytes) -> bytes:
    root = ET.fromstring(data)
    removed = False
    for node in list(root):
        if is_comment_relationship(node):
            root.remove(node)
            removed = True
    if not removed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def remove_comment_content_types(data: bytes) -> bytes:
    root = ET.fromstring(data)
    removed = False
    for node in list(root):
        part_name = node.attrib.get("PartName") or ""
        content_type = (node.attrib.get("ContentType") or "").lower()
        if is_comment_part(part_name) or "comments" in content_type or content_type.endswith("people+xml"):
            root.remove(node)
            removed = True
    if not removed:
        return data
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def remove_comment_markers(data: bytes) -> tuple[bytes, int]:
    root = ET.fromstring(data)
    parents = {child: parent for parent in root.iter() for child in parent}
    removed = 0
    for node in list(root.iter()):
        namespace, separator, local_name = node.tag[1:].partition("}") if node.tag.startswith("{") else ("", "", node.tag)
        if separator and namespace == W_NS and local_name in COMMENT_MARKERS:
            parent = parents.get(node)
            if parent is not None:
                parent.remove(node)
                removed += 1
    if not removed:
        return data, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=True), removed


def find_comment_residuals(members: dict[str, bytes]) -> list[str]:
    residuals = [f"part:{name}" for name in sorted(members) if is_comment_part(name)]
    for name, data in sorted(members.items()):
        if name.endswith(".rels"):
            root = ET.fromstring(data)
            if any(is_comment_relationship(node) for node in root):
                residuals.append(f"relationship:{name}")
        elif name.startswith("word/") and name.endswith(".xml"):
            root = ET.fromstring(data)
            for node in root.iter():
                namespace, separator, local_name = node.tag[1:].partition("}") if node.tag.startswith("{") else ("", "", node.tag)
                if separator and namespace == W_NS and local_name in COMMENT_MARKERS:
                    residuals.append(f"marker:{name}:{local_name}")
                    break
    return residuals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title")
    parser.add_argument("--subject")
    parser.add_argument("--revision", default="1")
    parser.add_argument("--clear", default="creator,lastModifiedBy,keywords,description,created,modified")
    parser.add_argument(
        "--remove-custom-properties",
        action="store_true",
        default=True,
        help="Remove custom properties (the safe delivery default; the flag remains accepted for compatibility).",
    )
    parser.add_argument("--keep-extended", action="store_true", help="Do not clear Company, Manager, and HyperlinkBase in app.xml.")
    parser.add_argument("--prohibit", action="append", default=[])
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--overwrite-output",
        action="store_true",
        help="Explicitly authorize replacing an existing output DOCX. The input is still never overwritten.",
    )
    parser.add_argument(
        "--overwrite-report",
        action="store_true",
        help="Explicitly authorize replacing an existing JSON report.",
    )
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve() if args.report else None
    try:
        require_suffix(source, ".docx", "input")
        require_suffix(output, ".docx", "--output")
        named_paths = {"input DOCX": source, "output DOCX": output}
        if report_path is not None:
            require_suffix(report_path, ".json", "--report")
            named_paths["JSON report"] = report_path
        ensure_distinct_paths(named_paths)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if not source.is_file():
        raise SystemExit(f"Input DOCX does not exist: {source}")
    if output.exists() and not args.overwrite_output:
        raise SystemExit(f"Refusing to overwrite existing output DOCX without --overwrite-output: {output}")
    if report_path is not None and report_path.exists() and not args.overwrite_report:
        raise SystemExit(f"Refusing to overwrite existing JSON report without --overwrite-report: {report_path}")
    output.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise SystemExit(f"Input DOCX contains duplicate ZIP members: {', '.join(duplicates)}")
        members = {info.filename: archive.read(info.filename) for info in infos}
    changed: list[str] = []
    deleted: list[str] = []
    if "docProps/core.xml" in members:
        new_data = clear_core(
            members["docProps/core.xml"],
            {item.strip() for item in args.clear.split(",") if item.strip()},
            {"title": args.title, "subject": args.subject, "revision": args.revision},
        )
        if new_data != members["docProps/core.xml"]:
            members["docProps/core.xml"] = new_data
            changed.append("docProps/core.xml")
    if not args.keep_extended and "docProps/app.xml" in members:
        new_data = clear_extended(members["docProps/app.xml"])
        if new_data != members["docProps/app.xml"]:
            members["docProps/app.xml"] = new_data
            changed.append("docProps/app.xml")
    if args.remove_custom_properties and "docProps/custom.xml" in members:
        del members["docProps/custom.xml"]
        deleted.append("docProps/custom.xml")
        if "_rels/.rels" in members:
            members["_rels/.rels"] = remove_custom_relationships(members["_rels/.rels"])
            changed.append("_rels/.rels")
        if "[Content_Types].xml" in members:
            members["[Content_Types].xml"] = remove_custom_content_type(members["[Content_Types].xml"])
            changed.append("[Content_Types].xml")

    comment_parts = sorted(name for name in members if is_comment_part(name))
    for name in comment_parts:
        del members[name]
        deleted.append(name)
    for name in sorted(member for member in members if member.endswith(".rels")):
        new_data = remove_comment_relationships(members[name])
        if new_data != members[name]:
            members[name] = new_data
            changed.append(name)
    if "[Content_Types].xml" in members:
        new_data = remove_comment_content_types(members["[Content_Types].xml"])
        if new_data != members["[Content_Types].xml"]:
            members["[Content_Types].xml"] = new_data
            changed.append("[Content_Types].xml")
    removed_comment_markers = 0
    for name in sorted(member for member in members if member.startswith("word/") and member.endswith(".xml")):
        new_data, removed_count = remove_comment_markers(members[name])
        if removed_count:
            members[name] = new_data
            changed.append(name)
            removed_comment_markers += removed_count

    residual_comment_artifacts = find_comment_residuals(members)
    residual_custom_properties = [name for name in members if name.lower() == "docprops/custom.xml"]

    fd, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".docx", dir=output.parent)
    os.close(fd)
    try:
        info_by_name = {info.filename: info for info in infos}
        with zipfile.ZipFile(temporary_name, "w") as archive:
            for name, data in members.items():
                archive.writestr(info_by_name[name], data)
        with zipfile.ZipFile(temporary_name) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise RuntimeError(f"ZIP integrity check failed at {bad_member}")
        prohibited_hits = []
        lowered_terms = [(term, term.casefold()) for term in args.prohibit]
        with zipfile.ZipFile(temporary_name) as archive:
            for name in archive.namelist():
                if not name.endswith((".xml", ".rels")):
                    continue
                text = archive.read(name).decode("utf-8", errors="ignore").casefold()
                for original, lowered in lowered_terms:
                    if lowered and lowered in text:
                        prohibited_hits.append({"term": original, "member": name})
        candidate_sha256 = sha256_file(Path(temporary_name))
        blocking_issues = [
            *(f"COMMENT_ARTIFACT_REMAINS:{item}" for item in residual_comment_artifacts),
            *(f"CUSTOM_PROPERTY_REMAINS:{item}" for item in residual_custom_properties),
        ]
        report = {
            "schema_version": "1.0", "status": "PASS" if not prohibited_hits and not blocking_issues else "FAIL",
            "input_sha256": sha256_file(source), "output_sha256": candidate_sha256,
            "output_published": not prohibited_hits and not blocking_issues,
            "changed_members": sorted(set(changed)), "deleted_members": sorted(deleted),
            "removed_comment_markers": removed_comment_markers,
            "residual_comment_artifacts": residual_comment_artifacts,
            "prohibited_hits": prohibited_hits, "blocking_issues": blocking_issues,
        }
        if prohibited_hits or blocking_issues:
            os.unlink(temporary_name)
            if report_path is not None:
                atomic_write_json(report_path, report)
            print(f"FAIL: prohibited metadata/content found; output was not published -> {output}")
            raise SystemExit(1)
        os.replace(temporary_name, output)
        if report_path is not None:
            atomic_write_json(report_path, report)
        print(f"PASS: scrubbed metadata -> {output}")
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


if __name__ == "__main__":
    main()
