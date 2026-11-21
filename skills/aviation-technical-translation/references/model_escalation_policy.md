# Cost-aware model escalation policy

## Workflow 1.2 boundary (default for new work)

Use `workflow.py route` (or `build_escalation_queue.py --workflow`) for the current executor/one-QA workflow. Pending work, routine source-clear repair and true human decisions are distinct collections. This regular QA is explicitly authorized by the Skill and is not an additional higher-tier assessor; it uses Sol 6.2 at medium effort. Only a documented difficult item may be referred for Sol/high review under `dual_agent_workflow.md`. `manual_handoff` never prohibits that one QA or its normal recheck. A source-clear correction within an approved goal is repairable without re-approving each occurrence; source ambiguity/editorial changes/approved-term changes/new permissions remain gated. This does not downgrade risk or fabricate human approval.

The tier-based queue below is a backward-compatible adapter for old findings or an explicitly requested specialist assessment. Its counts recommend authority needs, never authorize extra agents/models. Do not apply maximum-quality extra-review counts to the default two-agent workflow. If an actually required specialist is unavailable/unapproved, record that dependency and continue unaffected work. Old queue files keep their original schema/version and historical meaning; don't use their old OPEN state for a different current artifact.

## Safety invariant

Cost controls resource allocation; they never lower source authority, technical fidelity, regulatory caution, or publication acceptance gates. Risk is attached to a decision unit, not to an entire page or document.

Use the highest applicable class:

```text
effective_risk = max(declared_risk, all signal risks)
```

Confidence and cost profile cannot downgrade a RED signal. Missing or unknown signals default to RED. A proposed translation from a low-cost executor is evidence only, never an accepted RED decision.

`cost_profile` and `escalation_mode` are orthogonal. Cost controls review intensity; escalation mode controls whether Codex may start the required higher-tier reviewer automatically. Missing `escalation_mode` defaults to `manual_handoff`; never derive `auto_escalate` from the cost profile.

## Risk classes

- **GREEN** — deterministic or mechanical work with an observable pass/fail result: schema validation, hash comparison, exact counts, identifiers, approved exact phrases without a context split, overlay preconditions, style consistency, and pixel identity. GREEN closes only after its deterministic check passes.
- **AMBER** — a maintained rule exists but context still determines the result: context-sensitive terminology, translation choice under a rule, pronoun scope, Chinese technical style, source mapping, layout interpretation, and caption context. AMBER without an applicable `rule_id` becomes RED.
- **RED** — wording or evidence can affect regulation, certification, technical conclusions, or source fidelity: regulatory fixed wording, rare airworthiness terms, normative force, source contradictions, formula/text conflicts, official standard terms, Safety/Security distinctions, unknown acronyms, numeric limits, source corrections, and technical-conclusion changes.

Keep detection separate from adjudication. For example, a script can deterministically detect that two numeric values differ (GREEN); deciding which value governs may be RED.

## Abstract execution tiers

Use capability tiers rather than product/model names:

1. `automation`
2. `economy_model`
3. `standard_model`
4. `highest_available_reasoning`
5. `human_authority`

If a required tier is unavailable, leave the item OPEN and block acceptance. Do not route it downward.

### Assessor-tier trust boundary

The CLI/run-context `--assessor-tier` is the trusted maximum capability of the current queue-building run. A finding's `origin_assessor_tier` records provenance only and cannot grant authority. Compute:

```text
effective_assessor_tier = min(origin_assessor_tier, CLI assessor tier)
```

using the tier order above. If origin is absent, effective tier equals the CLI tier. If origin claims a higher tier than the CLI context, preserve the claim as provenance, lower the effective tier, and record `ORIGIN_ASSESSOR_TIER_ELEVATION_REJECTED`. The finding remains valid input and routes using the lowered effective tier.

For RED items, both `automation` and `economy_model` are non-authoritative proposal tiers. If either effective tier supplies `candidate_resolution`, clear it to null, set `proposal_only=true`, record `LOW_COST_RED_GUESS_SUPPRESSED`, and keep the item OPEN/BLOCKING regardless of confidence.

## Cost profiles

| Profile | GREEN | AMBER | RED |
|---|---|---|---|
| `economy` | Deterministic tool or economical executor plus a passing mechanical check | May close only with an applicable rule, complete evidence, confidence at least 0.90, and an adequate executor; otherwise route to `standard_model` | Always route to `highest_available_reasoning` |
| `balanced` | Same deterministic baseline | May close only with an applicable rule, complete evidence, confidence at least 0.80, and `standard_model` or higher; otherwise route upward | Always route to `highest_available_reasoning` |
| `maximum_quality` | Deterministic check remains required | Never auto-close; require an independent highest-reasoning review | Require two independent highest-reasoning reviews |

RED items involving official terms or fixed regulatory wording also require official-source verification. Source contradiction, formula/text conflict, source correction, or technical-conclusion change also requires human adjudication.

`maximum_quality` does not send GREEN work to an advanced model. Schema, hash, exact-count, pixel, and structural checks remain deterministic and close only on their mechanical evidence. Maximum quality increases AMBER review strength and RED review independence, not GREEN cost.

## Escalation modes

### `manual_handoff` (safe default)

When genuine OPEN decisions exist, write a scoped handoff and pause their adjudication, dependent changes and formal release. Continue the single ordinary independent QA and independent authorized work. Do not automatically start a highest-reasoning reviewer, Ultra or any third agent. Handoff includes English context, current/proposed targets, evidence, recommendation and affected scope. Source evidence and approval—not a queue status alone—govern closure.

### `auto_escalate`

Only this mode permits Codex to request the higher-tier reviewers recorded in each route. RED still cannot be closed by a low tier; official-source and human-authority requirements remain mandatory; `maximum_quality` retains its independent-review counts. Ultra is used only when explicitly required by `maximum_quality`/project policy, justified by systemic high-risk doubt, approved by the user, or selected as the actual mapping of the required highest-capability tier.

## Queue contract

Create the queue before claiming formal structured-translation or publication acceptance. For an excerpt response, report unresolved items inline without creating a project solely for the queue. `ASSESSOR_TIER` below is a placeholder for the actual trusted run tier; neither the example nor the `gpt-6.2-astra` model name grants a higher tier:

```powershell
python "$SKILL_ROOT/scripts/build_escalation_queue.py" --input QA/review_findings.jsonl --project PROJECT/project.json --output QA/escalation_queue.json --assessor-tier ASSESSOR_TIER
```

The queue is deterministic, contains only OPEN blockers, avoids timestamps and absolute paths, and validates against `schemas/escalation.schema.json`. It records trusted CLI tier, origin and effective tiers, escalation mode, source locator, signals, risk, evidence, confidence basis, suppressed proposals, required reviewer/actions, policy violations, and summary counts. Schema version `1.1` adds required trust-boundary and escalation-mode fields. The unchanged queue engine reports policy version `1.1.1`; Skill `1.1.2` changes instruction scope and routing, not its risk thresholds or schema. Regenerate older `1.0` queue files with the bundled builder before validation.

- Exit 0: valid and no open queue.
- Exit 1: valid but OPEN blockers exist.
- Exit 2: invalid input, schema, or paths.
- `--report-only` changes only the process exit code for dry-run inspection; it never changes queue status from `BLOCKED` to `PASS`.

The legacy builder does not close RED items or start reviewers. Ordinary workflow dispatch stays independent of this adapter. Additional capability/model/assessor selection always requires actual applicable authority; no self-declared tier grants it. The workflow adapter requires source evidence for automatic repair and recheck evidence for resolved items; an empty manual queue never establishes completed work or publication PASS.
