"""Read-only PDF layout, text extraction, and term-location utility.

Examples:
    python pdf_probe.py info source.pdf --output pdf_info.json
    python pdf_probe.py extract source.pdf --pages 1,3-5 --output pages.json
    python pdf_probe.py layout source.pdf --pages 1,3 --output source-lines.json
    python pdf_probe.py find source.pdf --term Validation --term "test data" --output hits.json
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import atomic_write_json, ensure_distinct_paths, require_package, require_suffix, sha256_file


def parse_pages(value: str, page_count: int) -> list[int]:
    pages: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            if start > end:
                raise ValueError(f"Invalid descending page range: {part}")
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    if not pages or min(pages) < 1 or max(pages) > page_count:
        raise ValueError(f"Page selection must be within 1..{page_count}: {value}")
    return sorted(pages)


def layout_report(pdf: Path, pages: str) -> dict:
    """Observe text geometry without inferring columns or the absence of visual objects."""
    pymupdf = require_package("pymupdf", "PyMuPDF")
    observations = []
    with pymupdf.open(pdf) as document:
        for number in parse_pages(pages, len(document)):
            page = document[number - 1]
            flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
            lines = []
            for block in page.get_text("dict", flags=flags)["blocks"]:
                for line in block.get("lines", []):
                    lines.append({
                        "text": "".join(span["text"] for span in line["spans"]),
                        "bounds_pt": line["bbox"],
                        "direction": line["dir"],
                    })
            observations.append({
                "page": number, "rotation_degrees": page.rotation,
                "width_pt": page.cropbox.width, "height_pt": page.cropbox.height,
                "lines": lines,
            })
    return {
        "sha256": sha256_file(pdf), "pages": observations,
        "coordinates": "Unrotated visible page, points from top left, y increases downward.",
        "scope": "Extractable text lines only. Inspect the rendered page for visual structure.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("info", "extract", "find", "layout"):
        child = subparsers.add_parser(command)
        child.add_argument("pdf", type=Path)
        child.add_argument("--output", type=Path, required=True)
        if command in ("extract", "layout"):
            child.add_argument("--pages", required=True)
        if command == "find":
            child.add_argument("--term", action="append", required=True)
    args = parser.parse_args()

    pdf = args.pdf.resolve()
    output = args.output.resolve()
    try:
        require_suffix(pdf, ".pdf", "PDF input")
        require_suffix(output, ".json", "--output")
        ensure_distinct_paths({"PDF input": pdf, "JSON output": output})
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if args.command == "layout":
        atomic_write_json(output, layout_report(pdf, args.pages))
        print(f"layout: {pdf.name} -> {output}")
        return
    pypdf = require_package("pypdf")
    reader = pypdf.PdfReader(str(pdf))
    if args.command == "info":
        result = {
            "schema_version": "1.0", "pdf": pdf.name, "sha256": sha256_file(pdf), "page_count": len(reader.pages),
            "pages": [
                {
                    "page": index, "width_pt": float(page.mediabox.width), "height_pt": float(page.mediabox.height),
                    "rotation": int(page.rotation or 0), "text_characters": len(page.extract_text() or ""),
                }
                for index, page in enumerate(reader.pages, 1)
            ],
        }
    elif args.command == "extract":
        selected = parse_pages(args.pages, len(reader.pages))
        result = {"schema_version": "1.0", "pdf": pdf.name, "pages": [{"page": number, "text": reader.pages[number - 1].extract_text() or ""} for number in selected]}
    else:
        hits = []
        for page_number, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            for term in args.term:
                for match in re.finditer(re.escape(term), text, re.IGNORECASE):
                    start = max(0, match.start() - 80)
                    end = min(len(text), match.end() + 80)
                    hits.append({"term": term, "page": page_number, "context": text[start:end].replace("\n", " ")})
        result = {"schema_version": "1.0", "pdf": pdf.name, "terms": args.term, "hit_count": len(hits), "hits": hits}
    atomic_write_json(output, result)
    print(f"{args.command}: {pdf.name} -> {output}")


if __name__ == "__main__":
    main()
