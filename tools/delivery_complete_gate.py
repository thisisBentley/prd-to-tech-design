#!/usr/bin/env python3
"""Aggregate all Harness evidence into a Delivery COMPLETE decision."""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import validate_research_record
from evaluate_delivery_quality import evaluate as evaluate_benchmark
from semantic_consistency_review import review as review_semantic

SEMANTIC_CHECKS = {
    "SEMANTIC.TERMINOLOGY",
    "SEMANTIC.CAPABILITY",
    "SEMANTIC.STATE",
    "SEMANTIC.PERMISSION",
    "SEMANTIC.AUTHORITY_SYNC",
    "SEMANTIC.PROVENANCE",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(base: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def check(check_id: str, passed: bool, observed: Any, expected: Any, evidence: list[str]) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": evidence,
    }


def implementation_surfaces(repo_root: Path) -> list[tuple[str, Path]]:
    scripts = repo_root / ("scripts" if (repo_root / "scripts").exists() else "tools")
    contracts = repo_root / ("references" if (repo_root / "references").exists() else "schemas")
    docs = repo_root / ("references" if (repo_root / "references").exists() else "docs")
    core = repo_root / ("references" if (repo_root / "references").exists() else "core")
    return [
        ("research_record_contract", contracts / "research-record.schema.json"),
        ("capability_registry", scripts / "detect_research_capabilities.py"),
        ("semantic_review", scripts / "semantic_consistency_review.py"),
        ("quality_exit", scripts / "delivery_quality_exit.py"),
        ("quality_benchmark", scripts / "evaluate_delivery_quality.py"),
        ("failure_recovery", scripts / "recover_delivery_run.py"),
        ("failure_matrix", docs / "m3-failure-matrix.md"),
        ("semantic_matrix", docs / "semantic-consistency-review-matrix.md"),
        ("p05_acceptance", docs / "p05-quality-acceptance.md"),
        ("harness_design", core / "harness-plane.md"),
    ]


def evaluate(data: dict[str, Any], source_path: Path, repo_root: Path) -> dict[str, Any]:
    base = source_path.parent
    mode = data["mode"]
    paths = {name: resolve(base, value) for name, value in data["evidence"].items() if name != "researchRecords"}
    research_paths = [resolve(base, value) for value in data["evidence"].get("researchRecords", [])]
    missing = [str(path) for path in list(paths.values()) + research_paths if not path.exists()]
    loaded = {name: load(path) for name, path in paths.items() if path.exists()}
    research = [load(path) for path in research_paths if path.exists()]
    evidence_refs = [str(path) for path in list(paths.values()) + research_paths if path.exists()]
    checks: list[dict[str, Any]] = []
    checks.append(check("COMPLETE.EVIDENCE_FILES", not missing, missing, "every required evidence file exists", evidence_refs or [str(source_path.resolve())]))

    surfaces = implementation_surfaces(repo_root)
    missing_surfaces = [name for name, path in surfaces if not path.exists()]
    checks.append(check("COMPLETE.IMPLEMENTATION", not missing_surfaces, {"missing": missing_surfaces}, "all Harness surfaces are implemented", [str(path) for _, path in surfaces]))

    quality_exit = loaded.get("deliveryQualityExit", {})
    checks.append(check("COMPLETE.M1_QUALITY_EXIT", quality_exit.get("status") == "PASS" and int(quality_exit.get("blockingCount", 1)) == 0, {"status": quality_exit.get("status"), "blockingCount": quality_exit.get("blockingCount")}, "PASS with zero blockers", [str(paths["deliveryQualityExit"])]))

    final_gate = loaded.get("finalGate", {})
    checks.append(check("COMPLETE.M2_FINAL_GATE", final_gate.get("result") == "PASS" and int(final_gate.get("blockingCount", 1)) == 0, {"result": final_gate.get("result"), "blockingCount": final_gate.get("blockingCount")}, "PASS with zero blockers", [str(paths["finalGate"])]))

    pair = loaded.get("pair", {})
    checks.append(check("COMPLETE.PAIR_AUTHORITY", pair.get("pairStatus") == "SYNCED", pair.get("pairStatus"), "SYNCED", [str(paths["pair"])]))
    consistency = loaded.get("consistency", {})
    checks.append(check("COMPLETE.CROSS_ARTIFACT", consistency.get("status") == "PASS" and int(consistency.get("blockingCount", 1)) == 0, {"status": consistency.get("status"), "blockingCount": consistency.get("blockingCount")}, "PASS with zero blockers", [str(paths["consistency"])]))

    state = loaded.get("stateConsistency", {})
    checks.append(check("COMPLETE.STATE_REPLAY", state.get("status") == "PASS" and int(state.get("blockingCount", 1)) == 0, {"status": state.get("status"), "blockingCount": state.get("blockingCount")}, "PASS with zero blockers", [str(paths["stateConsistency"])]))

    semantic = loaded.get("semanticReview", {})
    semantic_passed = {
        item.get("checkId") for item in semantic.get("checks", [])
        if item.get("status") == "passed"
    }
    semantic_ok = semantic.get("verdict") == "ACCEPTED" and int(semantic.get("blockingCount", 1)) == 0 and SEMANTIC_CHECKS <= semantic_passed
    checks.append(check("COMPLETE.SEMANTIC_REVIEW", semantic_ok, {"verdict": semantic.get("verdict"), "missingAxes": sorted(SEMANTIC_CHECKS - semantic_passed)}, "ACCEPTED with all six semantic axes passed", [str(paths["semanticReview"])]))
    semantic_input = loaded.get("semanticReviewInput", {})
    with tempfile.TemporaryDirectory() as td:
        replay_semantic = review_semantic(
            semantic_input,
            paths["semanticReviewInput"],
            Path(td) / "semantic-review.log",
            semantic.get("reviewPlanId"),
            semantic.get("targetHandoffId"),
        )
    semantic_bound = replay_semantic.get("verdict") == semantic.get("verdict") and replay_semantic.get("blockingCount") == semantic.get("blockingCount")
    checks.append(check("COMPLETE.SEMANTIC_SOURCE_BINDING", semantic_bound, {"recomputedVerdict": replay_semantic.get("verdict"), "recordedVerdict": semantic.get("verdict")}, "stored semantic result replays from its frozen input", [str(paths["semanticReviewInput"]), str(paths["semanticReview"])]))

    research_errors: list[str] = []
    for index, record in enumerate(research):
        research_errors.extend(validate_research_record(record, f"research[{index}]"))
    checks.append(check("COMPLETE.RESEARCH_EVIDENCE", bool(research) and not research_errors, {"records": len(research), "errors": research_errors}, "at least one schema-valid Research Record", [str(path) for path in research_paths] or evidence_refs))

    recovery = loaded.get("recoveryReport", {})
    checks.append(check("COMPLETE.RECOVERY", recovery.get("status") == "PASS" and not recovery.get("errors"), {"status": recovery.get("status"), "errors": recovery.get("errors")}, "PASS with no recovery errors", [str(paths["recoveryReport"])]))

    benchmark = loaded.get("qualityBenchmark", {})
    replay_benchmark = evaluate_benchmark(loaded.get("qualityBenchmarkInput", {}), paths["qualityBenchmarkInput"])
    benchmark_bound = all(
        replay_benchmark.get(key) == benchmark.get(key)
        for key in ("status", "productionEligible", "dataClassification", "sampleCount", "productionSampleCount", "blockingCount")
    )
    benchmark_ok = benchmark.get("status") == "PASS" and int(benchmark.get("blockingCount", 1)) == 0 and benchmark_bound
    if mode == "PRODUCTION":
        benchmark_ok = benchmark_ok and replay_benchmark.get("dataClassification") == "REAL" and replay_benchmark.get("productionEligible") is True
    checks.append(check("COMPLETE.P0_5_SOURCE_BINDING", benchmark_bound, {"recomputedStatus": replay_benchmark.get("status"), "recordedStatus": benchmark.get("status")}, "stored benchmark result replays from its frozen input", [str(paths["qualityBenchmarkInput"]), str(paths["qualityBenchmark"])]))
    checks.append(check("COMPLETE.P0_5_BENCHMARK", benchmark_ok, {"status": replay_benchmark.get("status"), "classification": replay_benchmark.get("dataClassification"), "productionEligible": replay_benchmark.get("productionEligible"), "samples": replay_benchmark.get("sampleCount")}, "PASS and production-eligible 3..5 real samples in PRODUCTION mode", [str(paths["qualityBenchmarkInput"]), str(paths["qualityBenchmark"])]))

    handoff = loaded.get("handoff", {})
    handoff_errors: list[str] = []
    for key in ("decisions", "openFindings", "unknowns"):
        if handoff.get(key):
            handoff_errors.append(f"{key} must be empty")
    for index, artifact in enumerate(handoff.get("artifacts", [])):
        artifact_path = Path(artifact.get("path", ""))
        if not artifact_path.is_absolute():
            artifact_path = paths["handoff"].parent / artifact_path
        artifact_path = artifact_path.resolve()
        if not artifact_path.exists():
            handoff_errors.append(f"artifacts[{index}] missing")
        elif digest(artifact_path) != artifact.get("sha256"):
            handoff_errors.append(f"artifacts[{index}] hash mismatch")
    checks.append(check("COMPLETE.HANDOFF", not handoff_errors, handoff_errors, "no open decisions/findings/unknowns and every artifact hash matches", [str(paths["handoff"])]))

    replay = data["replay"]
    replay_ok = replay.get("consistent") is True and len(set(replay.get("replayRunSha256", []))) == 1 and bool(replay.get("replayRunSha256"))
    checks.append(check("COMPLETE.REPLAY", replay_ok, {"consistent": replay.get("consistent"), "replayHashes": replay.get("replayRunSha256")}, "identical replay hashes and consistent=true", [str(source_path.resolve())]))

    failed = [item["checkId"] for item in checks if item["status"] == "failed"]
    if failed:
        status = "BLOCKED"
    elif mode == "PRODUCTION":
        status = "COMPLETE"
    else:
        status = "BASELINE_READY"
    object_hashes = {path.name: digest(path) for path in list(paths.values()) + research_paths if path.exists()}
    metrics = {
        "evidenceFiles": len(object_hashes),
        "researchRecords": len(research),
        "semanticAxes": len(SEMANTIC_CHECKS & semantic_passed),
        "benchmarkSamples": benchmark.get("sampleCount", 0),
        "benchmarkProductionSamples": benchmark.get("productionSampleCount", 0),
        "benchmarkRecall": (benchmark.get("metrics") or {}).get("findingRecall"),
        "benchmarkReplayConsistency": (benchmark.get("metrics") or {}).get("replayConsistency"),
    }
    return {
        "schemaVersion": 1,
        "gateId": data["gateId"],
        "workflowId": data["workflowId"],
        "mode": mode,
        "status": status,
        "productionEligible": status == "COMPLETE",
        "checks": checks,
        "blockingCount": len(failed),
        "metrics": metrics,
        "objectHashes": object_hashes,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = evaluate(load(args.input), args.input.resolve(), args.repo_root.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "blockingCount": result["blockingCount"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] in {"COMPLETE", "BASELINE_READY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
