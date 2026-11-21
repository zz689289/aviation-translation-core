"""Validate a project, its structured content, and mode-specific gates.

Usage:
    python validate_project.py --project PROJECT/project.json --report WORK/project_validation.json

Validation is read-only except for the report. It never overwrites a project
input and exits non-zero when a blocking error is found.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from common import (
    atomic_write_json,
    ensure_distinct_paths,
    load_json,
    load_jsonl,
    load_layout_profile,
    require_suffix,
    resolve_layout_profile,
    resolve_relative,
    schema_validation_errors,
    sha256_file,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = SKILL_ROOT / "schemas"


def _type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict), "array": isinstance(value, list), "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool), "null": value is None,
    }.get(expected, True)


def _resolve_ref(root: dict[str, Any], reference: str) -> dict[str, Any]:
    if not reference.startswith("#/"):
        raise ValueError(f"The dependency-light validator supports internal references only: {reference}")
    node: Any = root
    for part in reference[2:].split("/"):
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _mini_schema_errors(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "<root>") -> list[str]:
    if "$ref" in schema:
        return _mini_schema_errors(value, _resolve_ref(root, schema["$ref"]), root, path)
    errors: list[str] = []
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, item) for item in types):
            return [f"{path}: expected type {types}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in {schema['enum']!r}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than {schema['minLength']}")
        if schema.get("pattern") and not re.search(schema["pattern"], value):
            errors.append(f"{path}: string does not match pattern {schema['pattern']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value is below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value is above maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: value must be greater than {schema['exclusiveMinimum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array has fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array has more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            normalized = [repr(item) for item in value]
            if len(normalized) != len(set(normalized)):
                errors.append(f"{path}: array items are not unique")
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                errors.extend(_mini_schema_errors(item, schema["items"], root, f"{path}/{index}"))
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key}")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}/{key}"
            if key in properties:
                errors.extend(_mini_schema_errors(item, properties[key], root, child_path))
            elif additional is False:
                errors.append(f"{child_path}: additional property is not allowed")
            elif isinstance(additional, dict):
                errors.extend(_mini_schema_errors(item, additional, root, child_path))
    if "not" in schema and not _mini_schema_errors(value, schema["not"], root, path):
        errors.append(f"{path}: value matches a forbidden schema")
    for sub_schema in schema.get("allOf", []):
        if "if" in sub_schema:
            if not _mini_schema_errors(value, sub_schema["if"], root, path):
                errors.extend(_mini_schema_errors(value, sub_schema.get("then", {}), root, path))
        else:
            errors.extend(_mini_schema_errors(value, sub_schema, root, path))
    return errors


def schema_errors(value: Any, schema_name: str, label: str) -> list[str]:
    return [
        f"{label}:{error}"
        for error in schema_validation_errors(value, SCHEMAS / schema_name)
    ]


def load_objects(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return load_jsonl(path)
    value = load_json(path)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "figures", "formulas", "footnotes"):
            if isinstance(value.get(key), list):
                return value[key]
    raise ValueError(f"Expected an array or JSONL object stream: {path}")


def locator_pages(locator: dict[str, Any]) -> list[int]:
    """Return the ordered, de-duplicated page span declared by a locator."""

    values: list[Any] = [locator.get("page")]
    extra = locator.get("pages", [])
    if isinstance(extra, list):
        values.extend(extra)
    pages: list[int] = []
    for value in values:
        if isinstance(value, int) and not isinstance(value, bool) and value not in pages:
            pages.append(value)
    return pages


def validate_locator(
    record: dict[str, Any],
    label: str,
    page_limit: int | None,
    errors: list[str],
) -> set[int]:
    pages = locator_pages(record.get("source_locator", {}))
    if not pages:
        errors.append(f"{label} has no valid source_locator page.")
        return set()
    for page in pages:
        if page < 1:
            errors.append(f"{label} references invalid source page {page}.")
        elif page_limit and page > page_limit:
            errors.append(f"{label} references page {page} beyond source page count {page_limit}.")
    return set(pages)


def validate_provenance(
    record: dict[str, Any],
    label: str,
    project_input_ids: set[str],
    manifest_input_ids: set[str] | None,
    errors: list[str],
) -> None:
    source_asset_id = record.get("provenance", {}).get("source_asset_id")
    if not isinstance(source_asset_id, str) or not source_asset_id:
        return  # The schema error already identifies a missing/malformed value.
    if source_asset_id not in project_input_ids:
        errors.append(
            f"{label} provenance.source_asset_id={source_asset_id!r} does not reference project.inputs."
        )
    if manifest_input_ids is not None and source_asset_id not in manifest_input_ids:
        errors.append(
            f"{label} provenance.source_asset_id={source_asset_id!r} does not reference source_manifest.inputs."
        )


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def ensure_safe_report_path(project_path: Path, report_path: Path) -> None:
    """Keep a validation report outside immutable inputs and structured-source trees."""

    project_path = project_path.resolve()
    report_path = report_path.resolve()
    require_suffix(report_path, ".json", "--report")
    project = load_json(project_path)
    project_root = project_path.parent
    protected_exact: dict[str, Path] = {"--project": project_path}
    protected_trees: dict[str, Path] = {}

    for item in project.get("inputs", []):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        protected_exact[f"project input {item.get('id', '<unknown>')}"] = resolve_relative(
            project_root, item["path"], must_exist=False
        )
    for key, value in project.get("paths", {}).items():
        if not isinstance(value, str):
            continue
        path = resolve_relative(project_root, value, must_exist=False)
        protected_exact[f"paths.{key}"] = path
        if path.is_dir() or key.endswith("_dir"):
            protected_trees[f"paths.{key}"] = path
        elif key == "content" and path.parent != project_root:
            protected_trees["structured content tree"] = path.parent

    for label, protected_path in protected_exact.items():
        ensure_distinct_paths({"--report": report_path, label: protected_path})
    for label, directory in protected_trees.items():
        if _is_within(report_path, directory):
            raise ValueError(f"--report must not be written inside {label}: {directory.resolve()}")


def validate_source_manifest(
    project: dict[str, Any],
    project_base: Path,
    manifest_path: Path | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    """Validate a locked manifest and bind each declared project input to it."""
    publication_declared = (
        project.get("requested_mode") == "publication_grade_docx"
        or project.get("selected_mode") == "publication_grade_docx"
    )
    if manifest_path is None:
        message = "Project has no paths.source_manifest; declared inputs are not bound to a locked source baseline."
        (errors if publication_declared else warnings).append(message)
        return {
            "present": False,
            "locked": False,
            "input_count": 0,
            "input_ids": [],
            "authoritative_input_id": None,
        }

    try:
        manifest = load_json(manifest_path)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        errors.append(str(exc))
        return {
            "present": True,
            "locked": False,
            "input_count": 0,
            "input_ids": [],
            "authoritative_input_id": None,
        }
    errors.extend(schema_errors(manifest, "source_manifest.schema.json", str(manifest_path)))

    try:
        root_value = Path(str(manifest.get("project_root", ".")))
        if root_value.is_absolute():
            warnings.append("source_manifest.project_root is absolute; prefer a portable path relative to the manifest.")
            manifest_root = root_value.resolve()
        else:
            manifest_root = (manifest_path.parent / root_value).resolve()
        if not manifest_root.is_dir():
            errors.append(f"source_manifest.project_root is not an existing directory: {manifest_root}")
    except (OSError, ValueError) as exc:
        errors.append(f"source_manifest.project_root: {exc}")
        manifest_root = project_base.resolve()
    if manifest_root != project_base.resolve():
        errors.append(
            f"source_manifest.project_root resolves to {manifest_root}, but project.json is rooted at {project_base.resolve()}."
        )

    if publication_declared and manifest.get("locked") is not True:
        errors.append("Publication-grade mode requires source_manifest.locked=true.")
    elif manifest.get("locked") is not True:
        warnings.append("Source manifest is not locked; hashes do not define an accepted baseline.")

    manifest_inputs = manifest.get("inputs", []) if isinstance(manifest, dict) else []
    manifest_ids = [item.get("id") for item in manifest_inputs if isinstance(item, dict)]
    duplicate_ids = sorted(identifier for identifier, count in Counter(manifest_ids).items() if identifier and count > 1)
    if duplicate_ids:
        errors.append("Duplicate source manifest input IDs: " + ", ".join(duplicate_ids))
    manifest_by_id = {
        item.get("id"): item for item in manifest_inputs
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }

    authoritative = [item for item in manifest_inputs if isinstance(item, dict) and item.get("authoritative") is True]
    if len(authoritative) != 1:
        errors.append(f"Source manifest must identify exactly one authoritative input; found {len(authoritative)}.")
        authoritative_id = None
    else:
        authoritative_id = authoritative[0].get("id")
        if authoritative[0].get("role") != "source_document":
            errors.append("The authoritative manifest input must have role=source_document.")
        if authoritative[0].get("read_only") is not True:
            errors.append("The authoritative source document must be declared read-only.")
    for item in manifest_inputs:
        if isinstance(item, dict) and item.get("role") != "source_document" and item.get("authoritative") is True:
            errors.append(f"Non-source manifest input cannot be authoritative: {item.get('id')}.")

    for item in manifest_inputs:
        if not isinstance(item, dict):
            continue
        identifier = item.get("id", "<unknown>")
        try:
            actual_path = resolve_relative(manifest_root, item["path"])
        except (KeyError, ValueError, FileNotFoundError) as exc:
            errors.append(f"source_manifest input {identifier}: {exc}")
            continue
        expected_hash = item.get("sha256")
        if expected_hash and sha256_file(actual_path) != expected_hash:
            errors.append(f"Source manifest hash drift: {identifier} ({item.get('path')}).")
        if isinstance(item.get("size_bytes"), int) and actual_path.stat().st_size != item["size_bytes"]:
            errors.append(f"Source manifest size drift: {identifier} ({item.get('path')}).")

    project_inputs = project.get("inputs", []) if isinstance(project, dict) else []
    project_ids = [item.get("id") for item in project_inputs if isinstance(item, dict)]
    duplicate_project_ids = sorted(identifier for identifier, count in Counter(project_ids).items() if identifier and count > 1)
    if duplicate_project_ids:
        errors.append("Duplicate project input IDs: " + ", ".join(duplicate_project_ids))
    project_by_id = {
        item.get("id"): item for item in project_inputs
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    missing_from_manifest = sorted(set(project_by_id) - set(manifest_by_id))
    extra_in_manifest = sorted(set(manifest_by_id) - set(project_by_id))
    if missing_from_manifest:
        errors.append("Project inputs missing from source manifest: " + ", ".join(missing_from_manifest))
    if extra_in_manifest:
        warnings.append(
            "Source manifest inventory entries are outside project.inputs and are not part of the declared deliverable binding: "
            + ", ".join(extra_in_manifest)
        )

    compared_fields = ("role", "media_type", "language", "authority_rank", "required", "read_only", "approved")
    for identifier in sorted(set(project_by_id) & set(manifest_by_id)):
        project_input = project_by_id[identifier]
        manifest_input = manifest_by_id[identifier]
        try:
            project_actual = resolve_relative(project_base, project_input["path"])
            manifest_actual = resolve_relative(manifest_root, manifest_input["path"])
            if project_actual != manifest_actual:
                errors.append(f"Input path binding mismatch for {identifier}: project and manifest resolve to different files.")
        except (KeyError, ValueError, FileNotFoundError) as exc:
            errors.append(f"Input binding {identifier}: {exc}")
        for field in compared_fields:
            if field in project_input and project_input.get(field) != manifest_input.get(field):
                errors.append(
                    f"Input binding mismatch for {identifier}.{field}: "
                    f"project={project_input.get(field)!r}, manifest={manifest_input.get(field)!r}."
                )
        direct_hash = project_input.get("sha256")
        manifest_hash = manifest_input.get("sha256")
        if direct_hash and direct_hash != manifest_hash:
            errors.append(f"Input hash binding mismatch for {identifier}: project and manifest hashes differ.")
        if publication_declared and not (direct_hash or manifest_hash):
            errors.append(f"Publication-grade input is not hash-bound: {identifier}.")

    project_sources = [item for item in project_inputs if isinstance(item, dict) and item.get("role") == "source_document"]
    if len(project_sources) == 1 and authoritative_id != project_sources[0].get("id"):
        errors.append(
            f"Authoritative manifest input {authoritative_id!r} does not match project source_document "
            f"{project_sources[0].get('id')!r}."
        )

    for field in ("requested_mode", "selected_mode", "allow_downgrade"):
        if field in project and manifest.get(field) != project.get(field):
            errors.append(
                f"Source manifest {field}={manifest.get(field)!r} conflicts with project {field}={project.get(field)!r}."
            )
    project_capabilities = project.get("capabilities", {})
    manifest_capabilities = manifest.get("capabilities", {})
    for field in ("microsoft_word", "authoritative_renderer", "renderer_available"):
        manifest_value = manifest_capabilities.get(field)
        project_value = project_capabilities.get(field)
        if field == "renderer_available" and manifest_value is None and project_value is False:
            continue
        if manifest_value != project_value:
            errors.append(
                f"Source manifest capability {field}={manifest_value!r} conflicts with "
                f"project value {project_value!r}."
            )

    return {
        "present": True,
        "locked": manifest.get("locked") is True,
        "input_count": len(manifest_inputs),
        "input_ids": sorted(identifier for identifier in manifest_by_id if identifier),
        "authoritative_input_id": authoritative_id,
        "blocking_issues": list(manifest.get("blocking_issues", [])),
        "capabilities": manifest_capabilities,
        "sha256": sha256_file(manifest_path),
    }


def validate_project(project_path: Path) -> dict[str, Any]:
    project_path = project_path.resolve()
    base = project_path.parent
    project = load_json(project_path)
    errors = schema_errors(project, "project.schema.json", str(project_path))
    warnings: list[str] = []

    inputs = project.get("inputs", []) if isinstance(project, dict) else []
    project_input_ids = {
        item.get("id") for item in inputs
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    }
    source_inputs = [item for item in inputs if item.get("role") == "source_document"]
    if len(source_inputs) != 1:
        errors.append(f"Exactly one authoritative source_document is required; found {len(source_inputs)}.")
    page_limit = source_inputs[0].get("page_count") if len(source_inputs) == 1 else None
    for item in inputs:
        try:
            path = resolve_relative(base, item["path"])
        except (KeyError, ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
            continue
        expected = item.get("sha256")
        if expected and sha256_file(path) != expected:
            errors.append(f"Input hash drift: {item.get('id')} ({item['path']}).")
        if item.get("read_only") is not True:
            warnings.append(f"Input is not declared read-only: {item.get('id')}.")

    paths = project.get("paths", {})
    resolved: dict[str, Path] = {}
    for key, value in paths.items():
        try:
            resolved[key] = resolve_relative(base, value)
        except (ValueError, FileNotFoundError) as exc:
            errors.append(f"paths.{key}: {exc}")

    manifest_summary = validate_source_manifest(project, base, resolved.get("source_manifest"), errors, warnings)
    manifest_input_ids = (
        set(manifest_summary.get("input_ids", [])) if manifest_summary.get("present") else None
    )

    blocks: list[dict[str, Any]] = []
    if "content" in resolved:
        try:
            blocks = load_jsonl(resolved["content"])
            for index, block in enumerate(blocks, 1):
                errors.extend(schema_errors(block, "content_block.schema.json", f"content[{index}]"))
                validate_provenance(
                    block,
                    f"Content block {block.get('id', index)}",
                    project_input_ids,
                    manifest_input_ids,
                    errors,
                )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))

    block_ids = [item.get("id") for item in blocks]
    duplicates = [value for value, count in Counter(block_ids).items() if value and count > 1]
    if duplicates:
        errors.append("Duplicate content block IDs: " + ", ".join(sorted(duplicates)))
    block_by_id = {item.get("id"): item for item in blocks if item.get("id")}

    orders: dict[int, list[int]] = defaultdict(list)
    block_pages_by_id: dict[str, set[int]] = {}
    for block in blocks:
        locator = block.get("source_locator", {})
        page = locator.get("page")
        order = locator.get("order")
        identifier = block.get("id")
        pages = validate_locator(block, f"Block {identifier}", page_limit, errors)
        if isinstance(identifier, str):
            block_pages_by_id[identifier] = pages
        if isinstance(page, int) and isinstance(order, int):
            orders[page].append(order)
    for page, values in orders.items():
        expected = list(range(1, len(values) + 1))
        if sorted(values) != expected:
            errors.append(f"Source page {page} order values must be consecutive from 1; found {sorted(values)}.")

    declared_sequence = []
    for block in blocks:
        locator = block.get("source_locator", {})
        pages = locator_pages(locator)
        declared_sequence.append((min(pages) if pages else 0, int(locator.get("order", 0))))
    if declared_sequence != sorted(declared_sequence):
        errors.append("Content block sequence differs from source_locator page/order sequence.")

    nontext = {"page_break", "section_break", "toc", "table", "figure", "formula"}
    for block in blocks:
        if block.get("block_type") not in nontext and not str(block.get("target_text", "")).strip() and not block.get("merge_into"):
            errors.append(f"Block {block.get('id')} has empty target_text.")
        target = block.get("merge_into")
        if target and target not in block_by_id:
            errors.append(f"Block {block.get('id')} merges into unknown block {target}.")
        if target and target in block_by_id:
            if block.get("merge_strategy") != "target_contains_source":
                errors.append(f"Block {block.get('id')} must declare merge_strategy=target_contains_source.")
            merged_text = str(block.get("target_text", "")).strip()
            target_text = str(block_by_id[target].get("target_text", ""))
            if not merged_text or merged_text not in target_text:
                errors.append(f"Merged block {block.get('id')} target_text is not demonstrably contained in target block {target}; refusing silent content loss.")

    tables: dict[str, dict[str, Any]] = {}
    table_pages_by_id: dict[str, set[int]] = {}
    if "tables_dir" in resolved and resolved["tables_dir"].is_dir():
        for table_path in sorted(resolved["tables_dir"].glob("*.json")):
            try:
                table = load_json(table_path)
                errors.extend(schema_errors(table, "table.schema.json", str(table_path)))
                identifier = table.get("id")
                table_pages = validate_locator(table, f"Table {identifier}", page_limit, errors)
                validate_provenance(
                    table,
                    f"Table {identifier}",
                    project_input_ids,
                    manifest_input_ids,
                    errors,
                )
                if identifier in tables:
                    errors.append(f"Duplicate table ID: {identifier}")
                if identifier:
                    tables[identifier] = table
                    table_pages_by_id[identifier] = table_pages
                columns = table.get("columns", [])
                table_rows = table.get("rows", [])
                if table.get("header_row_count", 0) > 1 + len(table_rows):
                    errors.append(f"Table {identifier} header_row_count exceeds its Word row count.")
                covered: set[tuple[int, int]] = set()
                for row_index, row in enumerate(table_rows):
                    if len(row.get("cells", [])) != len(columns):
                        errors.append(f"Table {identifier} row {row.get('id')} has {len(row.get('cells', []))} cells for {len(columns)} columns.")
                    for column_index, cell in enumerate(row.get("cells", [])):
                        rowspan = int(cell.get("rowspan", 1))
                        colspan = int(cell.get("colspan", 1))
                        if row_index + rowspan > len(table_rows) or column_index + colspan > len(columns):
                            errors.append(f"Table {identifier} row {row.get('id')} cell {column_index + 1} has an out-of-range merge.")
                            continue
                        if (rowspan > 1 or colspan > 1) and (row_index, column_index) in covered:
                            errors.append(f"Table {identifier} has overlapping merge origins at row {row_index + 1}, column {column_index + 1}.")
                        if rowspan > 1 or colspan > 1:
                            for merge_row in range(row_index, row_index + rowspan):
                                for merge_column in range(column_index, column_index + colspan):
                                    coordinate = (merge_row, merge_column)
                                    if coordinate != (row_index, column_index):
                                        if coordinate in covered:
                                            errors.append(f"Table {identifier} has overlapping merges at row {merge_row + 1}, column {merge_column + 1}.")
                                        covered.add(coordinate)
                for row_index, row in enumerate(table_rows):
                    for column_index, cell in enumerate(row.get("cells", [])):
                        coordinate = (row_index, column_index)
                        source_text = str(cell.get("source_text", "")).strip()
                        target_text = str(cell.get("target_text", "")).strip()
                        if coordinate in covered:
                            if source_text or target_text:
                                errors.append(
                                    f"Table {identifier} merged-away cell at row {row_index + 1}, "
                                    f"column {column_index + 1} must have empty source_text and target_text."
                                )
                        elif cell.get("kind") != "formula" and source_text and not target_text:
                            errors.append(
                                f"Table {identifier} cell at row {row_index + 1}, column {column_index + 1} "
                                "has source_text but empty target_text."
                            )
                        if cell.get("kind") == "formula" and not cell.get("formula_id"):
                            errors.append(
                                f"Table {identifier} formula cell at row {row_index + 1}, "
                                f"column {column_index + 1} has no formula_id."
                            )
            except (ValueError, FileNotFoundError, RuntimeError) as exc:
                errors.append(str(exc))
    elif "tables_dir" in resolved:
        errors.append(f"tables_dir is not a directory: {resolved['tables_dir']}")

    formulas: dict[str, dict[str, Any]] = {}
    formula_pages_by_id: dict[str, set[int]] = {}
    if "formulas" in resolved:
        try:
            for index, formula in enumerate(load_objects(resolved["formulas"]), 1):
                errors.extend(schema_errors(formula, "formula.schema.json", f"formula[{index}]"))
                identifier = formula.get("id")
                formula_pages = validate_locator(formula, f"Formula {identifier}", page_limit, errors)
                validate_provenance(
                    formula,
                    f"Formula {identifier}",
                    project_input_ids,
                    manifest_input_ids,
                    errors,
                )
                if identifier in formulas:
                    errors.append(f"Duplicate formula ID: {identifier}")
                if identifier:
                    formulas[identifier] = formula
                    formula_pages_by_id[identifier] = formula_pages
                for anchor in formula.get("anchor_block_ids", []):
                    if anchor not in block_by_id:
                        errors.append(f"Formula {identifier} has unknown anchor block {anchor}.")
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))
    for table_id, table in tables.items():
        for row in table.get("rows", []):
            for cell in row.get("cells", []):
                if cell.get("kind") == "formula" and cell.get("formula_id") not in formulas:
                    errors.append(f"Table {table_id} references unknown formula {cell.get('formula_id')}.")

    footnotes: dict[str, dict[str, Any]] = {}
    footnote_pages_by_id: dict[str, set[int]] = {}
    if "footnotes" in resolved:
        try:
            for index, footnote in enumerate(load_objects(resolved["footnotes"]), 1):
                errors.extend(schema_errors(footnote, "footnote.schema.json", f"footnote[{index}]"))
                identifier = footnote.get("id")
                footnote_pages = validate_locator(footnote, f"Footnote {identifier}", page_limit, errors)
                validate_provenance(
                    footnote,
                    f"Footnote {identifier}",
                    project_input_ids,
                    manifest_input_ids,
                    errors,
                )
                if identifier in footnotes:
                    errors.append(f"Duplicate footnote ID: {identifier}")
                if identifier:
                    footnotes[identifier] = footnote
                    footnote_pages_by_id[identifier] = footnote_pages
                if footnote.get("anchor_block_id") not in block_by_id:
                    errors.append(f"Footnote {identifier} has unknown anchor block {footnote.get('anchor_block_id')}.")
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))
    footnote_scopes = {item.get("numbering_scope") for item in footnotes.values()}
    if len(footnote_scopes) > 1:
        errors.append("A Word document can use only one footnote numbering_scope in this builder; split the project or normalize the source rule.")
    if footnotes and footnote_scopes == {"document"}:
        ordered_numbers = [item["number"] for item in sorted(footnotes.values(), key=lambda note: (block_by_id.get(note.get("anchor_block_id"), {}).get("source_locator", {}).get("page", 0), block_by_id.get(note.get("anchor_block_id"), {}).get("source_locator", {}).get("order", 0)))]
        if ordered_numbers != list(range(ordered_numbers[0], ordered_numbers[0] + len(ordered_numbers))):
            errors.append(f"Document-scope footnote numbers must be consecutive in anchor order; found {ordered_numbers}.")

    figures: dict[str, dict[str, Any]] = {}
    figure_pages_by_id: dict[str, set[int]] = {}
    if "figures" in resolved:
        try:
            for index, figure in enumerate(load_objects(resolved["figures"]), 1):
                errors.extend(schema_errors(figure, "figure_asset.schema.json", f"figure[{index}]"))
                identifier = figure.get("id")
                figure_pages = validate_locator(figure, f"Figure {identifier}", page_limit, errors)
                validate_provenance(
                    figure,
                    f"Figure {identifier}",
                    project_input_ids,
                    manifest_input_ids,
                    errors,
                )
                if identifier in figures:
                    errors.append(f"Duplicate figure ID: {identifier}")
                if identifier:
                    figures[identifier] = figure
                    figure_pages_by_id[identifier] = figure_pages
                if figure.get("path"):
                    try:
                        asset = resolve_relative(resolved["figures"].parent, figure["path"])
                        if figure.get("sha256") and sha256_file(asset) != figure["sha256"]:
                            errors.append(f"Figure hash drift: {identifier}.")
                    except (ValueError, FileNotFoundError) as exc:
                        errors.append(f"Figure {identifier}: {exc}")
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))

    toc_entries: list[dict[str, Any]] = []
    toc_data: dict[str, Any] = {}
    if "toc" in resolved:
        try:
            toc_data = load_json(resolved["toc"])
            errors.extend(schema_errors(toc_data, "toc_map.schema.json", str(resolved["toc"])))
            toc_entries = toc_data.get("entries", [])
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))

    for block in blocks:
        identifier = block.get("id")
        kind = block.get("block_type")
        for field, expected_kind in (
            ("table_id", "table"),
            ("figure_id", "figure"),
            ("formula_id", "formula"),
            ("footnote_id", "footnote_anchor"),
        ):
            if field in block and kind != expected_kind:
                errors.append(
                    f"Block {identifier} declares {field} but has block_type={kind!r}; "
                    f"expected {expected_kind!r}."
                )
        if kind == "table" and block.get("table_id") not in tables:
            errors.append(f"Block {identifier} references unknown table {block.get('table_id')}.")
        if kind == "formula" and block.get("formula_id") not in formulas:
            errors.append(f"Block {identifier} references unknown formula {block.get('formula_id')}.")
        if kind == "footnote_anchor" and block.get("footnote_id") not in footnotes:
            errors.append(f"Block {identifier} references unknown footnote {block.get('footnote_id')}.")
        if kind == "figure" and block.get("figure_id") not in figures:
            errors.append(f"Block {identifier} references unknown figure {block.get('figure_id')}.")

    table_block_refs: dict[str, set[str]] = defaultdict(set)
    figure_block_refs: dict[str, set[str]] = defaultdict(set)
    formula_block_refs: dict[str, set[str]] = defaultdict(set)
    footnote_block_refs: dict[str, set[str]] = defaultdict(set)
    for block in blocks:
        identifier = block.get("id")
        if not isinstance(identifier, str):
            continue
        if isinstance(block.get("table_id"), str):
            table_block_refs[block["table_id"]].add(identifier)
        if isinstance(block.get("figure_id"), str):
            figure_block_refs[block["figure_id"]].add(identifier)
        if isinstance(block.get("formula_id"), str):
            formula_block_refs[block["formula_id"]].add(identifier)
        if isinstance(block.get("footnote_id"), str):
            footnote_block_refs[block["footnote_id"]].add(identifier)

    for table_id, table in tables.items():
        table_anchors = table_block_refs.get(table_id, set())
        if not table_anchors:
            errors.append(f"Table {table_id} is not referenced by any content block.")
        anchor_pages = set().union(*(block_pages_by_id.get(anchor, set()) for anchor in table_anchors))
        if anchor_pages and table_pages_by_id.get(table_id, set()) != anchor_pages:
            errors.append(
                f"Table {table_id} source_locator pages {sorted(table_pages_by_id.get(table_id, set()))} "
                f"do not match its referencing blocks {sorted(anchor_pages)}."
            )
        contains_formula_ids = {
            cell.get("formula_id")
            for row in table.get("rows", [])
            for cell in row.get("cells", [])
            if cell.get("kind") == "formula" and isinstance(cell.get("formula_id"), str)
        }
        for formula_id in contains_formula_ids:
            formula_block_refs[formula_id].update(table_anchors)

    for figure_id in figures:
        figure_anchors = figure_block_refs.get(figure_id, set())
        if not figure_anchors:
            errors.append(f"Figure {figure_id} is not referenced by any content block.")
        anchor_pages = set().union(*(block_pages_by_id.get(anchor, set()) for anchor in figure_anchors))
        if anchor_pages and figure_pages_by_id.get(figure_id, set()) != anchor_pages:
            errors.append(
                f"Figure {figure_id} source_locator pages {sorted(figure_pages_by_id.get(figure_id, set()))} "
                f"do not match its referencing blocks {sorted(anchor_pages)}."
            )

    for formula_id, formula in formulas.items():
        declared_anchors = set(formula.get("anchor_block_ids", []))
        actual_anchors = formula_block_refs.get(formula_id, set())
        if declared_anchors != actual_anchors:
            errors.append(
                f"Formula {formula_id} anchor_block_ids {sorted(declared_anchors)} do not match "
                f"actual referencing blocks {sorted(actual_anchors)}."
            )
        formula_pages = formula_pages_by_id.get(formula_id, set())
        for anchor in actual_anchors:
            anchor_pages = block_pages_by_id.get(anchor, set())
            if formula_pages and anchor_pages and not (formula_pages & anchor_pages):
                errors.append(
                    f"Formula {formula_id} source_locator pages {sorted(formula_pages)} do not overlap "
                    f"anchor block {anchor} pages {sorted(anchor_pages)}."
                )

    for footnote_id, footnote in footnotes.items():
        declared_anchor = footnote.get("anchor_block_id")
        actual_anchors = footnote_block_refs.get(footnote_id, set())
        if actual_anchors != ({declared_anchor} if isinstance(declared_anchor, str) else set()):
            errors.append(
                f"Footnote {footnote_id} anchor_block_id={declared_anchor!r} does not match "
                f"actual footnote anchor blocks {sorted(actual_anchors)}."
            )
        anchor_block = block_by_id.get(declared_anchor)
        if anchor_block and (
            anchor_block.get("block_type") != "footnote_anchor"
            or anchor_block.get("footnote_id") != footnote_id
        ):
            errors.append(
                f"Footnote {footnote_id} anchor {declared_anchor} is not a matching footnote_anchor block."
            )
        footnote_pages = footnote_pages_by_id.get(footnote_id, set())
        anchor_pages = block_pages_by_id.get(declared_anchor, set())
        if footnote_pages and anchor_pages and not footnote_pages.issubset(anchor_pages):
            errors.append(
                f"Footnote {footnote_id} source_locator pages {sorted(footnote_pages)} are outside "
                f"anchor block {declared_anchor} pages {sorted(anchor_pages)}."
            )

    heading_ids = {item.get("id") for item in blocks if item.get("block_type") == "heading"}
    active_heading_id: str | None = None
    for block in blocks:
        if block.get("block_type") == "heading" and isinstance(block.get("id"), str):
            active_heading_id = block["id"]
            continue
        if block.get("block_type") not in {"requirement", "regulatory_quote"}:
            continue
        identifier = block.get("id")
        owner = block.get("owner_ref", {}).get("id")
        source_owner = block.get("source_owner_ref", {}).get("id")
        if owner != source_owner:
            errors.append(
                f"Requirement block {identifier} owner {owner!r} differs from source owner {source_owner!r}."
            )
        owner_block = block_by_id.get(owner)
        if not owner_block or owner_block.get("block_type") != "heading":
            errors.append(f"Requirement block {identifier} references missing or non-heading owner {owner!r}.")
        else:
            if block.get("section_path", []) != owner_block.get("section_path", []):
                errors.append(
                    f"Requirement block {identifier} section_path differs from owner heading {owner}."
                )
        if owner != active_heading_id:
            errors.append(
                f"Requirement block {identifier} is ordered under active heading {active_heading_id!r}, "
                f"not declared owner {owner!r}."
            )
    if "toc" in resolved:
        toc_ids = [item.get("block_id") for item in toc_entries]
        if len(toc_ids) != len(set(toc_ids)):
            errors.append("TOC map contains duplicate block IDs.")
        if set(toc_ids) != heading_ids:
            missing = sorted(heading_ids - set(toc_ids))
            extra = sorted(set(toc_ids) - heading_ids)
            if missing:
                errors.append("Headings missing from TOC include/exclude map: " + ", ".join(missing))
            if extra:
                errors.append("TOC entries reference non-heading or missing blocks: " + ", ".join(extra))

    requested = project.get("requested_mode")
    selected = project.get("selected_mode")
    has_layout = "layout" in resolved
    layout_data: dict[str, Any] | None = None
    layout_section_ids: set[str] = set()
    if has_layout:
        try:
            raw_layout = load_json(resolved["layout"])
            errors.extend(schema_errors(raw_layout, "layout_spec.schema.json", str(resolved["layout"])))
            profile_id = str(raw_layout.get("profile_id") or "source_faithful")
            profile = load_layout_profile(profile_id)
            errors.extend(schema_errors(profile, "layout_profile.schema.json", f"layout profile {profile_id}"))
            layout = resolve_layout_profile(raw_layout)
            layout_data = layout
            styles = set(layout.get("styles", {}))
            for style_name, style_spec in layout.get("styles", {}).items():
                missing_font_fields = [
                    key for key in ("font_latin", "font_cjk", "size_pt")
                    if not style_spec.get(key)
                ]
                if missing_font_fields:
                    errors.append(
                        f"Resolved style {style_name} is missing {missing_font_fields}; "
                        "source_faithful must declare them and zh_formal_print may supply them by semantic role."
                    )
            if layout.get("math_font") != "Cambria Math":
                errors.append("Resolved layout math_font must be Cambria Math.")
            if profile_id == "zh_formal_print":
                required_roles = {
                    "body", "list", "requirement", "bibliography", "heading_major",
                    "heading_minor", "figure_caption", "table_caption",
                }
                missing_roles = sorted(required_roles - set(layout.get("style_roles", {})))
                if missing_roles:
                    errors.append(f"zh_formal_print is missing semantic style roles: {missing_roles}")
                role_styles = layout.get("style_roles", {})
                toc_target_by_block = {
                    entry.get("block_id"): entry.get("target_style")
                    for entry in toc_entries
                }
                toc_include_by_block = {
                    entry.get("block_id"): bool(entry.get("include"))
                    for entry in toc_entries
                }
                semantic_role_by_kind = {
                    "paragraph": "body",
                    "footnote_anchor": "body",
                    "list_item": "list",
                    "requirement": "requirement",
                    "regulatory_quote": "requirement",
                    "bibliography": "bibliography",
                }
                for block in blocks:
                    kind = block.get("block_type")
                    if kind == "heading":
                        role = "heading_major" if int(block.get("heading_level", 1)) == 1 else "heading_minor"
                        actual_style = toc_target_by_block.get(block.get("id")) or block.get("style_ref")
                    else:
                        role = semantic_role_by_kind.get(str(kind))
                        actual_style = block.get("style_ref") if role else None
                        if role and not actual_style:
                            actual_style = role_styles.get(role)
                    expected_style = role_styles.get(role) if role else None
                    if role and actual_style != expected_style:
                        no_toc_equivalent = False
                        if kind == "heading" and not toc_include_by_block.get(block.get("id"), True):
                            actual_spec = layout.get("styles", {}).get(actual_style, {})
                            expected_spec = layout.get("styles", {}).get(expected_style, {})
                            no_toc_equivalent = all(
                                actual_spec.get(field) == expected_spec.get(field)
                                for field in ("font_latin", "font_cjk", "size_pt")
                            )
                        if not no_toc_equivalent:
                            errors.append(
                                f"zh_formal_print block {block.get('id')} uses style {actual_style!r}; "
                                f"semantic role {role} requires {expected_style!r} or a typography-equivalent NoTOC style."
                            )
            section_ids = [section.get("id") for section in layout.get("sections", []) if isinstance(section, dict)]
            duplicate_section_ids = sorted(
                identifier for identifier, count in Counter(section_ids).items()
                if identifier and count > 1
            )
            if duplicate_section_ids:
                errors.append("Duplicate layout section IDs: " + ", ".join(duplicate_section_ids))
            layout_section_ids = {identifier for identifier in section_ids if isinstance(identifier, str)}
            brand_ids = [
                item.get("id") for item in layout.get("brand_assets", [])
                if isinstance(item, dict)
            ]
            duplicate_brand_ids = sorted(
                identifier for identifier, count in Counter(brand_ids).items()
                if identifier and count > 1
            )
            if duplicate_brand_ids:
                errors.append("Duplicate layout brand asset IDs: " + ", ".join(duplicate_brand_ids))
            for block in blocks:
                if block.get("style_ref") and block["style_ref"] not in styles:
                    errors.append(f"Block {block.get('id')} references unknown style {block['style_ref']}.")
            included_toc_styles = {
                entry.get("target_style") for entry in toc_entries if entry.get("include")
            }
            for entry in toc_entries:
                if entry.get("include"):
                    target_style = entry.get("target_style")
                    if target_style not in styles:
                        errors.append(f"Included TOC entry {entry.get('block_id')} references unknown target style {target_style}.")
                    else:
                        expected_outline = int(entry.get("level", 1)) - 1
                        actual_outline = layout["styles"][target_style].get("outline_level")
                        if actual_outline != expected_outline:
                            errors.append(f"TOC entry {entry.get('block_id')} level {entry.get('level')} conflicts with style {target_style} outline_level {actual_outline}.")
                else:
                    target_style = entry.get("target_style")
                    if target_style not in styles:
                        errors.append(f"Excluded TOC entry {entry.get('block_id')} references unknown NoTOC target style {target_style}.")
                    if target_style in included_toc_styles:
                        errors.append(
                            f"Excluded TOC entry {entry.get('block_id')} shares target style {target_style} "
                            "with an included entry; use a distinct NoTOC style."
                        )
                    if target_style in styles and layout["styles"][target_style].get("outline_level") is not None:
                        errors.append(
                            f"Excluded TOC entry {entry.get('block_id')} uses style {target_style} "
                            "whose outline_level must be null."
                        )
            visual_policy = layout.get("toc", {}).get("visual_spacing_policy", {})
            if visual_policy.get("required"):
                spacing_basis = toc_data.get("visual_spacing_basis", {})
                if spacing_basis.get("review_required") is not True:
                    errors.append(
                        "TOC visual spacing policy requires toc_map.visual_spacing_basis.review_required=true."
                    )
                included_without_spacing = [
                    entry.get("block_id")
                    for entry in toc_entries
                    if entry.get("include") and not entry.get("source_spacing")
                ]
                if included_without_spacing:
                    errors.append(
                        "TOC visual spacing policy requires source_spacing for every included entry: "
                        + ", ".join(str(item) for item in included_without_spacing)
                    )
            caption_roles = layout.get("style_roles", {})
            figure_caption_style = caption_roles.get("figure_caption")
            table_caption_style = caption_roles.get("table_caption")
            built_in_caption_styles = {"Caption"} if profile_id == "source_faithful" else set()
            if any(
                not figure.get("caption_embedded") and bool(figure.get("target_caption"))
                for figure in figures.values()
            ) and figure_caption_style not in styles | built_in_caption_styles:
                errors.append(
                    f"Generated figure captions require a declared figure_caption style; got {figure_caption_style!r}."
                )
            if any(bool(table.get("caption", {}).get("target")) for table in tables.values()) and table_caption_style not in styles | built_in_caption_styles:
                errors.append(
                    f"Generated table captions require a declared table_caption style; got {table_caption_style!r}."
                )
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            errors.append(str(exc))

    for block in blocks:
        if block.get("block_type") != "section_break":
            continue
        section_id = block.get("section_id")
        if not has_layout:
            errors.append(
                f"Section-break block {block.get('id')} requires paths.layout and a matching section definition."
            )
        elif section_id not in layout_section_ids:
            errors.append(
                f"Section-break block {block.get('id')} references unknown layout section {section_id}."
            )

    publication_ready = has_layout and bool(project.get("capabilities", {}).get("microsoft_word")) and bool(project.get("capabilities", {}).get("renderer_available"))
    derived_mode = "publication_grade_docx" if publication_ready else "translation_only"
    if requested == "publication_grade_docx":
        derived_mode = "publication_grade_docx"
        if not has_layout:
            errors.append("Publication-grade mode requires paths.layout.")
        if "toc" not in resolved:
            errors.append("Publication-grade mode requires an explicit paths.toc whitelist.")
        if any(block.get("block_type") == "table" for block in blocks) and "tables_dir" not in resolved:
            errors.append("Publication-grade table blocks require paths.tables_dir.")
        has_formula_use = any(block.get("block_type") == "formula" for block in blocks) or any(cell.get("kind") == "formula" for table in tables.values() for row in table.get("rows", []) for cell in row.get("cells", []))
        if has_formula_use and "formulas" not in resolved:
            errors.append("Publication-grade formula use requires paths.formulas.")
        if any(block.get("block_type") == "footnote_anchor" for block in blocks) and "footnotes" not in resolved:
            errors.append("Publication-grade footnote anchors require paths.footnotes.")
        if any(block.get("block_type") == "figure" for block in blocks) and "figures" not in resolved:
            errors.append("Publication-grade figure blocks require paths.figures.")
        if not project.get("capabilities", {}).get("microsoft_word"):
            errors.append("Publication-grade Word acceptance requires Microsoft Word Desktop.")
        if not project.get("capabilities", {}).get("renderer_available"):
            errors.append("Publication-grade mode requires the declared authoritative renderer.")
    elif requested == "translation_only":
        derived_mode = "translation_only"
    if selected and selected != derived_mode:
        errors.append(f"selected_mode={selected} conflicts with derived mode {derived_mode}.")
    if derived_mode == "publication_grade_docx":
        for blocker in list(project.get("blocking_issues", [])) + list(manifest_summary.get("blocking_issues", [])):
            errors.append(f"Publication blocker: {blocker}")
        if project.get("capabilities", {}).get("authoritative_renderer") != "word-com":
            errors.append("Publication-grade mode requires capabilities.authoritative_renderer=word-com.")
        if layout_data is not None and layout_data.get("render_policy", {}).get("renderer") != "word-com":
            errors.append("Publication-grade layout render_policy.renderer must be word-com.")
        if layout_data is not None and any(block.get("block_type") == "bibliography" for block in blocks):
            bibliography_profile = layout_data.get("object_profiles", {}).get("bibliography")
            if not bibliography_profile:
                errors.append("Publication-grade bibliography blocks require object_profiles.bibliography geometry.")
        if not manifest_summary.get("present"):
            message = "Publication-grade mode requires paths.source_manifest."
            if message not in errors:
                errors.append(message)
        elif not manifest_summary.get("locked"):
            message = "Publication-grade mode requires source_manifest.locked=true."
            if message not in errors:
                errors.append(message)
        for identifier, figure in figures.items():
            if not figure.get("approved"):
                errors.append(f"Publication-grade figure is not approved: {identifier}.")

    counts = {
        "blocks": len(blocks), "headings": len(heading_ids), "tables": len(tables), "figures": len(figures),
        "formulas": len(formulas), "footnotes": len(footnotes), "toc_entries": len(toc_entries),
    }
    return {
        "schema_version": "1.0",
        "project": project_path.name,
        "status": "PASS" if not errors else "FAIL",
        "selected_mode": derived_mode,
        "source_manifest": manifest_summary,
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        ensure_safe_report_path(args.project, args.report)
    except Exception as exc:
        print(f"FAIL: unsafe --report path: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        report = validate_project(args.project)
    except Exception as exc:
        report = {"schema_version": "1.0", "project": str(args.project), "status": "FAIL", "errors": [str(exc)], "warnings": []}
    atomic_write_json(args.report.resolve(), report)
    print(f"{report['status']}: {len(report.get('errors', []))} errors; report -> {args.report.resolve()}")
    if report["status"] != "PASS":
        sys.exit(1)


if __name__ == "__main__":
    main()
