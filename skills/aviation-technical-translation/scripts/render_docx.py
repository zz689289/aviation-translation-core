"""Postprocess a DOCX in Microsoft Word, export PDF, and render page PNGs.

Usage:
    python render_docx.py --input draft.docx --actions draft.actions.json \
        --output-dir qa/render --backend word-com --stability-runs 2

The command refuses an existing output directory and publishes a complete
render tree atomically. Tool paths are discovered from PATH or supplied
explicitly; no machine-specific path is embedded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from common import atomic_write_json, find_executable, load_json, load_jsonl, microsoft_word_registered, resolve_relative, sha256_file


SCRIPT_DIR = Path(__file__).resolve().parent


def ensure_safe_output_directory(project_path: Path | None, output_dir: Path) -> None:
    if project_path is None:
        return
    project_path = project_path.resolve()
    project = load_json(project_path)
    base = project_path.parent.resolve()
    protected_files = {project_path}
    protected_directories: set[Path] = set()
    for item in project.get("inputs", []):
        protected_files.add(resolve_relative(base, item["path"]))
    for key, value in project.get("paths", {}).items():
        path = resolve_relative(base, value)
        if path.is_dir():
            protected_directories.add(path)
        else:
            protected_files.add(path)
        if key in {"content", "figures"} and path.parent != base:
            protected_directories.add(path.parent)
    resolved_output = output_dir.resolve()
    if resolved_output in protected_files:
        raise ValueError(f"Render output directory collides with a protected project file: {resolved_output}")
    for protected in protected_directories:
        try:
            resolved_output.relative_to(protected.resolve())
        except ValueError:
            continue
        raise ValueError(f"Render output directory is inside protected project source tree: {resolved_output}")


def powershell_path(explicit: str | None) -> Path:
    found = find_executable(explicit, ("powershell.exe", "powershell", "pwsh.exe", "pwsh"))
    if found:
        return found
    if os.name == "nt" and os.environ.get("WINDIR"):
        candidate = Path(os.environ["WINDIR"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("Windows PowerShell was not found. Pass --powershell PATH.")


def word_pids(powershell: Path) -> set[int]:
    command = [str(powershell), "-NoProfile", "-Command", "@(Get-Process WINWORD -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','"]
    result = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    return {int(item) for item in result.stdout.strip().split(",") if item.strip().isdigit()}


def render_pngs(pdf: Path, output_dir: Path, pdftoppm: Path, dpi: int, timeout: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=False)
    prefix = output_dir / "page"
    subprocess.run([str(pdftoppm), "-png", "-r", str(dpi), str(pdf), str(prefix)], check=True, timeout=timeout)
    def page_number(path: Path) -> int:
        match = re.search(r"(\d+)$", path.stem)
        if match is None:
            raise RuntimeError(f"Cannot determine rendered page number from {path.name}")
        return int(match.group(1))

    generated = sorted(output_dir.glob("page-*.png"), key=page_number)
    if not generated:
        raise RuntimeError(f"pdftoppm produced no PNG pages from {pdf}")
    pages = []
    for index, source in enumerate(generated, 1):
        target = output_dir / f"page_{index:04d}.png"
        source.replace(target)
        pages.append(target)
    return pages


def page_pixel_snapshot(path: Path) -> dict[str, Any]:
    image_module = __import__("PIL.Image", fromlist=["Image"])
    with image_module.open(path) as source:
        rgba = source.convert("RGBA")
        digest = hashlib.sha256()
        digest.update(f"{rgba.width}x{rgba.height}:RGBA\n".encode("ascii"))
        digest.update(rgba.tobytes())
        return {"dimensions": [rgba.width, rgba.height], "rgba_sha256": digest.hexdigest()}


def project_expectations(project_path: Path | None) -> dict[str, Any] | None:
    if project_path is None:
        return None
    project = load_json(project_path)
    base = project_path.parent
    paths = {key: resolve_relative(base, value) for key, value in project["paths"].items()}
    blocks = load_jsonl(paths["content"])
    layout = load_json(paths["layout"]) if "layout" in paths else {}
    render_policy = layout.get("render_policy", {})
    toc = load_json(paths["toc"]) if "toc" in paths else {"entries": [{"block_id": block["id"], "include": block.get("toc_policy") == "include"} for block in blocks if block["block_type"] == "heading"]}
    block_by_id = {block["id"]: block for block in blocks}
    expected_toc = [block_by_id[item["block_id"]]["target_text"] for item in toc["entries"] if item["include"]]
    table_formula_cells = 0
    for table_path in sorted(paths["tables_dir"].glob("*.json")) if "tables_dir" in paths else []:
        table = load_json(table_path)
        table_formula_cells += sum(cell.get("kind") == "formula" for row in table.get("rows", []) for cell in row.get("cells", []))
    return {
        "toc_text": expected_toc,
        "tables": sum(block["block_type"] in {"table", "requirement", "regulatory_quote"} for block in blocks),
        "inline_shapes": sum(block["block_type"] == "figure" for block in blocks),
        "footnotes": sum(block["block_type"] == "footnote_anchor" for block in blocks),
        "omath_objects": sum(block["block_type"] == "formula" for block in blocks) + table_formula_cells,
        "toc_objects": sum(block["block_type"] == "toc" for block in blocks),
        "sections": 1 + sum(block["block_type"] == "section_break" for block in blocks),
        "declared_renderer": render_policy.get("renderer"),
        "declared_dpi": render_policy.get("image_dpi"),
        "declared_stability_runs": render_policy.get("stability_runs"),
        "selected_mode": project.get("selected_mode") or project.get("requested_mode"),
    }


def one_run(index: int, input_docx: Path, actions: Path, output_dir: Path, powershell: Path, pdftoppm: Path, dpi: int, timeout: int, expectations: dict[str, Any] | None) -> dict[str, Any]:
    run_dir = output_dir / f"run_{index}"
    run_dir.mkdir()
    work_docx = run_dir / "working.docx"
    pdf = run_dir / "render.pdf"
    stats = run_dir / "word_stats.json"
    toc = run_dir / "toc_entries.json"
    shutil.copy2(input_docx, work_docx)
    before = word_pids(powershell)
    command = [
        str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT_DIR / "word_postprocess.ps1"),
        "-DocxPath", str(work_docx), "-PdfPath", str(pdf), "-ActionsPath", str(actions),
        "-StatsPath", str(stats), "-TocEntriesPath", str(toc),
    ]
    command_error: BaseException | None = None
    try:
        subprocess.run(command, check=True, timeout=timeout)
    except BaseException as exc:
        command_error = exc
    try:
        after = word_pids(powershell)
    except BaseException as exc:
        if command_error is not None:
            raise RuntimeError(f"Word COM failed and residue check also failed: {exc}") from command_error
        raise
    residue = sorted(after - before)
    if residue and command_error is not None:
        raise RuntimeError(f"Word COM failed and left new WINWORD processes: {residue}") from command_error
    if command_error is not None:
        raise command_error
    if residue:
        raise RuntimeError(f"Word COM left new WINWORD processes: {residue}")
    pages = render_pngs(pdf, run_dir / "pages", pdftoppm, dpi, timeout)
    word_stats = json.loads(stats.read_text(encoding="utf-8-sig"))
    if int(word_stats["pages"]) != len(pages):
        raise RuntimeError(f"Word page count {word_stats['pages']} differs from rendered PNG count {len(pages)}")
    structure = None
    if expectations is not None:
        toc_data = json.loads(toc.read_text(encoding="utf-8-sig"))
        if isinstance(toc_data, dict):
            toc_data = [toc_data]
        actual_toc = [re.sub(r"\t+\d+\s*$", "", str(item.get("text", ""))).strip() for item in toc_data]
        counts = {key: int(word_stats.get(key, -1)) for key in ("tables", "inline_shapes", "footnotes", "omath_objects", "toc_objects", "sections")}
        expected_counts = {key: expectations[key] for key in counts}
        structure = {"pass": actual_toc == expectations["toc_text"] and counts == expected_counts, "expected_toc": expectations["toc_text"], "actual_toc": actual_toc, "expected_counts": expected_counts, "actual_counts": counts}
    pixel_snapshots = [page_pixel_snapshot(page) for page in pages]
    return {
        "run": index, "word_stats": word_stats, "docx_sha256": sha256_file(work_docx), "pdf_sha256": sha256_file(pdf),
        "working_docx_relative": f"run_{index}/working.docx",
        "pages_relative": f"run_{index}/pages",
        "page_files": [page.name for page in pages],
        "page_sha256": [sha256_file(page) for page in pages],
        "page_dimensions": [item["dimensions"] for item in pixel_snapshots],
        "page_pixel_sha256": [item["rgba_sha256"] for item in pixel_snapshots],
        "structure_validation": structure,
    }


def runs_are_deterministic(runs: list[dict[str, Any]]) -> bool:
    """Compare semantic Word evidence and decoded pixels, not volatile PDF bytes."""

    if len(runs) <= 1:
        return True
    first = runs[0]
    return all(
        first["word_stats"] == other["word_stats"]
        and first["page_dimensions"] == other["page_dimensions"]
        and first["page_pixel_sha256"] == other["page_pixel_sha256"]
        for other in runs[1:]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--actions", type=Path, help="Build action JSON. Omit only for an already postprocessed DOCX.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--backend", choices=("word-com",), default="word-com")
    parser.add_argument("--dpi", type=int, help="Raster DPI override. Omit to use layout.render_policy.image_dpi, then 220.")
    parser.add_argument("--stability-runs", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--powershell")
    parser.add_argument("--pdftoppm")
    parser.add_argument("--project", type=Path, help="Optional project configuration for TOC and object-count verification.")
    args = parser.parse_args()

    input_docx = args.input.resolve()
    actions = args.actions.resolve() if args.actions else None
    output_dir = args.output_dir.resolve()
    if not input_docx.is_file():
        raise SystemExit("--input DOCX must exist.")
    if actions is not None and not actions.is_file():
        raise SystemExit("--actions JSON does not exist.")
    if output_dir.exists() and not output_dir.is_dir():
        raise SystemExit(f"Render output path exists but is not a directory: {output_dir}")
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing render output directory: {output_dir}")
    try:
        ensure_safe_output_directory(args.project.resolve() if args.project else None, output_dir)
    except (ValueError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.stability_runs < 1:
        raise SystemExit("--stability-runs must be at least 1.")
    if args.backend == "word-com" and not microsoft_word_registered():
        raise SystemExit("Microsoft Word Desktop COM is not registered on this host.")
    powershell = powershell_path(args.powershell)
    pdftoppm = find_executable(args.pdftoppm, ("pdftoppm.exe", "pdftoppm"))
    if pdftoppm is None:
        raise SystemExit("Poppler pdftoppm was not found. Put it on PATH or pass --pdftoppm PATH.")

    project_path = args.project.resolve() if args.project else None
    if project_path is not None and not project_path.is_file():
        raise SystemExit(f"--project JSON does not exist: {project_path}")
    expectations = project_expectations(project_path)
    if expectations and expectations.get("selected_mode") == "publication_grade_docx" and args.stability_runs < 2:
        raise SystemExit(
            "Publication-grade release requires at least two independent Word COM renders; "
            "a single run is diagnostic only."
        )
    if expectations and expectations.get("declared_stability_runs") and args.stability_runs < int(expectations["declared_stability_runs"]):
        raise SystemExit(
            f"Requested stability runs {args.stability_runs} are below layout render_policy.stability_runs="
            f"{expectations['declared_stability_runs']}."
        )
    if expectations and expectations.get("declared_renderer") and expectations["declared_renderer"] != args.backend:
        raise SystemExit(
            f"Requested backend {args.backend!r} conflicts with layout render_policy.renderer="
            f"{expectations['declared_renderer']!r}."
        )
    dpi = args.dpi if args.dpi is not None else ((expectations.get("declared_dpi") if expectations else None) or 220)
    if dpi < 72:
        raise SystemExit("Render DPI must be at least 72.")
    if dpi > 1200:
        raise SystemExit("Render DPI must not exceed 1200 without an explicit tool policy update.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        if actions is None:
            actions = staging_dir / "empty_actions.json"
            atomic_write_json(
                actions,
                {
                    "schema_version": "1.0", "math_actions": [], "footnote_actions": [],
                    "expected_markers": {"math": 0, "footnotes": 0},
                },
            )
        input_sha256 = sha256_file(input_docx)
        actions_sha256 = sha256_file(actions)
        project_sha256 = sha256_file(project_path) if project_path is not None else None
        runs = [one_run(index, input_docx, actions, staging_dir, powershell, pdftoppm, dpi, args.timeout, expectations) for index in range(1, args.stability_runs + 1)]
        if sha256_file(input_docx) != input_sha256 or sha256_file(actions) != actions_sha256 or (project_path is not None and sha256_file(project_path) != project_sha256):
            raise RuntimeError("Render inputs changed during the run; discard the render and retry from a locked source.")
        stable = runs_are_deterministic(runs)
        structure_pass = all(run["structure_validation"] is None or run["structure_validation"]["pass"] for run in runs)
        blocking_reasons = []
        if not stable:
            blocking_reasons.append("NONDETERMINISTIC_RENDER")
        if not structure_pass:
            blocking_reasons.append("STRUCTURE_MISMATCH")
        report = {
            "schema_version": "2.0", "status": "PASS" if stable and structure_pass else "FAIL", "backend": args.backend, "dpi": dpi,
            "input_sha256": input_sha256, "actions_sha256": actions_sha256, "project_sha256": project_sha256,
            "declared_render_policy": {
                "renderer": expectations.get("declared_renderer") if expectations else None,
                "image_dpi": expectations.get("declared_dpi") if expectations else None,
                "stability_runs": expectations.get("declared_stability_runs") if expectations else None,
            },
            "stability_runs": len(runs), "stable": stable, "structure_pass": structure_pass,
            "blocking_reasons": blocking_reasons, "runs": runs,
        }
        atomic_write_json(staging_dir / "render_report.json", report)
        if output_dir.exists():
            raise RuntimeError(f"Render output directory appeared during the run: {output_dir}")
        staging_dir.replace(output_dir)
        print(f"Rendered {len(runs)} run(s); stable={stable}; report -> {output_dir / 'render_report.json'}")
        if not stable or not structure_pass:
            raise SystemExit(1)
    except BaseException:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        raise


if __name__ == "__main__":
    main()
