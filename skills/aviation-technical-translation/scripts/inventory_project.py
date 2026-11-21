"""Inventory aviation translation inputs and choose a conservative workflow.

Usage:
    python inventory_project.py PROJECT_ROOT --output PROJECT_ROOT/work/source_manifest.json

The scanner is read-only. It excludes common output/cache directories and writes
only the requested manifest. File-name classification is deliberately weak;
review all inferred roles before approving a project configuration. The manifest
stores project_root relative to its own location, so keep a bound manifest inside
the project tree whenever possible.
"""

from __future__ import annotations

import argparse
import importlib.util
import mimetypes
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from common import atomic_write_json, count_han_and_latin, load_json, microsoft_word_registered, relative_posix, require_suffix, sha256_file


DEFAULT_EXCLUDES = {
    ".git", ".svn", ".hg", "__pycache__", ".pytest_cache", ".mypy_cache",
    "work", "working", "intermediate", "render", "renders", "qa", "output", "outputs", "delivery", "dist",
}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".xml"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".svg"}
DECLARED_INPUT_ROLES = {
    "source_document", "translation_reference", "terminology", "localized_figure",
    "brand_asset", "layout_reference", "template",
}


def sample_text(path: Path, limit: int = 30000) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return ""
            reader = PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages[:3])[:limit]
        if suffix in {".docx", ".dotx"}:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
            root = ET.fromstring(xml)
            return " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))[:limit]
        if suffix == ".xlsx":
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
                parts = []
                if "xl/sharedStrings.xml" in names:
                    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    parts.extend(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
                return " ".join(parts)[:limit]
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return ""
    return ""


def page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except (ImportError, OSError, ValueError):
        return None


def image_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.lower() not in IMAGE_EXTENSIONS or path.suffix.lower() == ".svg":
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.width, image.height
    except (ImportError, OSError):
        return None


def looks_like_terminology(text: str) -> bool:
    lowered = text.lower()
    source_markers = ("source", "english", "原文", "源语言")
    target_markers = ("target", "chinese", "译文", "目标语言")
    return any(item in lowered for item in source_markers) and any(item in lowered for item in target_markers)


def classify(path: Path, text: str) -> tuple[str, str, float]:
    suffix = path.suffix.lower()
    name = path.stem.lower()
    normalized = re.sub(r"[^a-z0-9\u3400-\u9fff]+", "_", name)
    if suffix in {".dotx", ".dotm"}:
        return "template", "unknown", 0.98
    if suffix in {".csv", ".tsv", ".xlsx", ".xls"} and looks_like_terminology(text):
        return "terminology", "bilingual", 0.95
    if suffix == ".json" and "layout" in normalized:
        return "layout_spec", "neutral", 0.85
    if suffix in {".json", ".jsonl"} and any(token in normalized for token in ("content", "block", "table", "formula", "footnote", "toc")):
        return "structured_content", "bilingual", 0.8
    if suffix in IMAGE_EXTENSIONS:
        if any(token in normalized for token in ("logo", "flag", "brand", "seal")):
            return "brand_asset", "neutral", 0.7
        language = "zh-CN" if any(token in normalized for token in ("zh", "cn", "chinese", "中文", "汉化", "翻译")) else "unknown"
        return "localized_figure", language, 0.55 if language == "unknown" else 0.75
    if suffix in {".pdf", ".docx"}:
        han, latin = count_han_and_latin(text)
        language = "zh-CN" if han > max(20, latin * 0.15) else "en" if latin > 20 else "unknown"
        if language == "zh-CN" or any(token in normalized for token in ("translated", "translation", "chinese", "中文", "机翻", "译")):
            return "translation_reference", "zh-CN", 0.78 if language == "zh-CN" else 0.55
        if language == "en" or suffix == ".pdf" or any(token in normalized for token in ("source", "original", "english", "原文", "英文")):
            return "source_document", language, 0.86 if language == "en" else 0.6
        return "layout_reference", language, 0.5
    return "unclassified", "unknown", 0.2


def iter_files(
    root: Path,
    default_excludes: set[str],
    additional_excludes: set[str],
    included_excludes: set[str],
    output: Path,
) -> tuple[list[Path], list[dict[str, str]]]:
    result: list[Path] = []
    excluded_directories: list[dict[str, str]] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        retained: list[str] = []
        for directory in directories:
            lowered = directory.lower()
            reason = ""
            if lowered in additional_excludes:
                reason = "additional_exclude"
            elif lowered not in included_excludes and lowered in default_excludes:
                reason = "default_exclude"
            elif lowered not in included_excludes and directory.startswith("."):
                reason = "hidden_directory"
            if reason:
                excluded_directories.append({
                    "path": (current_path / directory).relative_to(root).as_posix(),
                    "reason": reason,
                })
            else:
                retained.append(directory)
        directories[:] = retained
        for filename in filenames:
            path = current_path / filename
            if path.resolve() == output.resolve():
                continue
            result.append(path)
    return (
        sorted(result, key=lambda item: item.as_posix().lower()),
        sorted(excluded_directories, key=lambda item: item["path"].lower()),
    )


def _resolve_declaration_path(raw_path: Any, base: Path, root: Path, label: str, warnings: list[str]) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path.strip():
        warnings.append(f"{label} has no usable relative path.")
        return None
    candidate = Path(raw_path)
    if candidate.is_absolute():
        warnings.append(f"{label} uses an absolute path and was not trusted: {raw_path}")
        return None
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        warnings.append(f"{label} escapes the project root and was not trusted: {raw_path}")
        return None
    return resolved


def discover_input_declarations(
    root: Path,
    files: list[Path],
) -> tuple[dict[Path, dict[str, Any]], list[str], list[str]]:
    """Find explicit project inputs and localized assets declared by figures.json.

    Project input declarations take precedence over figure-map declarations. A
    declaration never substitutes for the file itself: a missing required asset
    is returned as a publication blocker.
    """

    declarations: dict[Path, dict[str, Any]] = {}
    warnings: list[str] = []
    blockers: list[str] = []
    figure_maps: set[Path] = {path.resolve() for path in files if path.name.lower() == "figures.json"}

    def register(path: Path, value: dict[str, Any]) -> None:
        existing = declarations.get(path)
        if existing and (
            existing["approved"] != value["approved"] or existing["required"] != value["required"]
        ):
            selected_source = value["source"] if value["priority"] >= existing["priority"] else existing["source"]
            warnings.append(
                f"Conflicting input declarations for {relative_posix(path, root)}; "
                f"the higher-precedence declaration from {selected_source} was used."
            )
        if existing is None or value["priority"] >= existing["priority"]:
            sources = list(existing.get("sources", [])) if existing else []
            sources.append(value["source"])
            value["sources"] = sorted(set(sources))
            declarations[path] = value
        elif value["source"] not in existing["sources"]:
            existing["sources"].append(value["source"])
            existing["sources"].sort()

    project_files = [path for path in files if path.name.lower() == "project.json"]
    for project_path in project_files:
        try:
            project = load_json(project_path)
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not inspect project declarations in {relative_posix(project_path, root)}: {exc}")
            continue
        if not isinstance(project, dict):
            warnings.append(f"Project declaration is not an object: {relative_posix(project_path, root)}")
            continue
        project_label = relative_posix(project_path, root)
        figure_map_raw = project.get("paths", {}).get("figures") if isinstance(project.get("paths"), dict) else None
        if figure_map_raw:
            resolved_map = _resolve_declaration_path(
                figure_map_raw, project_path.parent, root, f"{project_label} paths.figures", warnings
            )
            if resolved_map:
                figure_maps.add(resolved_map)
        inputs = project.get("inputs", [])
        if not isinstance(inputs, list):
            warnings.append(f"{project_label} inputs is not an array; explicit input declarations were not read.")
            continue
        for index, item in enumerate(inputs):
            if not isinstance(item, dict) or not isinstance(item.get("role"), str):
                continue
            label = f"{project_label} inputs[{index}]"
            if item["role"] not in DECLARED_INPUT_ROLES:
                warnings.append(f"{label} has an unsupported role and was not trusted: {item['role']}")
                continue
            resolved = _resolve_declaration_path(item.get("path"), project_path.parent, root, label, warnings)
            if resolved is None:
                continue
            required = bool(item.get("required", False))
            approved = bool(item.get("approved", False))
            register(resolved, {
                "role": item["role"],
                "approved": approved,
                "required": required,
                "authoritative": item["role"] == "source_document",
                "language": str(item.get("language") or ("zh-CN" if item["role"] == "localized_figure" else "unknown")),
                "priority": 2,
                "source": label,
            })
            if required and not resolved.is_file():
                blockers.append(f"Required input declared by {label} is missing: {relative_posix(resolved, root)}")

    for figure_map in sorted(figure_maps, key=lambda item: item.as_posix().lower()):
        if not figure_map.is_file():
            try:
                display = relative_posix(figure_map, root)
            except ValueError:
                display = str(figure_map)
            blockers.append(f"Declared figure map is missing: {display}")
            continue
        try:
            payload = load_json(figure_map)
        except (OSError, ValueError) as exc:
            warnings.append(f"Could not inspect figure declarations in {relative_posix(figure_map, root)}: {exc}")
            continue
        items = payload.get("figures", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            warnings.append(f"Figure declaration is not an array: {relative_posix(figure_map, root)}")
            continue
        map_label = relative_posix(figure_map, root)
        for index, item in enumerate(items):
            if not isinstance(item, dict) or item.get("localized") is False:
                continue
            label = f"{map_label} figures[{index}]"
            resolved = _resolve_declaration_path(item.get("path"), figure_map.parent, root, label, warnings)
            if resolved is None:
                continue
            register(resolved, {
                "role": "localized_figure",
                "approved": bool(item.get("approved", False)),
                "required": True,
                "authoritative": False,
                "language": "zh-CN",
                "priority": 1,
                "source": label,
            })
            if not resolved.is_file():
                blockers.append(f"Required localized figure declared by {label} is missing: {relative_posix(resolved, root)}")

    return declarations, warnings, sorted(set(blockers))


def probe_word_com(enabled: bool) -> tuple[bool, dict[str, Any], list[str]]:
    """Optionally start and quit Word; registry presence alone is not renderer proof."""

    result: dict[str, Any] = {"requested": enabled, "verified": False, "status": "not_requested"}
    warnings: list[str] = []
    if not enabled:
        return False, result, warnings
    if os.name != "nt":
        result["status"] = "unsupported_platform"
        warnings.append("Word COM probing is only supported on Windows.")
        return False, result, warnings
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        result["status"] = "probe_dependency_missing"
        warnings.append("Cannot probe Word COM because Windows PowerShell was not found on PATH.")
        return False, result, warnings
    script = (
        "$ErrorActionPreference='Stop'; $word=$null; "
        "try { $word=New-Object -ComObject Word.Application; $word.Visible=$false; "
        "$word.DisplayAlerts=0; [Console]::Out.Write([string]$word.Version) } "
        "finally { if ($null -ne $word) { try { $word.Quit() } catch {}; "
        "try { [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($word) } catch {} } }"
    )
    try:
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["status"] = "probe_failed"
        result["detail"] = str(exc)
        warnings.append(f"Word COM probe could not complete: {exc}")
        return False, result, warnings
    if completed.returncode == 0 and completed.stdout.strip():
        result.update({"verified": True, "status": "verified", "version": completed.stdout.strip()})
        return True, result, warnings
    detail = (completed.stderr or completed.stdout or f"exit code {completed.returncode}").strip()
    result.update({"status": "probe_failed", "detail": detail[:1000]})
    warnings.append(
        "Microsoft Word may be registered, but the Word COM renderer was not usable in this host/session: "
        + detail[:500]
    )
    return False, result, warnings


def select_mode(
    requested: str,
    allow_downgrade: bool,
    inputs: list[dict],
    word_installed: bool,
    renderer_verified: bool,
    preliminary_blockers: list[str] | None = None,
    raster_verification_ready: bool = True,
) -> tuple[str, list[str], list[str]]:
    roles = [item["role"] for item in inputs]
    source_count = roles.count("source_document")
    unapproved_required_figures = [
        item for item in inputs
        if item["role"] == "localized_figure" and item.get("required") and not item.get("approved")
    ]
    publication_ready = (
        source_count == 1
        and "structured_content" in roles
        and "layout_spec" in roles
        and renderer_verified
        and not unapproved_required_figures
        and not preliminary_blockers
        and raster_verification_ready
    )
    reasons: list[str] = []
    blockers: list[str] = list(preliminary_blockers or [])
    if source_count == 0:
        blockers.append("No authoritative English source document was detected.")
    elif source_count > 1:
        blockers.append("Multiple source-document candidates require explicit human designation.")

    if requested == "translation_only":
        return "translation_only", ["The requested mode is translation_only."], blockers
    if requested == "publication_grade_docx":
        if publication_ready:
            return "publication_grade_docx", ["All conservative publication prerequisites were detected."], blockers
        missing = []
        if "structured_content" not in roles:
            missing.append("structured content")
        if "layout_spec" not in roles:
            missing.append("approved layout spec")
        if not word_installed:
            missing.append("Microsoft Word Desktop installation")
        elif not renderer_verified:
            missing.append("verified Word COM renderer (run inventory with --probe-word-com)")
        if unapproved_required_figures:
            missing.append("approval for every required localized figure")
        if not raster_verification_ready:
            missing.append("Pillow raster-asset verification dependency")
        if missing:
            blockers.append("Publication-grade mode is missing: " + ", ".join(missing) + ".")
        if allow_downgrade:
            reasons.append("Explicit downgrade was allowed, so translation_only was selected.")
            return "translation_only", reasons, blockers
        reasons.append("The requested publication-grade mode is retained but blocked; no silent downgrade occurred.")
        return "publication_grade_docx", reasons, blockers
    if publication_ready:
        return "publication_grade_docx", ["Auto mode found structured content, an approved layout profile, approved required figures, and a verified Word COM renderer."], blockers
    return "translation_only", ["Auto mode conservatively selected translation_only because publication prerequisites were incomplete."], blockers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--requested-mode", choices=("auto", "translation_only", "publication_grade_docx"), default="auto")
    parser.add_argument(
        "--cost-profile",
        choices=("economy", "balanced", "maximum_quality"),
        default="balanced",
        help="Model-cost routing profile recorded in the source manifest; default balanced.",
    )
    parser.add_argument(
        "--escalation-mode",
        choices=("manual_handoff", "auto_escalate"),
        default="manual_handoff",
        help="Escalation execution mode recorded in the source manifest; safe default manual_handoff.",
    )
    parser.add_argument("--allow-downgrade", action="store_true")
    parser.add_argument("--exclude", action="append", default=[], help="Additional directory name to exclude; repeatable.")
    parser.add_argument(
        "--include-excluded",
        action="append",
        default=[],
        help="Directory name to include even when it is hidden or in the default exclusion set; repeatable.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Disable named default exclusions. Hidden directories remain excluded unless named with --include-excluded.",
    )
    parser.add_argument(
        "--probe-word-com",
        action="store_true",
        help="Start and quit Microsoft Word to verify that Word COM is usable in the current host/session.",
    )
    parser.add_argument(
        "--overwrite-manifest",
        action="store_true",
        help="Replace an existing output only when it is already recognizable as a source manifest.",
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        raise SystemExit(f"Project root is not a directory: {root}")
    try:
        require_suffix(output, ".json", "--output")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if output.exists():
        try:
            existing = load_json(output)
        except (ValueError, FileNotFoundError) as exc:
            raise SystemExit(f"Refusing to overwrite an existing non-manifest output: {output}: {exc}") from exc
        manifest_markers = {"schema_version", "project_root", "requested_mode", "selected_mode", "inputs"}
        if not isinstance(existing, dict) or not manifest_markers.issubset(existing):
            raise SystemExit(f"Refusing to overwrite an existing file that is not a recognized source manifest: {output}")
        if not args.overwrite_manifest:
            raise SystemExit(
                f"Manifest output already exists: {output}. Use --overwrite-manifest only after confirming it is disposable."
            )
    try:
        manifest_project_root = Path(os.path.relpath(root, start=output.parent)).as_posix()
    except ValueError as exc:
        raise SystemExit(
            "The manifest output and project root must be on the same filesystem volume so project_root can be portable."
        ) from exc
    additional_excludes = {item.strip().lower() for item in args.exclude if item.strip()}
    included_excludes = {item.strip().lower() for item in args.include_excluded if item.strip()}
    conflict = additional_excludes & included_excludes
    if conflict:
        raise SystemExit("A directory name cannot be both --exclude and --include-excluded: " + ", ".join(sorted(conflict)))
    active_defaults = set() if args.no_default_excludes else {item.lower() for item in DEFAULT_EXCLUDES}
    files, excluded_directories = iter_files(
        root,
        active_defaults,
        additional_excludes,
        included_excludes,
        output,
    )
    warnings: list[str] = []
    input_declarations, declaration_warnings, declaration_blockers = discover_input_declarations(root, files)
    warnings.extend(declaration_warnings)
    missing_pdf_reader = any(path.suffix.lower() == ".pdf" for path in files) and importlib.util.find_spec("pypdf") is None
    missing_image_reader = any(path.suffix.lower() in IMAGE_EXTENSIONS - {".svg"} for path in files) and importlib.util.find_spec("PIL") is None
    if missing_pdf_reader:
        warnings.append("Missing dependency 'pypdf': PDF language, text, and page-count detection is unavailable; explicitly designate the authoritative source before proceeding.")
    if missing_image_reader:
        warnings.append("Missing dependency 'Pillow': raster dimensions cannot be verified; publication figure approval remains incomplete.")
    inputs: list[dict] = []
    used_ids: set[str] = set()
    rank_by_role = {"source_document": 1, "terminology": 2, "translation_reference": 3, "localized_figure": 2}
    for index, path in enumerate(files, 1):
        text = sample_text(path)
        role, language, confidence = classify(path, text)
        declaration = input_declarations.get(path.resolve())
        if declaration:
            role = declaration["role"]
            language = declaration["language"]
            confidence = 1.0
        stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-.") or f"input-{index}"
        identifier = stem
        serial = 2
        while identifier in used_ids:
            identifier = f"{stem}-{serial}"
            serial += 1
        used_ids.add(identifier)
        record = {
            "id": identifier,
            "role": role,
            "path": relative_posix(path, root),
            "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "language": language,
            "authority_rank": rank_by_role.get(role, 9),
            "required": declaration["required"] if declaration else role == "source_document",
            "read_only": True,
            "authoritative": declaration["authoritative"] if declaration else False,
            "approved": declaration["approved"] if declaration else False,
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
            "detection": {
                "method": "declared" if declaration else "content" if text else "filename_hint" if confidence > 0.2 else "unknown",
                "confidence": confidence,
            },
        }
        if declaration:
            record["declaration_sources"] = declaration["sources"]
        pages = page_count(path)
        if pages:
            record["page_count"] = pages
        dimensions = image_size(path)
        if dimensions:
            record["width_px"], record["height_px"] = dimensions
        inputs.append(record)

    word_registration_detected = microsoft_word_registered()
    renderer_verified, word_probe, word_probe_warnings = probe_word_com(args.probe_word_com)
    warnings.extend(word_probe_warnings)
    word_installed = word_registration_detected or renderer_verified
    if word_installed and not args.probe_word_com and args.requested_mode != "translation_only":
        warnings.append(
            "Microsoft Word registration was detected, but registry evidence does not verify renderer usability. "
            "Use --probe-word-com in the intended rendering session before publication-grade acceptance."
        )
    inferred_pdf_source = missing_pdf_reader and any(
        item["role"] == "source_document"
        and item["path"].lower().endswith(".pdf")
        and item["detection"]["method"] != "declared"
        for item in inputs
    )
    if inferred_pdf_source:
        declaration_blockers.append(
            "A PDF source_document role was inferred without PDF content parsing; install pypdf or provide an explicit human designation."
        )
    required_raster_figures = [
        item for item in inputs
        if item["role"] == "localized_figure"
        and item.get("required")
        and Path(item["path"]).suffix.lower() in IMAGE_EXTENSIONS - {".svg"}
    ]
    raster_verification_ready = not (missing_image_reader and required_raster_figures)
    mode, reasons, blockers = select_mode(
        args.requested_mode,
        args.allow_downgrade,
        inputs,
        word_installed,
        renderer_verified,
        preliminary_blockers=sorted(set(declaration_blockers)),
        raster_verification_ready=raster_verification_ready,
    )
    manifest = {
        "schema_version": "1.0",
        "project_root": manifest_project_root,
        "locked": False,
        "requested_mode": args.requested_mode,
        "selected_mode": mode,
        "cost_profile": args.cost_profile,
        "escalation_mode": args.escalation_mode,
        "allow_downgrade": bool(args.allow_downgrade),
        "scan_policy": {
            "use_default_excludes": not args.no_default_excludes,
            "default_excludes": sorted(DEFAULT_EXCLUDES),
            "active_default_excludes": sorted(active_defaults),
            "additional_excludes": sorted(additional_excludes),
            "include_overrides": sorted(included_excludes),
            "hidden_directories_excluded": True,
        },
        "excluded_directories": excluded_directories,
        "capabilities": {
            "microsoft_word": word_installed,
            "word_registration_detected": word_registration_detected,
            "authoritative_renderer": "word-com" if renderer_verified else "none",
            "renderer_available": renderer_verified,
            "word_com_probe": word_probe,
        },
        "inputs": inputs,
        "selection_reasons": reasons,
        "blocking_issues": blockers,
        "warnings": warnings,
    }
    atomic_write_json(output, manifest)
    print(f"Inventoried {len(inputs)} files -> {output}")
    print(f"Selected mode: {mode}; blocking issues: {len(blockers)}; warnings: {len(warnings)}")


if __name__ == "__main__":
    main()
