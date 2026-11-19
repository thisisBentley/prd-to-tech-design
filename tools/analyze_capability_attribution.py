#!/usr/bin/env python3
"""Build a conservative capability-attribution decision from evaluation evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integrity", type=Path, required=True)
    parser.add_argument("--capability-gap", type=Path, required=True)
    parser.add_argument("--historical-integrity", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--human-review-complete", action="store_true")
    parser.add_argument("--model-rerun-complete", action="store_true")
    args = parser.parse_args()
    integrity = load(args.integrity.resolve())
    gaps = load(args.capability_gap.resolve())

    invalid_tasks = [item for item in integrity.get("tasks", []) if item.get("status") == "INVALID"]
    historical_invalid: list[dict[str, Any]] = []
    for path in args.historical_integrity:
        historical = load(path.resolve())
        historical_invalid.extend(item for item in historical.get("tasks", []) if item.get("status") == "INVALID")
    capabilities: dict[str, dict[str, Any]] = {}
    for capability, item in sorted((gaps.get("capabilities") or {}).items()):
        capabilities[capability] = {
            "sampleCount": item.get("sampleCount", 0),
            "automaticRiskCodes": item.get("riskCodes", []),
            "stableAcrossSplits": item.get("stableAcrossSplits", False),
            "evaluationIntegrityStatus": "BLOCKED" if invalid_tasks else "PASS",
            "evidenceLayerDefectsProven": ["TASK_EVIDENCE_SCOPE_MISMATCH"] if historical_invalid else [],
            "modelCapabilityGapStatus": "NOT_PROVEN",
            "trainingDecision": "HOLD_OPTIMIZE_HARNESS_SKILL_FIRST" if not args.human_review_complete else "REEVALUATE_WITH_HUMAN_GOLD",
            "notes": [
                "Automatic lexical metrics are screening signals, not semantic truth.",
                "A model-parameter gap requires fair tasks, complete evidence, stable failures and human review.",
            ],
        }
    if invalid_tasks:
        status = "BLOCKED_BY_TASK_INTEGRITY"
    elif not args.model_rerun_complete:
        status = "PROVISIONAL_RECLASSIFICATION_ONLY"
    elif not args.human_review_complete:
        status = "WAITING_FOR_HUMAN_REVIEW"
    else:
        status = "READY_FOR_CAPABILITY_DECISION"
    report = {
        "schemaVersion": 1,
        "status": status,
        "provisional": not args.human_review_complete,
        "humanReviewComplete": bool(args.human_review_complete),
        "modelRerunComplete": bool(args.model_rerun_complete),
        "invalidTaskIds": [item.get("goldenTaskId") for item in invalid_tasks],
        "historicalInvalidTaskIds": sorted({item.get("goldenTaskId") for item in historical_invalid}),
        "capabilities": capabilities,
        "decision": {
            "modelParameterGap": "NOT_PROVEN",
            "harnessSkillContextGap": "PROVEN" if historical_invalid or invalid_tasks else "NOT_PROVEN",
            "training": "HOLD",
            "next": "Correct invalid task/evidence contracts, rerun the full validation/test set, then complete human blind review before considering narrow-capability SFT.",
        },
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    save(args.out, report)
    print(json.dumps({
        "status": report["status"],
        "provisional": report["provisional"],
        "modelRerunComplete": report["modelRerunComplete"],
        "invalidTaskIds": report["invalidTaskIds"],
        "decision": report["decision"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
