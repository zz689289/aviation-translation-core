"""Report context for ambiguous high-risk terms; never edits content.

Usage:
    python term_guard.py --content content_blocks.jsonl --report term_review.json

Optional rules JSON may define `terms` as objects with `source`, `case_sensitive`,
`forbidden_targets`, and an explicitly reviewed `match_pattern`. Bounded default
patterns cover recurrent inflection families without partial-word matching. The
script deliberately does not prescribe one unconditional Chinese equivalent.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from common import atomic_write_json, ensure_distinct_paths, load_json, load_jsonl, require_suffix


DEFAULT_RULES = [
    {"source": "human agency", "forbidden_targets": ["人类机构"]},
    {"source": "Gear", "match_pattern": r"Gear\s*#\s*[1-7]", "forbidden_targets": ["号车"]},
    {"source": "EASA", "forbidden_targets": ["欧洲审计事务管理局"]},
    {"source": "contribute to", "match_pattern": r"contribut(?:e|es|ed|ing)\s+to"},
    {"source": "at the next highest level"},
    {"source": "high-fidelity"},
    {"source": "high-frequency"},
    {"source": "test data"},
    {"source": "Validation"},
    {"source": "Solution"},
    {"source": "Issue"},
    {
        "source": "qualification",
        "match_pattern": r"qualif(?:ication(?:s)?|y|ies|ied|ying)",
        "family": "qualification/qualifications/qualify/qualifies/qualified/qualifying",
    },
    {
        "source": "error",
        "match_pattern": r"errors?",
        "family": "error/errors",
    },
    {
        "source": "certification",
        "match_pattern": r"certif(?:ication(?:s)?|y|ies|ied|ying)",
        "family": "certification/certifications/certify/certifies/certified/certifying",
    },
    {"source": "Safety"},
    {"source": "Security"},
    {"source": "integrity"},
    {
        "source": "MOC",
        "match_pattern": r"MOCs?",
        "family": "MOC/MOCs",
    },
    {"source": "FSM"},
]


def compile_rule_pattern(rule: dict[str, Any]) -> re.Pattern[str]:
    source_term = str(rule["source"])
    flags = 0 if rule.get("case_sensitive") else re.IGNORECASE
    expression = str(rule.get("match_pattern") or re.escape(source_term))
    try:
        return re.compile(r"(?<![A-Za-z0-9])(?:" + expression + r")(?![A-Za-z0-9])", flags)
    except re.error as exc:
        raise ValueError(f"Invalid match_pattern for term {source_term!r}: {exc}") from exc


def occurrences(blocks: list[dict[str, Any]], rule: dict[str, Any]) -> list[dict[str, Any]]:
    pattern = compile_rule_pattern(rule)
    hits = []
    forbidden = [str(item) for item in rule.get("forbidden_targets", [])]
    for block in blocks:
        source = str(block.get("source_text", ""))
        matches = list(pattern.finditer(source))
        if not matches:
            continue
        target = str(block.get("target_text", ""))
        hits.append(
            {
                "block_id": block.get("id"),
                "source_page": block.get("source_locator", {}).get("page"),
                "source_context": source,
                "target_context": target,
                "match_count": len(matches),
                "matched_forms": sorted({match.group(0) for match in matches}, key=str.casefold),
                "source_offsets": [[match.start(), match.end()] for match in matches],
                "forbidden_target_hits": [item for item in forbidden if item in target],
                "required_action": "CONTEXT_REVIEW",
            }
        )
    return hits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, required=True)
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    content_path = args.content.resolve()
    report_path = args.report.resolve()
    rules_path = args.rules.resolve() if args.rules else None
    named_paths = {"content input": content_path, "JSON report": report_path}
    if rules_path is not None:
        named_paths["rules input"] = rules_path
    try:
        require_suffix(report_path, ".json", "--report")
        ensure_distinct_paths(named_paths)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    blocks = load_jsonl(content_path)
    if rules_path is not None:
        value = load_json(rules_path)
        rules = value.get("terms", []) if isinstance(value, dict) else value
        if not isinstance(rules, list):
            raise SystemExit("Rules must be an array or an object with a terms array.")
    else:
        rules = [{"case_sensitive": False, "forbidden_targets": [], **rule} for rule in DEFAULT_RULES]
    result = []
    for rule in sorted(rules, key=lambda item: len(str(item.get("source", ""))), reverse=True):
        if not rule.get("source"):
            continue
        hits = occurrences(blocks, rule)
        if hits:
            result.append(
                {
                    "source": rule["source"],
                    "family": rule.get("family"),
                    "block_count": len(hits),
                    "occurrence_count": sum(hit["match_count"] for hit in hits),
                    "occurrences": hits,
                }
            )
    report = {
        "schema_version": "1.0",
        "policy": "phrase_first_context_sensitive_no_unconditional_global_replacement",
        "content": args.content.name,
        "terms_with_hits": len(result),
        "total_occurrences": sum(item["occurrence_count"] for item in result),
        "results": result,
    }
    atomic_write_json(report_path, report)
    print(f"Reported {report['total_occurrences']} high-risk occurrences -> {report_path}")


if __name__ == "__main__":
    main()
