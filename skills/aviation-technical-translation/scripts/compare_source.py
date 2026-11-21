"""Strictly compare structured source mappings with an authoritative English PDF.

The comparison is read-only apart from its JSON report. It checks every non-empty
source locator in the content map and its typed table, figure, formula, and
footnote objects. The English PDF is the only source used for content matching;
the Chinese draft is never treated as authority.

Input: project.json and its authoritative English PDF/structured mappings.
Output: a JSON comparison report; project inputs are never modified.
Run: python compare_source.py --project PROJECT/project.json --strict --report WORK/source_comparison.json
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Any

from common import (
    atomic_write_json,
    canonical_path,
    ensure_distinct_paths,
    load_json,
    load_jsonl,
    require_package,
    require_suffix,
    resolve_relative,
    sha256_file,
)


def normalize_text(value: str) -> str:
    """Normalize PDF line wrapping without changing technical tokens."""

    value = value.replace("\u00ad", "")
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def locator_pages(record: dict[str, Any]) -> list[int]:
    locator = record.get("source_locator") or {}
    values: list[Any] = []
    if locator.get("page") is not None:
        values.append(locator.get("page"))
    values.extend(locator.get("pages", []) or [])
    pages: list[int] = []
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1 and value not in pages:
            pages.append(value)
    return pages


def source_asset_id(record: dict[str, Any]) -> str | None:
    provenance = record.get("provenance")
    return provenance.get("source_asset_id") if isinstance(provenance, dict) else None


def add_match(
    results: list[dict[str, Any]],
    *,
    object_class: str,
    object_id: str,
    source_text: str,
    pages: list[int],
    page_texts: list[str],
) -> bool:
    normalized = normalize_text(source_text)
    if not normalized:
        return True
    combined = " ".join(page_texts)
    position = normalize_text(combined).find(normalized)
    matched = position >= 0
    results.append(
        {
            "object_class": object_class,
            "object_id": object_id,
            "pages": pages,
            "matched": matched,
            "position": position if matched else None,
            "source_text_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "source_text": source_text,
            "reason": None if matched else "SOURCE_TEXT_NOT_FOUND_IN_LOCATED_PAGES",
        }
    )
    return matched


def safe_report_path(project_path: Path, report_path: Path, protected_files: list[Path], protected_dirs: list[Path]) -> None:
    require_suffix(report_path, ".json", "--report")
    named = {"JSON report": report_path, "project": project_path}
    seen = {canonical_path(path) for path in named.values()}
    for index, path in enumerate(protected_files):
        key = canonical_path(path)
        if key in seen:
            continue
        named[f"protected_{index}"] = path
        seen.add(key)
    ensure_distinct_paths(named)
    report_key = canonical_path(report_path)
    for directory in protected_dirs:
        try:
            report_path.resolve().relative_to(directory.resolve())
        except ValueError:
            continue
        raise ValueError(f"--report must not be written inside protected source tree: {directory.resolve()}")
    if report_key == canonical_path(project_path):
        raise ValueError("--report must differ from --project")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--strict", action="store_true", help="Return failure when any non-empty mapped source text is unmatched.")
    parser.add_argument("--overwrite-report", action="store_true", help="Explicitly authorize replacing an existing JSON report.")
    args = parser.parse_args()

    project_path = args.project.resolve()
    report_path = args.report.resolve()
    if not project_path.is_file():
        raise SystemExit(f"Project file does not exist: {project_path}")
    try:
        require_suffix(project_path, ".json", "--project")
        project = load_json(project_path)
        base = project_path.parent
        paths = project.get("paths", {})
        content_path = resolve_relative(base, paths["content"])
        source_manifest_path = resolve_relative(base, paths["source_manifest"]) if paths.get("source_manifest") else None
        protected_files = [content_path]
        protected_dirs: list[Path] = [content_path.parent]
        if source_manifest_path:
            protected_files.append(source_manifest_path)
        for key in ("toc", "figures", "formulas", "footnotes", "layout", "terminology"):
            if paths.get(key):
                path = resolve_relative(base, paths[key])
                protected_files.append(path)
                if path.is_dir():
                    protected_dirs.append(path)
        if paths.get("tables_dir"):
            tables_dir = resolve_relative(base, paths["tables_dir"])
            protected_dirs.append(tables_dir)
            protected_files.extend(sorted(tables_dir.glob("*.json")))
        for item in project.get("inputs", []):
            if item.get("path"):
                protected_files.append(resolve_relative(base, item["path"]))
        safe_report_path(project_path, report_path, protected_files, protected_dirs)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    if report_path.exists() and not args.overwrite_report:
        raise SystemExit(f"Refusing to overwrite existing JSON report without --overwrite-report: {report_path}")

    pypdf = require_package("pypdf")
    source_inputs = [item for item in project.get("inputs", []) if item.get("role") == "source_document" and item.get("authoritative", True)]
    if len(source_inputs) != 1:
        raise SystemExit(f"Expected exactly one authoritative source_document input; found {len(source_inputs)}.")
    source_item = source_inputs[0]
    source_pdf = resolve_relative(base, source_item["path"])
    require_suffix(source_pdf, ".pdf", "authoritative source")
    source_hash = sha256_file(source_pdf)
    if source_item.get("sha256") and source_item.get("sha256") != source_hash:
        raise SystemExit("Authoritative source SHA-256 differs from the project lock; refresh the manifest before comparison.")
    reader = pypdf.PdfReader(str(source_pdf))
    page_texts = [page.extract_text() or "" for page in reader.pages]

    blocks = load_jsonl(resolve_relative(base, project["paths"]["content"]))
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    skipped_empty: list[str] = []
    mapped_pages: set[int] = set()
    checked_by_class: dict[str, int] = {}
    matched_by_class: dict[str, int] = {}
    dispositioned_by_class: dict[str, int] = {}

    def check(record: dict[str, Any], object_class: str, object_id: str, text: str) -> None:
        pages = locator_pages(record)
        if not normalize_text(text):
            skipped_empty.append(object_id)
            return
        checked_by_class[object_class] = checked_by_class.get(object_class, 0) + 1
        if not pages or min(pages) < 1 or max(pages) > len(page_texts):
            errors.append(f"{object_class} {object_id} has source locator pages outside 1..{len(page_texts)}: {pages}")
            matched = False
        else:
            mapped_pages.update(pages)
            matched = add_match(results, object_class=object_class, object_id=object_id, source_text=text, pages=pages, page_texts=[page_texts[p - 1] for p in pages])
        if matched:
            matched_by_class[object_class] = matched_by_class.get(object_class, 0) + 1
        else:
            flags = set(record.get("qa_flags", []) or [])
            if "SOURCE_TEXT_NOT_EXTRACTABLE" in flags:
                dispositioned_by_class[object_class] = dispositioned_by_class.get(object_class, 0) + 1
                warnings.append(f"{object_class} {object_id} was not extractable from source pages {pages}; explicit SOURCE_TEXT_NOT_EXTRACTABLE disposition recorded.")
                if results:
                    results[-1]["disposition"] = "SOURCE_TEXT_NOT_EXTRACTABLE"
            else:
                errors.append(f"{object_class} {object_id} source text was not found in located source pages {pages}; add an explicit extraction disposition or correct the mapping.")

    for block in blocks:
        block_id = str(block.get("id", "<missing>"))
        check(block, "block", block_id, str(block.get("source_text", "")))

    def load_objects(path_value: str | None) -> list[dict[str, Any]]:
        if not path_value:
            return []
        path = resolve_relative(base, path_value)
        if path.suffix.lower() == ".jsonl":
            return load_jsonl(path)
        value = load_json(path)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            if isinstance(value.get("figures"), list):
                return [item for item in value["figures"] if isinstance(item, dict)]
            return [value]
        return []

    tables_dir = resolve_relative(base, project["paths"]["tables_dir"]) if project["paths"].get("tables_dir") else None
    if tables_dir and tables_dir.is_dir():
        for table_path in sorted(tables_dir.glob("*.json")):
            table = load_json(table_path)
            table_id = str(table.get("id", table_path.stem))
            caption = table.get("caption") if isinstance(table.get("caption"), dict) else {}
            check(table, "table_caption", table_id, str(caption.get("source", "")))
            for column in table.get("columns", []):
                check(table, "table_column", f"{table_id}:{column.get('id', 'column')}", str(column.get("source_text", "")))
            for row in table.get("rows", []):
                for index, cell in enumerate(row.get("cells", []), 1):
                    check(table, "table_cell", f"{table_id}:{row.get('id', 'row')}:{index}", str(cell.get("source_text", "")))

    for figure in load_objects(project["paths"].get("figures")):
        figure_id = str(figure.get("id", "<missing>"))
        check(figure, "figure_caption", figure_id, str(figure.get("source_caption", "")))

    for formula in load_objects(project["paths"].get("formulas")):
        formula_id = str(formula.get("id", "<missing>"))
        check(formula, "formula", formula_id, str(formula.get("source_representation", "")))

    for footnote in load_objects(project["paths"].get("footnotes")):
        footnote_id = str(footnote.get("id", "<missing>"))
        check(footnote, "footnote", footnote_id, str(footnote.get("source_text", "")))

    pages_without_mapped_text = [number for number, text in enumerate(page_texts, 1) if normalize_text(text) and number not in mapped_pages]
    declared_page_count = source_item.get("page_count")
    if declared_page_count is not None and declared_page_count != len(page_texts):
        errors.append(f"Authoritative source declared page_count={declared_page_count} but PDF has {len(page_texts)} pages.")
    if pages_without_mapped_text:
        warnings.append("Source pages without nonempty mapped source_text: " + ", ".join(map(str, pages_without_mapped_text)) + ". A scoped review must record an explicit human coverage disposition.")
    if skipped_empty:
        warnings.append(f"Skipped {len(skipped_empty)} objects with empty source_text (normally structural objects): {', '.join(skipped_empty)}")
    if source_asset_id(source_item) not in {None, source_item.get("id")}:
        warnings.append("The authoritative source input has no matching provenance requirement; validate_project should enforce object provenance.")

    coverage = {
        "checked_nonempty_objects": sum(checked_by_class.values()),
        "matched_objects": sum(matched_by_class.values()),
        "unmatched_objects": sum(checked_by_class.values()) - sum(matched_by_class.values()),
        "match_ratio": (sum(matched_by_class.values()) / sum(checked_by_class.values())) if sum(checked_by_class.values()) else 1.0,
        "checked_by_class": checked_by_class,
        "matched_by_class": matched_by_class,
        "dispositioned_by_class": dispositioned_by_class,
        "mapped_pages": sorted(mapped_pages),
        "pages_without_mapped_text": pages_without_mapped_text,
        "coverage_disposition_required": bool(pages_without_mapped_text),
        "coverage_disposition": "REQUIRED" if pages_without_mapped_text else "NOT_REQUIRED",
        "skipped_empty_object_ids": skipped_empty,
    }
    unresolved_objects = coverage["unmatched_objects"] - sum(dispositioned_by_class.values())
    coverage["unresolved_objects"] = unresolved_objects
    passed = not errors and (not args.strict or unresolved_objects == 0)
    report = {
        "schema_version": "2.0",
        "status": "PASS" if passed else "FAIL",
        "comparison_status": "PASS" if passed else "FAIL",
        "strict": args.strict,
        "project": project_path.name,
        "source": {
            "id": source_item.get("id"),
            "path": source_item.get("path"),
            "sha256": source_hash,
            "source_manifest_sha256": sha256_file(source_manifest_path) if source_manifest_path and source_manifest_path.is_file() else None,
            "declared_page_count": source_item.get("page_count"),
            "actual_page_count": len(page_texts),
        },
        "coverage": coverage,
        "results": results,
        "errors": errors,
        "warnings": warnings,
    }
    atomic_write_json(report_path, report)
    print(f"{report['status']}: matched {coverage['matched_objects']}/{coverage['checked_nonempty_objects']} mapped objects -> {report_path}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
