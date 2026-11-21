"""Regression tests for role-specific PDF spacing samples."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import pdf_spacing

try:
    import pymupdf as fitz
except ImportError:
    fitz = None


@unittest.skipUnless(fitz, 'These rendered-page tests require PyMuPDF')
class PdfSpacingTest(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=220, height=200)
        for y in (29, 41, 53, 71):
            self.page.insert_text((12, y), 'Sample body', fontsize=9)
        self.page.insert_text((68, 37), '2', fontsize=5)
        self.page.insert_text((142, 34), 'Other column', fontsize=9)
        self.page.draw_rect(fitz.Rect(10, 85, 82, 96), color=None, fill=(0, 0, 0))
        self.page.draw_rect(fitz.Rect(10, 108, 82, 134), color=None, fill=(0, 0, 0))

    def check(self, kind, **spec):
        return pdf_spacing.measure(self.document, {'page': 1, 'kind': kind, 'range_pt': [11.8, 12.2], **spec}, fitz)

    def test_actual_baselines_across_roles_and_columns(self):
        good = self.check('leading', rect=[8, 25, 100, 59])
        self.assertEqual((good['status'], good['measured_pt']), ('PASS', [12, 12]))
        bad = self.check('leading', rect=[8, 25, 100, 76])
        self.assertEqual((bad['status'], bad['measured_pt']), ('FAIL', [12, 12, 18]))
        self.assertEqual(self.check('leading', rect=[8, 25, 100, 35])['status'], 'UNMEASURED')

    def test_graphic_ink_gap_with_both_limits(self):
        region = {'before': [5, 83, 90, 99], 'after': [5, 104, 90, 140]}
        good = self.check('gap', **region)
        self.assertEqual((good['status'], good['measured_pt']), ('PASS', [12]))
        for bounds in ([7, 11], [13, 16]):
            self.assertEqual(self.check('gap', **region, range_pt=bounds)['status'], 'FAIL')
        self.assertEqual(self.check('gap', **dict(region, before=[5, 83, 90, 95]))['status'], 'UNMEASURED')
        self.assertEqual(self.check('gap', **dict(region, after=[5, 99, 90, 103]))['status'], 'UNMEASURED')
        self.assertEqual(self.check('gap', **dict(region, after=[5, 90, 90, 140]))['status'], 'UNMEASURED')

    def test_intervening_content_is_not_clearance(self):
        self.page.draw_line((30, 102), (60, 102))
        finding = self.check('gap', before=[5, 83, 90, 99], after=[5, 104, 90, 140])
        self.assertEqual(finding['status'], 'UNMEASURED')

    def test_report_does_not_pass_without_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            pdf, spec = Path(tmp) / 'sample.pdf', Path(tmp) / 'spec.json'
            self.document.save(pdf)
            check = {'page': 1, 'id': 'p1-left', 'kind': 'leading', 'rect': [8, 25, 100, 35], 'range_pt': [9, 12]}
            spec.write_text(json.dumps({'checks': [check]}), encoding='utf-8')
            result = pdf_spacing.report(pdf, spec)
            self.assertEqual((result['status'], result['checks'][0]['status']), ('REVIEW', 'UNMEASURED'))
            self.assertEqual(len(result['pdf_sha256']), 64)
            for checks in ([], [check, check], [dict(check, rect=[10, 5, -1, 8])], [dict(check, range_pt=[30, 15])]):
                spec.write_text(json.dumps({'checks': checks}), encoding='utf-8')
                with self.assertRaises(ValueError):
                    pdf_spacing.report(pdf, spec)
