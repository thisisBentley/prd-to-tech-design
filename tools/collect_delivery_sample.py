#!/usr/bin/env python3
"""Collect one P0.5 benchmark sample from a real Delivery run."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else base / path


def digest_file(path: Path | None) -> str | None:
    if not path or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_replay_hash(paths: list[Path | None]) -> str:
    payload = []
    for path in paths:
        if path and path.exists():
            payload.append({"path": path.name, "sha256": digest_file(path)})
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def review_findings(plan: dict[str, Any], root: Path) -> set[str]:
    findings: set[str] = set()
    for task in plan.get("tasks", []):
        if task.get("kind") != "reviewer" and not str(task.get("taskId", "")).startswith("RECHECK-"):
            continue
        result_path = resolve(root, task.get("resultPath"))
        if not result_path or not result_path.exists():
            continue
        result = load(result_path, {})
        review_path = resolve(result_path.parent, result.get("reviewResultPath"))
        review = load(review_path, result) if review_path else result
        for item in review.get("findings", []) or []:
            if item.get("severity") == "BLOCKING":
                findings.add(str(item.get("rootCauseId") or item.get("findingId")))
    return findings


def duration_seconds(plan: dict[str, Any]) -> float:
    starts = []
    ends = []
    for task in plan.get("tasks", []):
        for key, bucket in (("startedAt", starts), ("completedAt", ends)):
            value = task.get(key)
            if value:
                try:
                    bucket.append(datetime.fromisoformat(value.replace("Z", "+00:00")))
                except ValueError:
                    pass
    if not starts or not ends:
        return 0.0
    return round(max(0.0, (max(ends) - min(starts)).total_seconds()), 3)


def traceability(prd_path: Path | None) -> dict[str, int]:
    if not prd_path or not prd_path.exists():
        return {"frTotal": 0, "frCovered": 0, "acTotal": 0, "acCovered": 0}
    text = prd_path.read_text(encoding="utf-8")
    fr_set = set(FR_RE.findall(text))
    ac_set = set(AC_RE.findall(text))
    frs = sorted(fr_set)
    acs = sorted(ac_set)
    covered_ac = set()
    covered_fr = set()
    for ac in acs:
        match = re.search(rf"\b{re.escape(ac)}\b", text)
        if not match:
            continue
        window = text[max(0, match.start() - 800): min(len(text), match.end() + 1200)]
        refs = set(FR_RE.findall(window))
        if refs:
            covered_ac.add(ac)
            covered_fr.update(refs)
    return {"frTotal": len(frs), "frCovered": len(fr_set & covered_fr), "acTotal": len(acs), "acCovered": len(covered_ac)}


def collect(spec: dict[str, Any], spec_path: Path) -> dict[str, Any]:
    base = spec_path.parent
    root = resolve(base, spec["runRoot"])
    if root is None or not root.exists():
        raise FileNotFoundError(f"runRoot not found: {root}")
    plan_path = resolve(base, spec.get("plan")) or root / ".agents" / "delivery-plan.json"
    quality_path = resolve(base, spec.get("qualityExit"))
    final_path = resolve(base, spec.get("finalGate"))
    pair_path = resolve(base, spec.get("pair"))
    overview_path = resolve(base, spec.get("overviewGate"))
    runtime_path = resolve(base, spec.get("runtimeEvidence"))
    prd_path = resolve(base, spec.get("prd"))
    plan = load(plan_path, {"tasks": []})
    quality = load(quality_path, {})
    final = load(final_path, {})
    pair = load(pair_path, {})
    overview = load(overview_path, {})
    runtime = load(runtime_path, {})
    detected = sorted(review_findings(plan, root))
    expected = sorted(set(spec.get("groundTruthFindingIds", [])))
    escalation_files = list((root / ".agents" / "escalations").glob("*.json")) if (root / ".agents" / "escalations").exists() else []
    decision_files = list((root / ".agents" / "decisions").glob("*.json")) if (root / ".agents" / "decisions").exists() else []
    open_escalations = sum(1 for path in escalation_files if load(path, {}).get("status") == "open")
    open_decisions = sum(1 for path in decision_files if load(path, {}).get("status") not in {"confirmed", "closed"})
    repairs = [task for task in plan.get("tasks", []) if str(task.get("taskId", "")).startswith("PRD-REPAIR-")]
    repeated = {
        str(task.get("rootCauseId")) for task in repairs
        if task.get("rootCauseId") and sum(1 for item in repairs if item.get("rootCauseId") == task.get("rootCauseId")) >= 2
    }
    evidence_paths = [plan_path, quality_path, final_path, pair_path, overview_path, runtime_path]
    replay_hash = compute_replay_hash(evidence_paths)
    comparison_root = resolve(base, spec.get("comparisonRunRoot"))
    replay_matches = True
    if comparison_root:
        comparison_plan = comparison_root / ".agents" / "delivery-plan.json"
        comparison_quality = next((comparison_root / ".agents" / "quality").glob("*.json"), None) if (comparison_root / ".agents" / "quality").exists() else None
        replay_matches = compute_replay_hash([comparison_plan, comparison_quality]) == compute_replay_hash([plan_path, quality_path])
    return {
        "sampleId": spec["sampleId"],
        "profile": spec["profile"],
        "caseTypes": spec["caseTypes"],
        "productionEligible": bool(spec.get("productionEligible")) and bool(quality) and bool(final),
        "durationSeconds": duration_seconds(plan),
        "expectedFindingIds": expected,
        "detectedFindingIds": detected,
        "repairRounds": len({item.get("repairRound", 1) for item in repairs}),
        "repeatedRootCauseCount": len(repeated),
        "escalationCount": len(escalation_files),
        "decisionCount": len(decision_files),
        "openEscalationCount": open_escalations,
        "openDecisionCount": open_decisions,
        "traceability": traceability(prd_path),
        "pairStatus": pair.get("pairStatus", "NOT_APPLICABLE") if spec["profile"] != "PRD_ONLY" else "NOT_APPLICABLE",
        "unresolvedDelta": int(quality.get("metrics", {}).get("unresolvedDelta", 0)),
        "staleOverview": 1 if overview and overview.get("status") != "PASS" else 0,
        "runtimeConsoleErrors": int(runtime.get("consoleErrors", len(runtime.get("consoleDiagnostics", []) or []))),
        "replayHash": replay_hash,
        "replayMatches": replay_matches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = collect(load(args.spec), args.spec.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "sampleId": result["sampleId"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
