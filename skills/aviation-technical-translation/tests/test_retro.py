"""Neutral regression cases; synthetic evidence is never real independent QA."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))
import workflow as w
import docx_preflight as dp
from common import load_layout_profile, resolve_layout_profile, schema_validation_errors
from check_invariants import check
from term_guard import DEFAULT_RULES, occurrences

def package(path,body):
    with zipfile.ZipFile(path,"x") as z:
        z.writestr("word/document.xml",
            f'<w:document xmlns:w="{dp.W}"><w:body>{body}</w:body></w:document>')

class Retro(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def proof(self,name,obj):
        p=self.root/name;p.write_text(json.dumps(obj),encoding="utf8")
        return {"path":str(p),"sha256":w.sha256_file(p)}
    def pair(self):
        ev=self.proof("observations.json",{"synthetic":True})
        criteria=self.proof("criteria.json",{"required":["readability","source_style"]})
        deps={k:w.digest(k) for k in w.DEPENDENCIES}
        r={"status":"PASS","complete":True,"kind":"visual_page","scope_ids":["page:2"],
           "dependencies":deps,"evidence":[ev],"artifact_sha256":w.digest("old pdf"),
           "review_contract":{"criteria":criteria,"aspects":["readability","source_style"],
                              "method":"READABLE_PAGES_AND_DETAIL","source_compared":True}}
        c=copy.deepcopy(r);c["artifact_sha256"]=w.digest("new pdf with other page changed")
        c["actual_render_comparison_pass"]=True
        compare=self.proof("comparison.json",{"baseline_target_sha256":r["artifact_sha256"],
            "candidate_target_sha256":c["artifact_sha256"],"scope_ids":["page:2"],
            "dimensions_equal":True,"raw_text_equal":True,"decoded_pixels_equal":True,
            "synthetic":True})
        c["comparison_record"]=compare;c["comparison_evidence"]=[compare]
        return r,c
    def test_valid_unchanged_page_can_reuse_after_other_page_changes(self):
        r,c=self.pair();self.assertTrue(w.cache({"record":r,"current":c})["reusable"])
    def test_equal_pixels_do_not_revalidate_revoked_style_pass(self):
        r,c=self.pair();c["invalidated_aspects"]=["source_style"]
        self.assertFalse(w.cache({"record":r,"current":c})["reusable"])
    def test_readability_does_not_cover_source_style(self):
        r,c=self.pair();r["review_contract"]["aspects"]=["readability"]
        self.assertFalse(w.cache({"record":r,"current":c})["reusable"])
    def test_contact_sheet_not_actual_detail(self):
        r,c=self.pair();r["review_contract"]["method"]="CONTACT_SHEET"
        self.assertFalse(w.cache({"record":r,"current":c})["reusable"])
    def test_stale_comparator_cannot_bind_new_artifact(self):
        r,c=self.pair();c["artifact_sha256"]=w.digest("another pdf")
        self.assertFalse(w.cache({"record":r,"current":c})["reusable"])
    def test_changed_criteria_reject_old_review(self):
        r,c=self.pair()
        c["review_contract"]["criteria"]=self.proof("new_criteria.json",{"new":"source widths"})
        self.assertFalse(w.cache({"record":r,"current":c})["reusable"])
    def test_malformed_contract_fails_closed(self):
        r,c=self.pair();c["review_contract"]=None
        with self.assertRaises(ValueError):w.cache({"record":r,"current":c})
        for value in (None, [], "not a reference"):
            r,c=self.pair();c["review_contract"]["criteria"]=value
            with self.assertRaises(ValueError):w.cache({"record":r,"current":c})
    def test_hidden_character_and_invalid_run_properties(self):
        p=self.root/"wrong.docx"
        package(p,'<w:p><w:r><w:t>校验\ufeff\ufeff结果</w:t><w:rPr><w:u w:val="single"/></w:rPr></w:r></w:p>')
        codes={x["code"] for x in dp.inspect_docx(p)["failures"]}
        self.assertEqual(codes,{"INTRAWORD_FEFF","RUN_PROPERTIES_POSITION"})
    def test_cross_run_hidden_character_and_story_coverage(self):
        p=self.root/"stories.docx"
        package(p,'<w:p><w:r><w:t>连续文本</w:t></w:r></w:p>')
        with zipfile.ZipFile(p,"a") as z:
            z.writestr("word/footnotes.xml",f'<w:footnotes xmlns:w="{dp.W}"><w:footnote w:id="1"><w:p><w:r><w:t>术语</w:t></w:r><w:r><w:t>\ufeff</w:t></w:r><w:r><w:t>正文</w:t></w:r></w:p></w:footnote></w:footnotes>')
        self.assertEqual(dp.inspect_docx(p)["failures"][0]["part"],"word/footnotes.xml")
    def test_valid_raw_text_and_real_run_properties(self):
        p=self.root/"right.docx"
        package(p,'<w:p><w:pPr/><w:r><w:rPr><w:u w:val="single"/></w:rPr><w:t>校验结果 A\u00a0B x_i ∑ 👩\u200d🔬</w:t></w:r></w:p>')
        self.assertEqual(dp.inspect_docx(p)["status"],"PASS")
    def test_preflight_refuses_overwrite(self):
        p=self.root/"right.docx";package(p,'<w:p/>');report=self.root/"report.json"
        report.write_text("keep")
        cmd=[sys.executable,"-B",str(SCRIPTS/"docx_preflight.py"),"--docx",str(p),"--report",str(report)]
        r=subprocess.run(cmd,capture_output=True)
        self.assertEqual(r.returncode,2);self.assertEqual(report.read_text(),"keep")
    def test_exact_code_and_bibliography_objects(self):
        for source in ["if speed < limit: hold()", "@report{neutral, year={2030}}"]:
            s={"source_units":[{"id":"x","text":source,"preserve_exact":True,"source_evidence":"original neutral fixture"}],
               "target_units":[{"id":"x","text":source}]}
            self.assertEqual(check(s)["mechanical_status"],"PASS")
            s["target_units"][0]["text"]="若速度小于上限则保持"
            self.assertEqual(check(s)["mechanical_status"],"FAIL")
    def test_integrity_is_context_review_not_global_replacement(self):
        rule=next(r for r in DEFAULT_RULES if r["source"]=="integrity")
        blocks=[{"id":"security","source_text":"Verify data integrity before transfer.","target_text":"传输前验证数据完整性。"},
                {"id":"system","source_text":"The monitor checks system integrity.","target_text":"监视器检查系统完好性。"}]
        hits=occurrences(blocks,dict(rule,case_sensitive=False))
        self.assertEqual(len(hits),2)
        self.assertTrue(all(x["required_action"]=="CONTEXT_REVIEW" and not x["forbidden_target_hits"] for x in hits))
    def test_exact_missing_text_cannot_pass_as_two_nulls(self):
        s={"source_units":[{"id":"x","preserve_exact":True,"source_evidence":"original test"}],
           "target_units":[{"id":"x"}]}
        self.assertEqual(check(s)["mechanical_status"],"FAIL")
        for value in (None,0,False,[]):
            for row in (s["source_units"][0],s["target_units"][0]):row["text"]=value
            self.assertEqual(check(s)["mechanical_status"],"FAIL")
        for row in (s["source_units"][0],s["target_units"][0]):row["text"]=""
        self.assertEqual(check(s)["mechanical_status"],"PASS")
        s["target_units"][0]["text"]=None
        self.assertEqual(check(s)["mechanical_status"],"FAIL")
    def test_requested_routes_have_available_references(self):
        for task in ("translate","repair","qa","resume"):
            for fmt in ("pdf","docx","text"):
                plan=w.plan({"task":task,"output_format":fmt,"document_kind":"paper"})
                self.assertFalse(plan["completed"])
                for ref in plan["references"]:
                    self.assertTrue((SCRIPTS.parent/"references"/ref).is_file(),ref)
                self.assertEqual(plan["word_required"],fmt=="docx")
                if task=="qa":self.assertIn("qa_policy.md",plan["references"])
        self.assertEqual(w.plan({"task":"resume","output_format":"docx","document_kind":"manual"})["phase"],"CURRENT_STATE_FIRST")
        self.assertFalse(w.plan({"task":"excerpt"})["independent_qa_required"])
    def test_pdf_first_delivery_checks_source_layout_at_pilot_and_final(self):
        for kind in ("paper", "manual", "other"):
            request = {"task": "translate", "output_format": "pdf", "document_kind": kind}
            plan = w.plan(request)
            self.assertEqual(plan["next_action"], "INSPECT_SOURCE_PAGE_LAYOUT")
            self.assertEqual(plan["required_checks"], [
                "inspect_source_page_layout", "compare_rendered_pilot_to_source_layout",
                "calibrate_body_leading_and_object_gaps_on_pilot",
                "compare_final_render_to_source_layout", "review_rendered_body_leading_and_object_gaps",
                "verify_requested_type_on_render", "review_context_terms_and_figure_labels",
                *(["verify_ordered_batches_and_boundary_context"] if kind == "manual" else []),
            ])
            self.assertIn("presentation_review.md", plan["references"])
            resumed = w.plan(dict(request, task="resume"))
            self.assertEqual(resumed["next_action"], "VERIFY_CURRENT_ARTIFACTS")
            self.assertIn("compare_final_render_to_source_layout", resumed["required_checks"])
            for fmt in ("text", "docx"):
                other = w.plan(dict(request, output_format=fmt))
                self.assertNotIn("compare_rendered_pilot_to_source_layout", other["required_checks"])

    def test_profile_does_not_force_old_paper_size_or_underline(self):
        p=load_layout_profile("personal_paper_review")
        self.assertNotIn("size_pt",p["style_defaults"]["body"])
        r=resolve_layout_profile({"profile_id":"personal_paper_review","styles":{"Body":{"size_pt":10.5}}})
        self.assertEqual(r["styles"]["Body"]["size_pt"],10.5)
        self.assertEqual(r["styles"]["Body"]["font_latin"],"Times New Roman")
        for path in (SCRIPTS.parent/"schemas").glob("*.json"):
            schema=json.loads(path.read_text(encoding="utf8"))
            prop=schema.get("properties",{}).get("layout_profile_id")
            if prop and "enum" in prop:self.assertIn("personal_paper_review",prop["enum"])
        self.assertFalse(schema_validation_errors(p,SCRIPTS.parent/"schemas/layout_profile.schema.json"))

if __name__=="__main__":unittest.main(verbosity=2)
