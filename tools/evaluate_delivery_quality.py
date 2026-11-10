#!/usr/bin/env python3
"""Evaluate Delivery quality, repair efficiency and replay consistency."""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_CASES = {
    "SIMPLE_PRD_ONLY",
    "COMPLEX_PERMISSION_STATE",
    "PRD_PROTOTYPE",
    "PROTOTYPE_SEMANTIC_DELETE",
    "EXISTING_CAPABILITY_TERMINOLOGY",
    "MULTI_ROUND_REPAIR",
    "DECISION_ESCALATION",
}
PROTOTYPE_PROFILES = {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return round(ordered[index], 3)


def check(check_id: str, passed: bool, observed: Any, expected: Any, evidence: list[str]) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": evidence,
    }


def evaluate(data: dict[str, Any], source_path: Path) -> dict[str, Any]:
    samples = data.get("samples", [])
    thresholds = data.get("thresholds", {})
    tp = fp = fn = 0
    trace_total = trace_covered = 0
    for sample in samples:
        expected = set(sample.get("expectedFindingIds", []))
        detected = set(sample.get("detectedFindingIds", []))
        tp += len(expected & detected)
        fp += len(detected - expected)
        fn += len(expected - detected)
        trace = sample.get("traceability", {})
        trace_total += int(trace.get("frTotal", 0)) + int(trace.get("acTotal", 0))
        trace_covered += int(trace.get("frCovered", 0)) + int(trace.get("acCovered", 0))

    recall = 1.0 if tp + fn == 0 else tp / (tp + fn)
    precision = 1.0 if tp + fp == 0 else tp / (tp + fp)
    fpr = 0.0 if tp + fp == 0 else fp / (tp + fp)
    traceability = 1.0 if trace_total == 0 else trace_covered / trace_total
    replay_consistency = (sum(1 for sample in samples if sample.get("replayMatches")) / len(samples)) if samples else 0.0
    durations: dict[str, list[float]] = defaultdict(list)
    for sample in samples:
        durations[sample.get("profile", "UNKNOWN")].append(float(sample.get("durationSeconds", 0)))
    p50 = {profile: percentile(values, 0.5) for profile, values in sorted(durations.items())}
    p90 = {profile: percentile(values, 0.9) for profile, values in sorted(durations.items())}
    case_types = sorted({case for sample in samples for case in sample.get("caseTypes", [])})
    missing_cases = sorted(REQUIRED_CASES - set(case_types))
    production_samples = [sample for sample in samples if sample.get("productionEligible")]
    min_samples = int(thresholds.get("minimumSamples", 3))
    max_samples = int(thresholds.get("maximumSamples", 5))
    min_recall = float(thresholds.get("minimumFindingRecall", 1.0))
    max_fpr = float(thresholds.get("maximumFalsePositiveRate", 0.05))
    min_replay = float(thresholds.get("minimumReplayConsistency", 1.0))
    pair_failures = [
        sample.get("sampleId") for sample in samples
        if sample.get("profile") in PROTOTYPE_PROFILES and sample.get("pairStatus") != "SYNCED"
    ]
    overview_failures = [sample.get("sampleId") for sample in samples if int(sample.get("staleOverview", 0)) != 0]
    runtime_failures = [sample.get("sampleId") for sample in samples if int(sample.get("runtimeConsoleErrors", 0)) != 0]
    open_decision_escalation_failures = [
        sample.get("sampleId") for sample in samples
        if int(sample.get("openDecisionCount", 0)) != 0 or int(sample.get("openEscalationCount", 0)) != 0
    ]
    sample_count_ok = min_samples <= len(samples) <= max_samples
    evidence = [str(source_path.resolve())]
    checks = [
        check("BENCHMARK.SAMPLE_COUNT", sample_count_ok, len(samples), f"{min_samples}..{max_samples} samples", evidence),
        check("BENCHMARK.CASE_COVERAGE", not missing_cases, {"covered": case_types, "missing": missing_cases}, "all required case dimensions covered", evidence),
        check("BENCHMARK.FINDING_RECALL", recall >= min_recall, round(recall, 4), f">={min_recall}", evidence),
        check("BENCHMARK.FALSE_POSITIVE_RATE", fpr <= max_fpr, round(fpr, 4), f"<={max_fpr}", evidence),
        check("BENCHMARK.TRACEABILITY", traceability == 1.0, round(traceability, 4), 1.0, evidence),
        check("BENCHMARK.PAIR_SYNC", not pair_failures, pair_failures, "SYNCED for every Prototype profile", evidence),
        check("BENCHMARK.OVERVIEW_FRESHNESS", not overview_failures, overview_failures, "zero stale Overview", evidence),
        check("BENCHMARK.RUNTIME", not runtime_failures, runtime_failures, "zero console errors", evidence),
        check("BENCHMARK.REPLAY", replay_consistency >= min_replay, round(replay_consistency, 4), f">={min_replay}", evidence),
        check("BENCHMARK.OPEN_GAPS", not open_decision_escalation_failures, open_decision_escalation_failures, "zero open decisions and escalations", evidence),
    ]
    if not sample_count_ok:
        status = "INSUFFICIENT_SAMPLES"
    else:
        status = "PASS" if all(item["status"] == "passed" for item in checks) else "FAIL"
    metrics = {
        "truePositiveFindings": tp,
        "falsePositiveFindings": fp,
        "falseNegativeFindings": fn,
        "findingRecall": round(recall, 4),
        "findingPrecision": round(precision, 4),
        "falsePositiveRate": round(fpr, 4),
        "averageRepairRounds": round(sum(int(s.get("repairRounds", 0)) for s in samples) / len(samples), 3) if samples else 0,
        "repeatedRootCauseCount": sum(int(s.get("repeatedRootCauseCount", 0)) for s in samples),
        "escalationCount": sum(int(s.get("escalationCount", 0)) for s in samples),
        "decisionCount": sum(int(s.get("decisionCount", 0)) for s in samples),
        "traceability": round(traceability, 4),
        "replayConsistency": round(replay_consistency, 4),
        "caseCoverage": case_types,
        "durationP50Seconds": p50,
        "durationP90Seconds": p90,
        "caseTypeFrequency": dict(sorted(Counter(case for sample in samples for case in sample.get("caseTypes", [])).items())),
    }
    production_eligible = (
        data.get("dataClassification") == "REAL"
        and min_samples <= len(production_samples) <= max_samples
        and status == "PASS"
    )
    blocking = [item["checkId"] for item in checks if item["status"] == "failed"]
    return {
        "schemaVersion": 1,
        "benchmarkId": data.get("benchmarkId", "unknown"),
        "status": status,
        "productionEligible": production_eligible,
        "dataClassification": data.get("dataClassification"),
        "sampleCount": len(samples),
        "productionSampleCount": len(production_samples),
        "metrics": metrics,
        "checks": checks,
        "blockingCount": len(blocking),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(load(args.input), args.input.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "blockingCount": result["blockingCount"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
