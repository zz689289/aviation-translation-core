# QA: correctness, coverage, independence

## Non-substitutable evidence

Require at least one full independent source-to-output audit across ordinary text, table cells, displayed/inline formulas, captions, image labels/arrows/units, every real footnote occurrence, references/front matter and branding/fields. QA first inventories English pages independently; reconcile with the executor extraction only afterward. An omitted source formula cannot disappear from the denominator because the executor inventory is empty. Absence of a layer requires source-review evidence, not a zero extracted count. Coverage can accumulate in batches, never extrapolate a sample to PASS.

For every compared unit preserve English context, target, locator, outcome and specific reasoning. Check omission/addition, completion, identifiers, numbers, units/case, normative force, negation, conditions, causality/scope and canonical terms in their actual context. Null/pending work is execution status, not semantic uncertainty. Assets require label/arrow relation review as well as hash integrity. True repeated footnotes are distinct occurrences with independent anchor/body bindings; identical body strings are legal.

Automation handles hashes, coverage set reconciliation, source coordinates, field and TOC cache values, numbering definitions/overrides, actual PDF geometry and decoded pixels. Model QA handles meaning and actual visual judgments. A populated checks array, XML property, asset hash, nonempty target or double-render match alone cannot establish semantic/visual PASS. Test relevant negative AND correct controls before trusting a changed checker.

## Review and repair

Use the single source-first independent QA and repair loop in dual_agent_workflow.md. Findings include object/page, English/output evidence, failure category, root cause, affected scope, recommended repair and authority requirement. QA writes evidence only. Source-clear authorized fixes go to executor backlog, not human approval per occurrence. Risk and unresolved-decision status are separate: a severe but unambiguous missing equation is automatically repairable within authorized source-faithful reconstruction; a guessed source equation correction is not.

## Change-aware reuse

Use evidence_contract.md and workflow.py. Recheck changed meaning plus context/term/reference dependents; changed formatting plus actual changed and adjacent pages; global font/margin/numbering/section/render changes across the affected document. Verify unchanged-page reuse through actual render content/geometry/pixel comparison and applicable source/target/assets/style/checker/environment keys. Cache only complete PASS records for their declared scope; never cache failed, partial, unreviewed or mismatched-version work as PASS. Don't retrospectively expand a page allowlist to hide a defect. Where the user permits reflow, source/body equivalence and review follow the new pagination; don't hard-fail an authorized page-count change just because the old version differed.

## Visual gate

Cover every final actual page at readable full-page scale; inspect dense figures/formulas/tables/notes at enlarged scale. Contact sheets alone are insufficient. Record source-style comparison separately from readability, including exact emphasis boundaries, effective inherited/direct formatting, list anchors, gaps, line weights and original text integrity. A newly demonstrated defect revokes that aspect of old PASS even if every pixel is unchanged; see the visual review_contract in evidence_contract.md. Verify semantic roles and emphasis, numbering alignment/tabs, continuation headers at actual page breaks, no orphan title, table merges, captions paired with images, footnotes/anchors, source-dependent 'next page' relation, colours, intact brand assets, complete PAGE/NUMPAGES and no clipping/overlap. Read styles AND direct run formatting AND the PDF. Reuse unchanged pages only as above, listing the origin evidence. The same error in two renders still fails.

## Acceptance

Source/semantic completeness, all applicable deterministic/package checks, actual-page visual coverage and exact-artifact human decisions must pass. DOCX or a Word-authoritative pipeline requires final stable independent dual Word exports. Direct PDF uses its actual production renderer and applicable stability evidence as defined in pdf_workflow.md; it does not acquire a Word requirement. Plain text has no page-render gate. Keep export capability, execution completion, QA, human proofreading and formal publication in separate fields. A new user acceptance can append the disposition 'accept current text this edition'; this does not approve the suggestion or populate a glossary. Preserve historical failure states with artifact scope. New unknown visual differences pause their acceptance even when old micropositions were human-approved. No auto-tolerance, invented review, unearned assessor tier or automatic formal release.
