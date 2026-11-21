"""Create inputs, locked manifests, and project files for the virtual dry-run.

This is example data, not a generic build script. It intentionally uses a
different title, page count, annex, identifiers, and object counts from the
project that inspired the Skill. Re-running it replaces only virtual-example
inputs and rewrites their recorded hashes.

Input: no project input; fixture values are defined only in this example.
Output: complete translation_only/ and publication_grade/ fixtures below --output-dir.
Run: python create_fixture.py [--output-dir PATH] [--overwrite]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import textwrap
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parent

PUBLICATION_SOURCE_PAGES = [
    ["EASA-NEXT D-7.2"],
    ["Contents"],
    [
        "1 Compliance method",
        (
            "Validation of the high-fidelity FSM Solution uses test data. "
            "Issue 2 separates Safety from Security and identifies the MOCs. "
            "A high-frequency input is qualified before certification, and model errors are reported."
        ),
    ],
    ["Figure: Flight-envelope example"],
    ["Table: Scope matrix", "D = q S C_D"],
    ["The evidence set is configuration controlled.", "Annex C Informative examples"],
    ["This annex is informative."],
]

TRANSLATION_SOURCE_PAGES = [
    ["1 Scope", "Validation of the high-fidelity model uses test data."],
    ["Annex C Informative material"],
    ["Synthetic unmapped page 3."],
    ["Synthetic unmapped page 4."],
    ["Synthetic unmapped page 5."],
    ["Synthetic unmapped page 6."],
    ["Synthetic unmapped page 7."],
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def create_pdf(path: Path, pages: list[list[str]], language: str) -> None:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError("The virtual fixture requires reportlab.") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=(595, 842))
    font = "Helvetica"
    if language == "zh-CN":
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        font = "STSong-Light"
    for page_number, paragraphs in enumerate(pages, 1):
        text = pdf.beginText(60, 780)
        text.setFont(font, 11)
        for paragraph in paragraphs:
            wrapped = textwrap.wrap(
                paragraph,
                width=78 if language == "en" else 38,
                break_long_words=False,
                break_on_hyphens=False,
            ) or [""]
            for line in wrapped:
                text.textLine(line)
            text.textLine("")
        text.setFont(font, 8)
        text.textLine(f"Virtual fixture page {page_number}")
        pdf.drawText(text)
        pdf.showPage()
    pdf.save()


def create_figure(path: Path) -> None:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("The virtual fixture requires Pillow.") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (960, 480), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 50, 900, 400), outline="#1F5D7A", width=5)
    draw.line((130, 340, 780, 120), fill="#007F9F", width=8)
    draw.polygon(((780, 120), (738, 126), (764, 160)), fill="#007F9F")
    draw.text((110, 80), "APPROVED LOCALIZED FIGURE - VIRTUAL", fill="#222222")
    image.save(path, dpi=(300, 300))


def create_terms(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["source", "target", "context"])
        writer.writerow(["Means of Compliance", "符合性方法", "certification"])
        writer.writerow(["high-fidelity model", "高保真模型", "simulation"])


def manifest_input(
    project_root: Path,
    *,
    identifier: str,
    role: str,
    relative_path: str,
    media_type: str,
    language: str,
    authority_rank: int,
    required: bool,
    authoritative: bool,
    approved: bool | None = None,
    page_count: int | None = None,
    dimensions: tuple[int, int] | None = None,
) -> dict[str, Any]:
    path = project_root / relative_path
    record: dict[str, Any] = {
        "id": identifier,
        "role": role,
        "path": relative_path,
        "media_type": media_type,
        "language": language,
        "authority_rank": authority_rank,
        "required": required,
        "read_only": True,
        "authoritative": authoritative,
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
        "detection": {"method": "declared", "confidence": 1.0},
    }
    if approved is not None:
        record["approved"] = approved
    if page_count is not None:
        record["page_count"] = page_count
    if dimensions is not None:
        record["width_px"], record["height_px"] = dimensions
    return record


def project_input(record: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "id", "role", "path", "media_type", "language", "authority_rank", "required",
        "read_only", "approved", "sha256", "size_bytes", "page_count", "width_px",
        "height_px", "detection",
    }
    return {key: value for key, value in record.items() if key in allowed}


def seed_static_fixture(root: Path) -> None:
    """Copy packaged structured-content templates into a separate fixture root."""

    if root == DEFAULT_ROOT.resolve():
        return
    for mode in ("translation_only", "publication_grade"):
        source_root = DEFAULT_ROOT / mode
        source_content = source_root / "content"
        if not source_content.is_dir():
            raise RuntimeError(f"Packaged fixture content is missing: {source_content}")
        destination_root = root / mode
        shutil.copytree(source_content, destination_root / "content", dirs_exist_ok=True)
        if mode == "publication_grade":
            source_layout = source_root / "layout_spec.json"
            if not source_layout.is_file():
                raise RuntimeError(f"Packaged fixture layout is missing: {source_layout}")
            destination_root.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_layout, destination_root / "layout_spec.json")


def create_translation_only(root: Path) -> None:
    project_root = root / "translation_only"
    inputs = project_root / "inputs"
    create_pdf(inputs / "easa-next-d7-2-en.pdf", TRANSLATION_SOURCE_PAGES, "en")
    create_terms(inputs / "approved_terms.csv")
    manifest_inputs = [
        manifest_input(
            project_root,
            identifier="source-en", role="source_document", relative_path="inputs/easa-next-d7-2-en.pdf",
            media_type="application/pdf", language="en", authority_rank=1, required=True,
            authoritative=True, page_count=len(TRANSLATION_SOURCE_PAGES),
        ),
        manifest_input(
            project_root,
            identifier="terms", role="terminology", relative_path="inputs/approved_terms.csv",
            media_type="text/csv", language="bilingual", authority_rank=2, required=False,
            authoritative=False, approved=True,
        ),
    ]
    selection_reasons = ["No approved publication layout or renderer is supplied."]
    manifest = {
        "schema_version": "1.0",
        "project_root": ".",
        "locked": True,
        "requested_mode": "auto",
        "selected_mode": "translation_only",
        "allow_downgrade": False,
        "capabilities": {"microsoft_word": False, "authoritative_renderer": "none", "renderer_available": False},
        "inputs": manifest_inputs,
        "selection_reasons": selection_reasons,
        "blocking_issues": [],
        "warnings": [],
    }
    project = {
        "schema_version": "1.0",
        "project_id": "easa-next-translation-review",
        "title": "EASA-NEXT terminology review",
        "deliverable_id": "TR-ALPHA",
        "languages": {"source": "en", "target": "zh-CN"},
        "requested_mode": "auto",
        "selected_mode": "translation_only",
        "allow_downgrade": False,
        "paths": {
            "content": "content/blocks.jsonl",
            "tables_dir": "content/tables",
            "formulas": "content/formulas.jsonl",
            "footnotes": "content/footnotes.jsonl",
            "toc": "content/toc.json",
            "terminology": "inputs/approved_terms.csv",
            "source_manifest": "source_manifest.json",
        },
        "inputs": [project_input(item) for item in manifest_inputs],
        "capabilities": {
            "microsoft_word": False, "authoritative_renderer": "none",
            "renderer_available": False, "fonts_verified": False,
        },
        "document": {
            "title": "EASA-NEXT terminology review",
            "subject": "English to Chinese translation review",
            "creator": "",
            "language": "zh-CN",
        },
        "selection_reasons": selection_reasons,
        "blocking_issues": [],
    }
    write_json(project_root / "source_manifest.json", manifest)
    write_json(project_root / "project.json", project)


def create_publication_grade(root: Path) -> None:
    project_root = root / "publication_grade"
    inputs = project_root / "inputs"
    source_path = inputs / "easa-next-d7-2-en.pdf"
    draft_path = inputs / "easa-next-d7-2-zh-draft.pdf"
    terms_path = inputs / "approved_terms.csv"
    figure_path = project_root / "content" / "assets" / "fig-flight-envelope-zh.png"
    create_pdf(source_path, PUBLICATION_SOURCE_PAGES, "en")
    create_pdf(
        draft_path,
        [[f"EASA-NEXT D-7.2 虚拟初译，第 {index} 页"] for index in range(1, len(PUBLICATION_SOURCE_PAGES) + 1)],
        "zh-CN",
    )
    create_terms(terms_path)
    create_figure(figure_path)
    manifest_inputs = [
        manifest_input(
            project_root,
            identifier="source-en", role="source_document", relative_path="inputs/easa-next-d7-2-en.pdf",
            media_type="application/pdf", language="en", authority_rank=1, required=True,
            authoritative=True, page_count=len(PUBLICATION_SOURCE_PAGES),
        ),
        manifest_input(
            project_root,
            identifier="terms", role="terminology", relative_path="inputs/approved_terms.csv",
            media_type="text/csv", language="bilingual", authority_rank=2, required=True,
            authoritative=False, approved=True,
        ),
        manifest_input(
            project_root,
            identifier="draft-zh", role="translation_reference", relative_path="inputs/easa-next-d7-2-zh-draft.pdf",
            media_type="application/pdf", language="zh-CN", authority_rank=3, required=False,
            authoritative=False, page_count=len(PUBLICATION_SOURCE_PAGES),
        ),
        manifest_input(
            project_root,
            identifier="figure-flight-envelope", role="localized_figure",
            relative_path="content/assets/fig-flight-envelope-zh.png", media_type="image/png",
            language="zh-CN", authority_rank=2, required=True, authoritative=False,
            approved=True, dimensions=(960, 480),
        ),
    ]
    selection_reasons = ["An approved layout, structured content, approved figure, and Word renderer are available."]
    manifest = {
        "schema_version": "1.0",
        "project_root": ".",
        "locked": True,
        "requested_mode": "publication_grade_docx",
        "selected_mode": "publication_grade_docx",
        "allow_downgrade": False,
        "capabilities": {"microsoft_word": True, "authoritative_renderer": "word-com", "renderer_available": True},
        "inputs": manifest_inputs,
        "selection_reasons": selection_reasons,
        "blocking_issues": [],
        "warnings": [],
    }
    project = {
        "schema_version": "1.0",
        "project_id": "easa-next-publication",
        "title": "EASA-NEXT virtual compliance report",
        "deliverable_id": "D-7.2",
        "languages": {"source": "en", "target": "zh-CN"},
        "requested_mode": "publication_grade_docx",
        "selected_mode": "publication_grade_docx",
        "allow_downgrade": False,
        "paths": {
            "content": "content/blocks.jsonl",
            "tables_dir": "content/tables",
            "formulas": "content/formulas.jsonl",
            "footnotes": "content/footnotes.jsonl",
            "toc": "content/toc.json",
            "figures": "content/figures.json",
            "layout": "layout_spec.json",
            "terminology": "inputs/approved_terms.csv",
            "source_manifest": "source_manifest.json",
        },
        "inputs": [project_input(item) for item in manifest_inputs],
        "capabilities": {
            "microsoft_word": True, "authoritative_renderer": "word-com",
            "renderer_available": True, "fonts_verified": True,
        },
        "document": {
            "title": "EASA-NEXT virtual compliance report",
            "subject": "English to Chinese publication dry-run",
            "creator": "",
            "language": "zh-CN",
        },
        "selection_reasons": selection_reasons,
        "blocking_issues": [],
    }
    write_json(project_root / "source_manifest.json", manifest)
    write_json(project_root / "project.json", project)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic, non-MODEL-SI EASA translation dry-run fixture."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_ROOT,
        help="Fixture root; defaults to the directory containing this script.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow replacement of known fixture files in an existing non-empty output directory.",
    )
    args = parser.parse_args()
    root = args.output_dir.resolve()
    if root != DEFAULT_ROOT.resolve() and root.exists() and any(root.iterdir()) and not args.overwrite:
        parser.error(f"--output-dir is not empty; pass --overwrite to replace known fixture files: {root}")
    seed_static_fixture(root)
    create_translation_only(root)
    create_publication_grade(root)
    print(f"Created virtual fixture inputs, manifests, and projects under {root}")


if __name__ == "__main__":
    main()
