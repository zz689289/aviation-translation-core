# Translation policy

Fidelity and authority rules apply to all translations in scope. Structured manifests, overlays, queues, and whole-document acceptance checks apply when that structured deliverable or review is requested. For an excerpt, preserve its source context and report unresolved decisions inline. Layout profile does not weaken these rules; case-specific pages, counts, and corrections are not defaults.

## Authority and provenance

Use this order unless an approved project manifest states a stricter rule:

1. The English original controls technical meaning, structure, numbering, tables, formulas, citations, and layout intent.
2. The approved terminology source controls the Chinese form of technical terms when it does not contradict the source meaning.
3. A Chinese machine translation or earlier draft is a sentence-level aid, never independent authority.
4. Approved localized figures control the translated asset only; the English source still controls placement and meaning.

Record each input's role, relative path, SHA-256, size, page or pixel count, authority rank, and approval state. Do not let old outputs be rediscovered as inputs.

## Fidelity rules

- Preserve conditions, exceptions, causality, scope, negation, comparisons, quantities, units, tolerances, equation symbols, identifiers, standards, issue/revision designators, and references.
- Preserve normative force: map `shall/must`, `should`, `may`, `can`, and recommendations deliberately. Do not add words such as “必须” to a descriptive sentence.
- Do not delete repetition merely because it seems redundant.
- Do not add technical conclusions absent from the source.
- When the source appears technically questionable, retain the faithful translation and create a `SOURCE_QUIRK` record. Change it only after an authorized decision.
- Keep abbreviations aligned with the source. Introduce a Chinese term and abbreviation consistently; do not expand an abbreviation differently in different sections.
- Preserve the distinction between document edition/issue, problem/issue, certification, qualification, verification, validation, and confirmation.

算法的题目、标识符、步骤/注释和数学符号应分别记录语言策略。默认叙述性步骤的翻译规则不覆盖本项目明确的保留原语言决定；题目译中文也不自动授权改写算法内部。见[presentation_review.md](presentation_review.md)。

Cross-page qualifications, repeated numbered families, entity expansions, and the relation between the subject and reference of verification must be checked against local definitions. See [long_translation.md](long_translation.md) for the scoped decision checker, joined groups and ordered checkpoints.

## Structured document translation workflow

1. Segment the source into immutable, ordered content blocks.
2. Align the draft Chinese to those blocks. A blank draft does not authorize omission.
3. Apply the glossary with longest-phrase-first matching.
4. Classify ambiguous terms by context before choosing a translation.
5. Translate tables cell by cell and equations symbol by symbol; do not rely on paragraph extraction for them.
6. Run dedicated scans for numbers, units, identifiers, standard numbers, issue/revision labels, modal verbs, and negation.
7. Record unresolved terminology as `TERMINOLOGY_REVIEW` rather than guessing.
8. Apply approved corrections through a versioned overlay. Verify the expected current value before each replacement.

## Cost-aware risk routing

Classify the smallest reviewable decision unit, not an entire page, using the highest applicable risk signal:

- `GREEN`: deterministic/mechanical and closed only by an observable scripted PASS;
- `AMBER`: an applicable rule exists, but sentence/object context controls the result;
- `RED`: a wrong choice may alter regulatory meaning, certification evidence, normative strength, official terminology, numerical/formula meaning, or the faithful handling of a source conflict.

Use `economy`, `balanced`, or `maximum_quality` only to choose the review tier described in [model_escalation_policy.md](model_escalation_policy.md). Cost never changes source authority or acceptance criteria. An AMBER item without an applicable rule becomes RED. Missing/unknown signals default to RED. A low-cost executor must suppress rather than guess a low-confidence RED proposal and place the item in the structured escalation queue.

Automated detection and technical adjudication remain separate. For example, detecting that a formula and paragraph contain different values may be GREEN; deciding which source meaning governs is RED.

## Translation-only deliverable

Translation-only mode may produce a reviewed bilingual content map, terminology report, decision log, and a clean reading DOCX. It does not claim source-faithful pagination or publication layout unless the publication workflow and its gates are completed.

## Structured deliverable source comparison

Compare at two levels:

- Structure: full heading sequence, lists, tables, figures, formulas, footnotes, requirement blocks, references, annex boundaries, front matter, and back matter.
- Content: block-by-block English/Chinese fidelity plus dedicated comparison of numbers, units, standards, modal force, table cells, equations, and captions.

Reports state checked/total coverage for the requested scope. A requested sample review may finish with its sample coverage and limits; it does not establish whole-document acceptance.
