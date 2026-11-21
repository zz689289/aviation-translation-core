"""Measure selected same-column baselines and visible gaps on a rendered PDF."""
import argparse
import math
import sys
from collections import Counter
from pathlib import Path

from common import atomic_write_json, ensure_distinct_paths, load_json, require_package, sha256_file

SCALE = 4
INK_THRESHOLD = 200
INK_MASK = bytes(int(value < INK_THRESHOLD) for value in range(256))


def numbers(values, count):
    if (not isinstance(values, list) or len(values) != count or
            not all(type(n) in (int, float) and math.isfinite(n) for n in values)):
        raise ValueError(f'Expected {count} finite coordinates or limits')
    return values


def rectangle(page, values, fitz):
    rect = fitz.Rect(numbers(values, 4))
    if rect.is_empty or not page.rect.contains(rect):
        raise ValueError('Measurement box is empty or outside the visible page')
    return rect


def baselines(page, rect, fitz):
    flags = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
    blocks = page.get_text('dict', flags=flags, clip=rect + (0, -24, 0, 24))['blocks']
    spans = []
    for block in blocks:
        for line in block.get('lines', []):
            if abs(line['dir'][0] - 1) > 0.001 or abs(line['dir'][1]) > 0.001:
                continue
            for span in line['spans']:
                y = span['origin'][1]
                text = span['text'].strip()
                if text and rect.y0 <= y < rect.y1 and span.get('alpha', 255) > 0:
                    spans.append((round(span['size'], 1), y, len(text)))
    if not spans:
        return []
    weights = Counter()
    for size, y, weight in spans:
        weights[size] += weight
    main_size = weights.most_common(1)[0][0]
    rows = []
    for y in sorted(y for size, y, _ in spans if abs(size - main_size) <= max(0.15, main_size * 0.04)):
        if not rows or y - rows[-1] > 0.4:
            rows.append(y)
    return rows


def ink_edges(page, rect, fitz):
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), clip=rect,
                          colorspace=fitz.csGRAY, alpha=False, annots=False)
    if not pix.width or not pix.height:
        return None
    ink = pix.samples.translate(INK_MASK)
    first, last = ink.find(b'\x01'), ink.rfind(b'\x01')
    if first < 0:
        return None
    return (pix.y + first // pix.stride) / SCALE, (pix.y + last // pix.stride + 1) / SCALE


def measure(document, check, fitz):
    low, high = numbers(check['range_pt'], 2)
    if not 0 <= low <= high or check['kind'] not in ('leading', 'gap'):
        raise ValueError('Invalid range_pt or kind')
    number = check['page']
    if type(number) is not int or not 1 <= number <= len(document):
        raise ValueError('Page number is outside the PDF')
    page = document[number - 1]
    if page.rotation:
        return {'status': 'UNMEASURED', 'reason': 'Inspect the rotated page visually'}
    if check['kind'] == 'leading':
        rows = baselines(page, rectangle(page, check['rect'], fitz), fitz)
        if len(rows) < 2:
            return {'status': 'UNMEASURED', 'reason': 'Fewer than two extractable main-text baselines'}
        values = [b - a for a, b in zip(rows, rows[1:])]
        evidence = {'baselines_pt': [round(y, 3) for y in rows]}
    else:
        before = rectangle(page, check['before'], fitz)
        after = rectangle(page, check['after'], fitz)
        if before.y1 > after.y0:
            return {'status': 'UNMEASURED', 'reason': 'Overlapping crops require visual inspection'}
        prev = ink_edges(page, before, fitz)
        following = ink_edges(page, after, fitz)
        if prev is None or following is None:
            return {'status': 'UNMEASURED', 'reason': 'One or both crops have no detectable ink'}
        if prev[1] >= before.y1 or following[0] <= after.y0:
            return {'status': 'UNMEASURED', 'reason': 'Ink meets a facing crop edge; check the crop or inspect visually'}
        between = fitz.Rect(min(before.x0, after.x0), before.y1, max(before.x1, after.x1), after.y0)
        if not between.is_empty and ink_edges(page, between, fitz) is not None:
            return {'status': 'UNMEASURED', 'reason': 'Intervening ink; verify these objects are adjacent'}
        values = [following[0] - prev[1]]
        evidence = {'previous_ink_bottom_pt': prev[1], 'next_ink_top_pt': following[0]}
    values = [round(value, 3) for value in values]
    return {**evidence, 'measured_pt': values,
            'status': 'PASS' if all(low <= value <= high for value in values) else 'FAIL'}


def report(pdf, spec_path):
    fitz = require_package('pymupdf')
    checks = load_json(spec_path)['checks']
    if not isinstance(checks, list) or not checks:
        raise ValueError('Supply a nonempty list of checks')
    ids = [check['id'] for check in checks]
    if not all(isinstance(i, str) and i.strip() for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Each check needs a unique nonempty id')
    with fitz.open(pdf) as document:
        if not document.is_pdf:
            raise ValueError('Expected PDF')
        results = [{**check, **measure(document, check, fitz)} for check in checks]
    return {'pdf_sha256': sha256_file(pdf), 'spec_sha256': sha256_file(spec_path),
            'scope': 'Listed samples only', 'gray_ink_below': INK_THRESHOLD, 'pixels_per_pt': SCALE,
            'status': 'PASS' if all(r['status'] == 'PASS' for r in results) else 'REVIEW', 'checks': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        ensure_distinct_paths({'pdf': args.pdf, 'spec': args.spec, 'output': args.output})
        if args.output.suffix.lower() != '.json' or args.output.exists():
            raise ValueError('Supply a new output JSON path')
        outcome = report(args.pdf, args.spec)
        atomic_write_json(args.output, outcome)
        print(outcome['status'], args.output)
        return 0 if outcome['status'] == 'PASS' else 1
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f'INVALID: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
