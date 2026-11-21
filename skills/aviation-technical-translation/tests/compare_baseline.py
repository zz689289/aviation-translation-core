"""Compare deterministic guards in two skill directories, with original fixtures.

Each version is loaded in an isolated process. All evidence here is synthetic;
these probes do not establish real visual or independent QA.
"""
import argparse
import copy
import json
import subprocess
import sys
from pathlib import Path

def probe(skill, out):
    out.mkdir(parents=True,exist_ok=False)
    sys.path.insert(0,str(skill/"scripts"))
    import workflow as w
    from check_invariants import check
    from term_guard import DEFAULT_RULES
    from common import load_layout_profile, schema_validation_errors
    def evidence(name,data):
        p=out/name;p.write_text(json.dumps(data),encoding="utf8")
        return {"path":str(p),"sha256":w.sha256_file(p)}
    criteria=evidence("criteria.json",{"readable":True,"compare_source":True})
    obs=evidence("observation.json",{"synthetic":True})
    old={"kind":"visual_page","status":"PASS","complete":True,"scope_ids":["page:2"],
         "dependencies":{k:w.digest(k) for k in w.DEPENDENCIES},
         "evidence":[obs],"artifact_sha256":w.digest("old"),
         "review_contract":{"criteria":criteria,"aspects":["readability","source_style"],
          "method":"READABLE_PAGES_AND_DETAIL","source_compared":True}}
    current=copy.deepcopy(old);current["artifact_sha256"]=w.digest("new")
    cmp=evidence("comparison.json",{"baseline_target_sha256":old["artifact_sha256"],
        "candidate_target_sha256":current["artifact_sha256"],"scope_ids":["page:2"],
        "dimensions_equal":True,"raw_text_equal":True,"decoded_pixels_equal":True,"synthetic":True})
    current.update(actual_render_comparison_pass=True,comparison_evidence=[cmp],comparison_record=cmp)
    rows=[]
    def cache_case(name,expected,mutate):
        a,b=copy.deepcopy(old),copy.deepcopy(current);mutate(a,b)
        try:r=w.cache({"record":a,"current":b});got=r["reusable"];details=r["invalidation_reasons"]
        except (ValueError,TypeError,KeyError) as exc:got=False;details=[type(exc).__name__]
        rows.append(dict(id=name,expected=expected,actual=got,passed=got==expected,details=details))
    cache_case("valid_unchanged_page_reuse",True,lambda a,b:None)
    cache_case("style_review_invalidated",False,lambda a,b:b.update(invalidated_aspects=["source_style"]))
    cache_case("contact_sheet_only",False,lambda a,b:a["review_contract"].update(method="CONTACT_SHEET"))
    cache_case("readability_not_source_style",False,lambda a,b:a["review_contract"].update(aspects=["readability"]))
    cache_case("source_not_compared",False,lambda a,b:a["review_contract"].update(source_compared=False))
    cache_case("stale_comparison_binding",False,lambda a,b:b.update(artifact_sha256=w.digest("third")))
    cache_case("revoked_review",False,lambda a,b:a.update(revoked=True))
    def changed(a,b):
        b["review_contract"]["criteria"]=evidence("new-criteria.json",{"different":True})
    cache_case("changed_criteria",False,changed)
    for bad in (False,True):
        r=check({"source_units":[{"id":"code","text":"if ready: keep()","preserve_exact":True,
             "source_evidence":"original neutral test"}],
            "target_units":[{"id":"code","text":"若就绪则保持" if bad else "if ready: keep()"}]})
        got=r["mechanical_status"]=="PASS";expected=not bad
        rows.append(dict(id="code_changed" if bad else "code_preserved",expected=expected,actual=got,
                         passed=got==expected,details=r["failures"]))
    r=check({"source_units":[{"id":"code","preserve_exact":True,"source_evidence":"original neutral test"}],
             "target_units":[{"id":"code"}]})
    got=r["mechanical_status"]=="PASS"
    rows.append(dict(id="exact_text_missing",expected=False,actual=got,passed=not got,details=r["failures"]))
    hit=any(r["source"]=="integrity" for r in DEFAULT_RULES)
    rows.append(dict(id="integrity_context_review_available",expected=True,actual=hit,passed=hit))
    # Test the existing profile's real schema validation, not merely the new name.
    existing=load_layout_profile("personal_zh_review")
    errors=schema_validation_errors(existing,skill/"schemas/layout_profile.schema.json")
    rows.append(dict(id="existing_personal_profile_schema",expected=True,actual=not errors,passed=not errors,details=errors))
    (out/"result.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf8")
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline",type=Path);p.add_argument("--candidate",type=Path)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--probe",type=Path)
    a=p.parse_args()
    if a.probe:probe(a.probe,a.output);return
    if not a.baseline or not a.candidate:p.error("Both --baseline and --candidate required")
    a.output.mkdir(parents=True,exist_ok=False)
    versions={}
    for name,path in [("baseline",a.baseline),("candidate",a.candidate)]:
        subprocess.run([sys.executable,"-B",str(Path(__file__).resolve()),"--probe",str(path),
                        "--output",str(a.output/name)],check=True)
        versions[name]=json.loads((a.output/name/"result.json").read_text(encoding="utf8"))
    result={"synthetic_guard_probes":True,"versions":versions,
      "boundary":"Only declared data and deterministic checks are tested; no semantic/visual acceptance."}
    (a.output/"comparison.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({k:{"passed":sum(x["passed"] for x in v),"total":len(v)} for k,v in versions.items()}))
if __name__=="__main__":main()
