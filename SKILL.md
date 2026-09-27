---
name: aviation-translation-core
description: Review English-to-Chinese technical translations using source fidelity rules, contextual terminology, mechanical evidence checks and a real independent QA handoff. Use for translation and review; this public pre-release source edition does not construct publication DOCX or automatically translate through an API.
metadata:
  version: "0.1.1-r1-candidate"
---

# Technical translation core

This is a public pre-release source edition. This repository checkout is not itself an installed Skill, and no tagged release has been published yet. Preserve the requested scope. For an excerpt, apply [translation rules](references/translation_policy.md) and [terminology rules](references/terminology_disambiguation.md); do not create a project merely to answer a short question.

For a structured review, establish independent source evidence before reading the candidate's proposed expected values. Use [the input contract](docs/input_contract.md). Run `scripts/compare_source.py` to locate source mappings in a supported PDF, `scripts/check_invariants.py` for numeric/structural checks, and `scripts/term_guard.py` for terminology contexts. Commands are in [quickstart](docs/quickstart.md). They are not translators or semantic assessors.

Use [QA handoff](references/dual_agent_workflow.md), [evidence bindings](references/evidence_contract.md), and [QA policy](references/qa_policy.md). `scripts/workflow.py` exposes snapshot, verify-snapshot, route, cache, coverage and scope gates. Keep explicit sample scope separate from full document review. Unknown or unsupported layers block completion. Never fill an absent-layer declaration solely from empty extraction.

The host must perform any real independent review. This candidate has no trusted host-event adapter: `INDEPENDENT_QA_UNAVAILABLE` and `NOT_RUN` are honest states. A second JSON, a different reviewer name or `SYNTHETIC_TEST_ONLY` fixture cannot establish real QA. Human approval and release remain false in program output; actual human decisions and publication authority are separately required.

Source anomalies require a scoped decision, not silent correction. Preserve original materials; use a new private run directory. Shareable reports contain counts and codes only. Original paragraphs and generated PDFs are private run data. Do not upload them or include them in a review package.
