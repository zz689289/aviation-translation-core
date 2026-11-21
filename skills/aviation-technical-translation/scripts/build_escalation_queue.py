"""Build a deterministic cost-aware escalation queue from review findings.

Exit codes: 0 for no blockers (or --report-only), 1 for a valid open queue,
and 2 for invalid input, schema, or paths. The script never adjudicates items.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from common import atomic_write_json, ensure_distinct_paths, load_json, load_jsonl, schema_validation_errors, sha256_file


RISK_RANK = {"GREEN": 0, "AMBER": 1, "RED": 2}
TIER_RANK = {
    "automation": 0,
    "economy_model": 1,
    "standard_model": 2,
    "highest_available_reasoning": 3,
    "human_authority": 4,
}
SIGNAL_RISK = {
    "schema_validation": "GREEN",
    "hash_match": "GREEN",
    "exact_count": "GREEN",
    "identifier_match": "GREEN",
    "approved_exact_phrase_no_context_split": "GREEN",
    "overlay_precondition": "GREEN",
    "pixel_identity": "GREEN",
    "style_consistency": "GREEN",
    "context_sensitive_term": "AMBER",
    "translation_choice_under_rule": "AMBER",
    "pronoun_scope": "AMBER",
    "chinese_technical_style": "AMBER",
    "source_mapping_ambiguity": "AMBER",
    "layout_interpretation": "AMBER",
    "caption_context": "AMBER",
    "regulatory_fixed_wording": "RED",
    "rare_airworthiness_term": "RED",
    "normative_force": "RED",
    "source_contradiction": "RED",
    "formula_text_conflict": "RED",
    "official_standard_term": "RED",
    "safety_security_distinction": "RED",
    "unknown_acronym": "RED",
    "numeric_limit_change": "RED",
    "source_correction": "RED",
    "technical_conclusion_change": "RED",
}
OFFICIAL_SOURCE_SIGNALS = {"official_standard_term", "regulatory_fixed_wording"}
HUMAN_SIGNALS = {"source_contradiction", "formula_text_conflict", "source_correction", "technical_conclusion_change"}
ALLOWED_FINDING_FIELDS = {
    "id", "category", "source_locator", "signals", "declared_risk_class", "finding",
    "source_text", "target_text", "rule_id", "confidence", "confidence_basis",
    "evidence", "origin_assessor_tier", "candidate_resolution", "deterministic_verification",
}
REQUIRED_FINDING_FIELDS = {
    "id", "category", "source_locator", "signals", "finding", "source_text",
    "target_text", "confidence_basis", "evidence",
}


def load_findings(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return load_jsonl(path)
    value = load_json(path)
    if isinstance(value, list):
        findings = value
    elif isinstance(value, dict) and isinstance(value.get("findings"), list):
        findings = value["findings"]
    else:
        raise ValueError("Input must be JSONL, a JSON array, or an object containing a findings array.")
    if not all(isinstance(item, dict) for item in findings):
        raise ValueError("Every finding must be a JSON object.")
    return findings


def validate_finding(item: dict[str, Any], index: int) -> None:
    extra = sorted(set(item) - ALLOWED_FINDING_FIELDS)
    missing = sorted(REQUIRED_FINDING_FIELDS - set(item))
    if extra:
        raise ValueError(f"finding[{index}] has unknown fields: {extra}")
    if missing:
        raise ValueError(f"finding[{index}] is missing fields: {missing}")
    if not isinstance(item.get("id"), str) or not item["id"].strip():
        raise ValueError(f"finding[{index}].id must be a nonempty string")
    locator = item.get("source_locator")
    if not isinstance(locator, dict) or not isinstance(locator.get("object_id"), str) or not locator["object_id"].strip():
        raise ValueError(f"finding[{index}].source_locator.object_id is required")
    signals = item.get("signals")
    if not isinstance(signals, list) or not all(isinstance(value, str) and value for value in signals):
        raise ValueError(f"finding[{index}].signals must be an array of nonempty strings")
    if len(signals) != len(set(signals)):
        raise ValueError(f"finding[{index}].signals contains duplicates")
    declared = item.get("declared_risk_class")
    if declared is not None and declared not in RISK_RANK:
        raise ValueError(f"finding[{index}].declared_risk_class is invalid")
    confidence = item.get("confidence")
    if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1):
        raise ValueError(f"finding[{index}].confidence must be null or between 0 and 1")
    tier = item.get("origin_assessor_tier")
    if tier is not None and tier not in TIER_RANK:
        raise ValueError(f"finding[{index}].origin_assessor_tier is invalid")
    evidence = item.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError(f"finding[{index}].evidence must be an array")
    required_evidence = {"kind", "locator", "summary", "authority"}
    for evidence_index, record in enumerate(evidence, 1):
        if not isinstance(record, dict) or set(record) != required_evidence:
            raise ValueError(f"finding[{index}].evidence[{evidence_index}] must contain exactly {sorted(required_evidence)}")


def highest_risk(values: list[str]) -> str:
    return max(values, key=lambda value: RISK_RANK[value])


def classify(item: dict[str, Any]) -> tuple[str, list[str]]:
    violations: list[str] = []
    signals = item["signals"]
    if not signals:
        signal_risks = ["RED"]
        violations.append("MISSING_RISK_SIGNAL_DEFAULTED_TO_RED")
    else:
        signal_risks = []
        for signal in signals:
            if signal not in SIGNAL_RISK:
                signal_risks.append("RED")
                violations.append(f"UNKNOWN_SIGNAL_DEFAULTED_TO_RED:{signal}")
            else:
                signal_risks.append(SIGNAL_RISK[signal])
    signal_risk = highest_risk(signal_risks)
    declared = item.get("declared_risk_class")
    effective = highest_risk([signal_risk, declared] if declared else [signal_risk])
    if declared and RISK_RANK[declared] < RISK_RANK[signal_risk]:
        violations.append("DECLARED_RISK_DOWNGRADE_REJECTED")
    if effective == "GREEN" and item.get("deterministic_verification") != "PASS":
        effective = "AMBER"
        violations.append("GREEN_WITHOUT_PASS_PROMOTED_TO_AMBER")
    if effective == "GREEN" and not item.get("evidence"):
        effective = "AMBER"
        violations.append("GREEN_WITHOUT_EVIDENCE_PROMOTED_TO_AMBER")
    if effective == "AMBER" and not item.get("rule_id"):
        effective = "RED"
        violations.append("AMBER_WITHOUT_RULE_PROMOTED_TO_RED")
    return effective, violations


def route_item(item: dict[str, Any], risk: str, profile: str, assessor_tier: str) -> tuple[bool, dict[str, Any], list[str]]:
    violations: list[str] = []
    confidence = item.get("confidence")
    evidence_complete = bool(item.get("evidence"))
    if risk == "GREEN":
        return False, {}, violations
    if risk == "AMBER":
        if profile == "economy":
            can_close = bool(item.get("rule_id")) and evidence_complete and confidence is not None and confidence >= 0.90 and TIER_RANK[assessor_tier] >= TIER_RANK["economy_model"]
            reviewer = "standard_model"
            independent = 0
        elif profile == "balanced":
            can_close = bool(item.get("rule_id")) and evidence_complete and confidence is not None and confidence >= 0.80 and TIER_RANK[assessor_tier] >= TIER_RANK["standard_model"]
            reviewer = "highest_available_reasoning"
            independent = 0
        else:
            can_close = False
            reviewer = "highest_available_reasoning"
            independent = 1
        return (not can_close), {
            "required_reviewer_tier": reviewer,
            "required_actions": ["context_review", "rule_evidence_verification"],
            "required_independent_review_count": independent,
            "human_authority_required": False,
        }, violations

    actions = ["highest_reasoning_review"]
    signals = set(item["signals"])
    if signals & OFFICIAL_SOURCE_SIGNALS:
        actions.append("official_source_verification")
    human_required = bool(signals & HUMAN_SIGNALS)
    if human_required:
        actions.append("human_adjudication")
    independent = 2 if profile == "maximum_quality" else 1
    if TIER_RANK[assessor_tier] <= TIER_RANK["economy_model"] and item.get("candidate_resolution"):
        violations.append("LOW_COST_RED_GUESS_SUPPRESSED")
    return True, {
        "required_reviewer_tier": "highest_available_reasoning",
        "required_actions": actions,
        "required_independent_review_count": independent,
        "human_authority_required": human_required,
    }, violations


def effective_assessor_tier(origin_assessor_tier: str | None, trusted_assessor_tier: str) -> tuple[str, list[str]]:
    if origin_assessor_tier is None:
        return trusted_assessor_tier, []
    effective = min(
        (origin_assessor_tier, trusted_assessor_tier),
        key=lambda tier: TIER_RANK[tier],
    )
    violations = []
    if TIER_RANK[origin_assessor_tier] > TIER_RANK[trusted_assessor_tier]:
        violations.append("ORIGIN_ASSESSOR_TIER_ELEVATION_REJECTED")
    return effective, violations


def markdown_value(value: Any) -> str:
    if value is None:
        return "—"
    return " ".join(str(value).replace("|", "\\|").splitlines()).strip() or "—"


def build_handoff(queue: dict[str, Any]) -> str:
    summary = queue["summary"]
    lines = [
        "# Escalation handoff",
        "",
        f"- Project: `{markdown_value(queue['project_id'])}`",
        f"- Cost profile: `{queue['cost_profile']}`",
        f"- Escalation mode: `{queue['escalation_mode']}`",
        f"- Current executor tier: `{queue['assessor_tier']}`",
        f"- OPEN count: {summary['queue_count']}",
        f"- AMBER count: {summary['queued_risk_counts']['AMBER']}",
        f"- RED count: {summary['queued_risk_counts']['RED']}",
        "- Automatic higher-tier review started: no",
        "- Publication acceptance: BLOCKED",
        "",
        "Completed work: deterministic classification, trust-boundary enforcement, queue validation, and low-cost RED proposal suppression.",
        "The following items remain OPEN because the current effective assessor tier cannot satisfy their recorded review route.",
        "",
    ]
    for item in queue["items"]:
        route = item["route"]
        evidence = "; ".join(
            f"{markdown_value(record['kind'])}: {markdown_value(record['locator'])} — "
            f"{markdown_value(record['summary'])} [{markdown_value(record['authority'])}]"
            for record in item["evidence"]
        ) or "—"
        official_required = "official_source_verification" in route["required_actions"]
        suppressed = "LOW_COST_RED_GUESS_SUPPRESSED" in item["policy_violations"]
        blocking_reason = (
            f"{item['effective_risk_class']} remains OPEN; requires {route['required_reviewer_tier']}"
            f" and {route['required_independent_review_count']} independent review(s)."
        )
        lines.extend(
            [
                f"## {markdown_value(item['id'])}",
                "",
                f"- Risk: `{item['effective_risk_class']}`",
                f"- Category: {markdown_value(item['category'])}",
                f"- Source locator: `{markdown_value(item['source_locator'].get('object_id'))}`",
                f"- Source text: {markdown_value(item['source_text'])}",
                f"- Current target: {markdown_value(item['target_text'])}",
                f"- Rule: {markdown_value(item['rule_id'])}",
                f"- Evidence: {evidence}",
                f"- Confidence: {markdown_value(item['confidence'])}",
                f"- Confidence basis: {markdown_value(item['confidence_basis'])}",
                f"- Origin assessor tier: `{markdown_value(item['origin_assessor_tier'])}`",
                f"- Effective assessor tier: `{item['effective_assessor_tier']}`",
                f"- Required reviewer tier: `{route['required_reviewer_tier']}`",
                f"- Required actions: {', '.join(route['required_actions'])}",
                f"- Official-source requirement: {'yes' if official_required else 'no'}",
                f"- Human-authority requirement: {'yes' if route['human_authority_required'] else 'no'}",
                f"- Suppressed low-cost proposal: {'yes' if suppressed else 'no'}",
                f"- Blocking reason: {blocking_reason}",
                "",
            ]
        )
    lines.extend(
        [
            "## Copyable reviewer instruction",
            "",
            "> Only process OPEN items in escalation_queue.json. Do not re-review closed GREEN/AMBER items and do not modify any other content. Record evidence and authority for every closure.",
            "",
        ]
    )
    return "\n".join(lines)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def queue_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    locator = item["source_locator"]
    return (
        -RISK_RANK[item["effective_risk_class"]],
        str(locator.get("source_asset_id", "")),
        int(locator.get("page", 0)),
        int(locator.get("order", 0)),
        str(locator.get("object_id", "")),
        item["id"],
    )


def schema_errors(queue: dict[str, Any]) -> list[str]:
    return schema_validation_errors(
        queue,
        Path(__file__).resolve().parent.parent / "schemas" / "escalation.schema.json",
    )


def build_queue(
    input_path: Path,
    project_path: Path | None,
    project_id: str | None,
    cli_profile: str | None,
    cli_escalation_mode: str | None,
    assessor_tier: str,
) -> dict[str, Any]:
    findings = load_findings(input_path)
    identifiers = []
    for index, item in enumerate(findings, 1):
        validate_finding(item, index)
        identifiers.append(item["id"])
    duplicates = sorted(identifier for identifier, count in Counter(identifiers).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate finding IDs: {duplicates}")

    project = load_json(project_path) if project_path else None
    resolved_project_id = project_id or (str(project.get("project_id")) if project else None)
    if not resolved_project_id:
        raise ValueError("Provide --project or --project-id.")
    if cli_profile:
        profile, profile_source = cli_profile, "cli"
    elif project and project.get("cost_profile"):
        profile, profile_source = str(project["cost_profile"]), "project"
    else:
        profile, profile_source = "balanced", "legacy_default"
    if profile not in {"economy", "balanced", "maximum_quality"}:
        raise ValueError(f"Invalid project cost_profile: {profile!r}")
    if cli_escalation_mode:
        escalation_mode, escalation_mode_source = cli_escalation_mode, "cli"
    elif project and project.get("escalation_mode"):
        escalation_mode, escalation_mode_source = str(project["escalation_mode"]), "project"
    else:
        escalation_mode, escalation_mode_source = "manual_handoff", "safe_default"
    if escalation_mode not in {"manual_handoff", "auto_escalate"}:
        raise ValueError(f"Invalid project escalation_mode: {escalation_mode!r}")

    input_counts = Counter({"GREEN": 0, "AMBER": 0, "RED": 0})
    queued_counts = Counter({"GREEN": 0, "AMBER": 0, "RED": 0})
    queue_items: list[dict[str, Any]] = []
    violation_count = 0
    for finding in findings:
        declared_origin_tier = finding.get("origin_assessor_tier")
        origin_tier = str(declared_origin_tier) if declared_origin_tier is not None else None
        effective_tier, trust_violations = effective_assessor_tier(origin_tier, assessor_tier)
        risk, violations = classify(finding)
        violations.extend(trust_violations)
        input_counts[risk] += 1
        queued, route, route_violations = route_item(finding, risk, profile, effective_tier)
        violations.extend(route_violations)
        violation_count += len(violations)
        if not queued:
            continue
        candidate_resolution = finding.get("candidate_resolution")
        proposal_only = risk == "RED"
        if "LOW_COST_RED_GUESS_SUPPRESSED" in violations:
            candidate_resolution = None
        record = {
            "id": finding["id"],
            "category": finding["category"],
            "source_locator": finding["source_locator"],
            "signals": finding["signals"],
            "declared_risk_class": finding.get("declared_risk_class"),
            "effective_risk_class": risk,
            "finding": finding["finding"],
            "source_text": finding["source_text"],
            "target_text": finding["target_text"],
            "rule_id": finding.get("rule_id"),
            "confidence": finding.get("confidence"),
            "confidence_basis": finding["confidence_basis"],
            "evidence": finding["evidence"],
            "origin_assessor_tier": origin_tier,
            "effective_assessor_tier": effective_tier,
            "candidate_resolution": candidate_resolution,
            "proposal_only": proposal_only,
            "route": route,
            "blocking": True,
            "status": "OPEN",
            "policy_violations": sorted(set(violations)),
        }
        queue_items.append(record)
        queued_counts[risk] += 1
    queue_items.sort(key=queue_sort_key)
    summary = {
        "input_count": len(findings),
        "queue_count": len(queue_items),
        "non_queue_count": len(findings) - len(queue_items),
        "blocking_count": len(queue_items),
        "policy_violation_count": violation_count,
        "input_risk_counts": {key: input_counts[key] for key in ("GREEN", "AMBER", "RED")},
        "queued_risk_counts": {key: queued_counts[key] for key in ("GREEN", "AMBER", "RED")},
    }
    queue = {
        "schema_version": "1.1",
        "policy_version": "1.1.1",
        "project_id": resolved_project_id,
        "cost_profile": profile,
        "profile_source": profile_source,
        "escalation_mode": escalation_mode,
        "escalation_mode_source": escalation_mode_source,
        "automatic_escalation_permitted": escalation_mode == "auto_escalate",
        "handoff_required": escalation_mode == "manual_handoff" and bool(queue_items),
        "assessor_tier": assessor_tier,
        "input_sha256": sha256_file(input_path),
        "status": "BLOCKED" if queue_items else "PASS",
        "summary": summary,
        "items": queue_items,
    }
    errors = schema_errors(queue)
    if errors:
        raise ValueError("Generated queue failed schema validation: " + "; ".join(errors))
    if summary["input_count"] != summary["queue_count"] + summary["non_queue_count"]:
        raise ValueError("Generated queue summary count invariant failed.")
    return queue


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", action="store_true", help="Route workflow 1.2 findings into pending, routine repair and human decision scopes; no assessor upgrade.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--project-id")
    parser.add_argument("--cost-profile", choices=("economy", "balanced", "maximum_quality"))
    parser.add_argument("--escalation-mode", choices=("manual_handoff", "auto_escalate"))
    parser.add_argument("--assessor-tier", choices=tuple(TIER_RANK), default="automation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff-output", type=Path)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    try:
        if args.workflow:
            from workflow import route
            if args.output.exists() or args.output.resolve() == args.input.resolve():
                raise ValueError("Refuse overwrite or input/output collision")
            spec = load_json(args.input)
            errors = schema_validation_errors({"command": "route", "spec": spec}, Path(__file__).resolve().parents[1] / "schemas/workflow.schema.json")
            if errors:
                raise ValueError("; ".join(errors))
            report = route(spec)
            atomic_write_json(args.output, report)
            print(f"{report['status']}: ordinary QA permitted; manual items={len(report['manual_handoff'])}; pending={report['pending_translation_objects']}")
            raise SystemExit(0 if report['status'] == 'PASS' or args.report_only else 1)
        input_path = args.input.resolve(strict=True)
        project_path = args.project.resolve(strict=True) if args.project else None
        output_path = args.output.resolve()
        named_paths = {"input": input_path, "output": output_path}
        if project_path:
            named_paths["project"] = project_path
        if output_path.exists():
            raise ValueError(f"Refusing to overwrite existing escalation queue: {output_path}")
        queue = build_queue(
            input_path,
            project_path,
            args.project_id,
            args.cost_profile,
            args.escalation_mode,
            args.assessor_tier,
        )
        if args.handoff_output and queue["escalation_mode"] != "manual_handoff":
            raise ValueError("--handoff-output is only valid with escalation_mode=manual_handoff.")
        handoff_path = None
        if queue["handoff_required"]:
            handoff_path = (
                args.handoff_output.resolve()
                if args.handoff_output
                else output_path.with_name("escalation_handoff.md")
            )
            named_paths["handoff"] = handoff_path
            if handoff_path.exists():
                raise ValueError(f"Refusing to overwrite existing escalation handoff: {handoff_path}")
        ensure_distinct_paths(named_paths)
        atomic_write_json(output_path, queue)
        if handoff_path is not None:
            atomic_write_text(handoff_path, build_handoff(queue))
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(f"{queue['status']}: {queue['summary']['queue_count']} open escalation item(s) -> {output_path}")
    if queue["handoff_required"]:
        print(f"MANUAL_HANDOFF: additional higher-tier escalation stopped; ordinary independent QA permitted; handoff -> {handoff_path}")
    if queue["status"] == "BLOCKED" and not args.report_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
