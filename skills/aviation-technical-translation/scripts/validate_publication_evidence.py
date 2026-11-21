"""Validate caption, TOC spacing, special-section, and branding QA evidence."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import atomic_write_json, ensure_distinct_paths, load_json, resolve_layout_profile, resolve_relative, schema_validation_errors


def load_registry(path: Path, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    value = load_json(path)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
    raise ValueError(f"Expected an object registry at {path}")


def schema_errors(value: Any, schema_name: str) -> list[str]:
    return schema_validation_errors(value, Path(__file__).resolve().parent.parent / "schemas" / schema_name)


def validate(project_path: Path, evidence_path: Path) -> dict[str, Any]:
    project = load_json(project_path)
    base = project_path.parent
    layout_path_value = project.get("paths", {}).get("layout")
    if not layout_path_value:
        raise ValueError("Publication evidence requires project.paths.layout.")
    layout_path = (base / layout_path_value).resolve()
    try:
        layout_path.relative_to(base.resolve())
    except ValueError as exc:
        raise ValueError("project.paths.layout escapes the project directory.") from exc
    layout = resolve_layout_profile(load_json(layout_path))
    evidence = load_json(evidence_path)
    errors = schema_errors(evidence, "publication_evidence.schema.json")
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(f"{name}: {detail}")

    check(
        "layout profile binding",
        evidence.get("layout_profile_id") == layout.get("profile_id"),
        {"evidence": evidence.get("layout_profile_id"), "layout": layout.get("profile_id")},
    )
    expected_captions: dict[str, str] = {}
    figures_value = project.get("paths", {}).get("figures")
    if figures_value:
        figures_path = resolve_relative(base, figures_value)
        for figure in load_registry(figures_path, ("figures", "items")):
            if not figure.get("caption_embedded") and figure.get("target_caption"):
                expected_captions[str(figure.get("id"))] = "figure"
    tables_value = project.get("paths", {}).get("tables_dir")
    if tables_value:
        tables_path = resolve_relative(base, tables_value)
        for table_path in sorted(tables_path.glob("*.json")):
            table = load_json(table_path)
            if table.get("caption", {}).get("target"):
                expected_captions[str(table.get("id"))] = "table"

    styles_by_kind: dict[str, set[str]] = defaultdict(set)
    expected_roles = {"figure": "figure_caption", "table": "table_caption"}
    for item in evidence.get("caption_checks", []):
        kind = item.get("kind")
        style_name = item.get("style_name")
        styles_by_kind[str(kind)].add(str(style_name))
        expected = layout.get("style_roles", {}).get(expected_roles.get(str(kind), ""))
        check(
            f"caption {item.get('object_id')}",
            item.get("status") == "PASS" and bool(expected) and style_name == expected,
            {"kind": kind, "actual_style": style_name, "expected_style": expected, "status": item.get("status")},
        )
    caption_ids = [str(item.get("object_id")) for item in evidence.get("caption_checks", [])]
    duplicate_caption_ids = sorted(identifier for identifier in set(caption_ids) if caption_ids.count(identifier) > 1)
    actual_captions = {
        str(item.get("object_id")): str(item.get("kind"))
        for item in evidence.get("caption_checks", [])
    }
    check("caption evidence unique", not duplicate_caption_ids, duplicate_caption_ids)
    check(
        "caption evidence complete",
        actual_captions == expected_captions,
        {"expected": expected_captions, "actual": actual_captions},
    )
    for kind, styles in sorted(styles_by_kind.items()):
        check(f"{kind} caption style consistency", len(styles) == 1, sorted(styles))

    toc = evidence.get("toc_spacing", {})
    required = toc.get("required_checks", {})
    toc_policy = layout.get("toc", {}).get("visual_spacing_policy", {})
    expected_required = {
        "terminal_entry": bool(toc_policy.get("required") and toc_policy.get("compare_terminal_entry")),
        "group_spacing": bool(toc_policy.get("required") and toc_policy.get("compare_group_spacing")),
        "special_entries": bool(toc_policy.get("required") and toc_policy.get("compare_special_entries")),
    }
    check("TOC visual spacing policy active", bool(toc_policy.get("required")), toc_policy)
    check(
        "TOC required checks bound to layout",
        required == expected_required,
        {"layout": expected_required, "evidence": required},
    )
    check("TOC source visual comparison", bool(toc.get("source_compared")), toc)
    for key, status_key in (
        ("terminal_entry", "terminal_entry_status"),
        ("group_spacing", "group_spacing_status"),
        ("special_entries", "special_entry_spacing_status"),
    ):
        expected = "PASS" if expected_required[key] else {"PASS", "NOT_APPLICABLE"}
        actual = toc.get(status_key)
        passed = actual == expected if isinstance(expected, str) else actual in expected
        check(f"TOC {key}", passed, {"required": expected_required[key], "status": actual})

    expected_special_sections = {
        str(item.get("id")): str(item.get("kind") or "other")
        for item in layout.get("sections", [])
        if item.get("title_spacing_override")
    }
    special_section_ids = [str(item.get("section_id")) for item in evidence.get("special_sections", [])]
    check(
        "special-section spacing evidence complete",
        set(special_section_ids) == set(expected_special_sections) and len(special_section_ids) == len(set(special_section_ids)),
        {"expected": sorted(expected_special_sections), "actual": special_section_ids},
    )
    for item in evidence.get("special_sections", []):
        section_id = str(item.get("section_id"))
        expected_role = expected_special_sections.get(section_id)
        check(
            f"special section {section_id}",
            bool(item.get("source_compared"))
            and item.get("spacing_override_applied") is True
            and item.get("status") == "PASS"
            and item.get("section_role") == expected_role,
            {"expected_role": expected_role, "evidence": item},
        )

    expected_brand_assets = {
        str(item.get("id")): str(item.get("asset_type"))
        for item in layout.get("brand_assets", [])
        if item.get("required")
    }
    brand_ids = [str(item.get("asset_id")) for item in evidence.get("brand_assets", [])]
    actual_brand_assets = {
        str(item.get("asset_id")): str(item.get("asset_type"))
        for item in evidence.get("brand_assets", [])
    }
    check(
        "branding evidence complete",
        actual_brand_assets == expected_brand_assets and len(brand_ids) == len(set(brand_ids)),
        {"expected": expected_brand_assets, "actual": actual_brand_assets},
    )
    for item in evidence.get("brand_assets", []):
        passed = (
            item.get("full_display") is True
            and item.get("crop") == "none"
            and item.get("page_bound_clipping") is False
            and item.get("container_clipping") is False
            and item.get("aspect_ratio_locked") is True
            and item.get("pdf_visual_status") == "PASS"
        )
        check(f"brand asset {item.get('asset_id')}", passed, item)

    return {
        "schema_version": "1.0",
        "status": "PASS" if not errors else "FAIL",
        "project_id": project.get("project_id"),
        "layout_profile_id": layout.get("profile_id"),
        "checks": checks,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    project_path = args.project.resolve()
    evidence_path = args.evidence.resolve()
    report_path = args.report.resolve()
    ensure_distinct_paths({"project": project_path, "evidence": evidence_path, "report": report_path})
    if report_path.exists():
        raise SystemExit(f"Refusing to overwrite existing report: {report_path}")
    try:
        report = validate(project_path, evidence_path)
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        report = {"schema_version": "1.0", "status": "FAIL", "project_id": None, "layout_profile_id": None, "checks": [], "errors": [str(exc)]}
    atomic_write_json(report_path, report)
    print(f"{report['status']}: {len(report['errors'])} error(s) -> {report_path}")
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
