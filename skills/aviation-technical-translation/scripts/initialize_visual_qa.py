"""Create an explicit UNREVIEWED page checklist and optional contact sheets.

Usage:
    python initialize_visual_qa.py --pages-dir render/pages --output qa_pages.json \
        --contact-dir contact_sheets --columns 2 --rows 2 --thumb-width 700

No page is automatically marked PASS. Reviewers must update each page record
with evidence after examining the full-size page.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from common import atomic_write_json, ensure_distinct_paths, require_package, require_suffix, sha256_file


def make_contacts(pages: list[Path], output_dir: Path, columns: int, rows: int, thumb_width: int) -> list[str]:
    pil = require_package("PIL.Image", "Pillow")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty contact-sheet directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    per_sheet = columns * rows
    names = []
    for sheet_index in range(math.ceil(len(pages) / per_sheet)):
        subset = pages[sheet_index * per_sheet:(sheet_index + 1) * per_sheet]
        thumbs = []
        for page in subset:
            with pil.open(page) as source:
                height = round(source.height * thumb_width / source.width)
                thumbs.append(source.convert("RGB").resize((thumb_width, height)))
        cell_height = max(image.height for image in thumbs)
        canvas = pil.new("RGB", (columns * thumb_width, rows * cell_height), "white")
        for index, image in enumerate(thumbs):
            canvas.paste(image, ((index % columns) * thumb_width, (index // columns) * cell_height))
        target = output_dir / f"contact_{sheet_index + 1:03d}.jpg"
        canvas.save(target, quality=88)
        names.append(target.name)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contact-dir", type=Path)
    parser.add_argument("--columns", type=int, default=2)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--thumb-width", type=int, default=700)
    args = parser.parse_args()
    pages_dir = args.pages_dir.resolve()
    output_path = args.output.resolve()
    pages = sorted(list(pages_dir.glob("page_*.png")) + list(pages_dir.glob("page-*.png")))
    if not pages:
        raise SystemExit(f"No page PNGs found in {pages_dir}")
    try:
        require_suffix(output_path, ".json", "--output")
        ensure_distinct_paths({"visual QA report": output_path, **{f"page {index}": page for index, page in enumerate(pages, 1)}})
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    records = [
        {
            "page": index, "file": page.name, "sha256": sha256_file(page), "status": "UNREVIEWED",
            "reviewer": "", "reviewed_at": "", "zoom": [], "findings": [], "evidence": [],
        }
        for index, page in enumerate(pages, 1)
    ]
    contacts = make_contacts(pages, args.contact_dir.resolve(), args.columns, args.rows, args.thumb_width) if args.contact_dir else []
    report = {
        "schema_version": "1.0", "page_count": len(records), "allowed_status": ["UNREVIEWED", "PASS", "REVIEW", "FAIL"],
        "acceptance_rule": "All pages reviewed; FAIL=0; every REVIEW adjudicated.", "pages": records, "contact_sheets": contacts,
    }
    atomic_write_json(output_path, report)
    print(f"Initialized {len(records)} UNREVIEWED pages -> {output_path}")


if __name__ == "__main__":
    main()
