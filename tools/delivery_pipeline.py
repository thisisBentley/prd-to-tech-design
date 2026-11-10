#!/usr/bin/env python3
"""Unified Delivery pipeline: PRD core, full artifacts, semantic recheck and Handoff."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAIR_PROFILES = {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path, expect_zero: bool = True) -> dict[str, Any]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    result = {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "result": payload}
    if expect_zero and process.returncode != 0:
        raise RuntimeError(f"command failed ({process.returncode}): {' '.join(argv)}\n{process.stdout}\n{process.stderr}")
    return result


def add_semantic_review_task(root: Path, plan_path: Path, workflow_id: str, review_path: Path, coverage_path: Path, input_path: Path) -> str:
    plan = load(plan_path)
    task_id = "SEMANTIC-FINAL-PACKAGE-REVIEW"
    existing = next((task for task in plan.get("tasks", []) if task.get("taskId") == task_id), None)
    result_path = root / ".agents" / "results" / f"{task_id}.result.json"
    envelope = {
        "schemaVersion": 1,
        "status": "SUCCEEDED",
        "taskId": task_id,
        "role": "semantic-consistency-reviewer",
        "reviewResultPath": str(review_path.resolve()),
        "semanticReviewInputPath": str(input_path.resolve()),
        "semanticCoveragePath": str(coverage_path.resolve()),
        "outputs": [{"path": str(review_path.resolve()), "kind": "review-result"}, {"path": str(input_path.resolve()), "kind": "semantic-evidence-ledger"}],
        "evidenceRefs": [str(input_path.resolve()), str(coverage_path.resolve())],
    }
    save(result_path, envelope)
    if existing is None:
        dependencies = [task["taskId"] for task in plan.get("tasks", []) if task.get("status") == "SUCCEEDED" and task.get("taskId") in {"PRD-PRODUCE", "FINDING-CONSOLIDATE"}]
        existing = {
            "taskId": task_id,
            "role": "semantic-consistency-reviewer",
            "kind": "reviewer",
            "dependencies": dependencies,
            "readScope": ["01-delivery/**", ".agents/**"],
            "writeScope": [".agents/reviews"],
            "expectedOutputs": ["Final Semantic Consistency Review"],
            "required": True,
        }
        plan.setdefault("tasks", []).append(existing)
    existing.update({"status": "SUCCEEDED", "resultPath": str(result_path.resolve()), "completedAt": datetime.now(timezone.utc).isoformat(), "reviewVerdict": load(review_path).get("verdict"), "reviewBlockingCount": load(review_path).get("blockingCount", 0)})
    save(plan_path, plan)
    return task_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-name", required=True)
    parser.add_argument("--requirement-id")
    parser.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"], default="PRD_ONLY")
    parser.add_argument("--prototype-status", choices=["TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"], default="NOT_TRIGGERED")
    parser.add_argument("--ui-ownership", choices=["LOCAL", "EXTERNAL", "NONE", "UNKNOWN"], default="NONE")
    parser.add_argument("--worker", type=Path, default=Path(__file__).resolve().parent / "deterministic_worker.py")
    parser.add_argument("--runtime", choices=["noop", "process", "codex"], default="noop")
    parser.add_argument("--semantic-input", type=Path)
    parser.add_argument("--research-package", type=Path)
    parser.add_argument("--research-request", type=Path)
    parser.add_argument("--research-adapters", type=Path)
    parser.add_argument("--benchmark-input", type=Path)
    parser.add_argument("--producer-mode", choices=["deterministic", "provided", "semantic"], default="deterministic")
    parser.add_argument("--artifact-source-dir", type=Path, help="Externally produced Prototype/Overview/Jira artifacts to validate and package.")
    parser.add_argument("--comparison-run-root", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    root = args.run_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    py = sys.executable
    state_path = root / ".agents" / "orchestration.json"
    if not state_path.exists():
        run([py, str(scripts / "orchestrate.py"), "init", "--run-root", str(root), "--workflow-id", args.workflow_id, "--requirement-name", args.requirement_name, "--requirement-id", args.requirement_id or "", "--artifact-profile", args.artifact_profile, "--prototype-status", args.prototype_status, "--ui-ownership", args.ui_ownership], root)
    if bool(args.research_request) != bool(args.research_adapters):
        print(json.dumps({"status": "RESEARCH_CONFIG_BLOCKED", "error": "--research-request and --research-adapters must be supplied together"}, ensure_ascii=False))
        return 1
    research_query_result_path = root / ".agents" / "research" / "query-result.json"
    if args.research_request:
        query_run = run([
            py, str(scripts / "run_research_queries.py"),
            "--request", str(args.research_request.resolve()),
            "--adapters", str(args.research_adapters.resolve()),
            "--out", str(research_query_result_path),
        ], root, expect_zero=False)
        if query_run.get("result", {}).get("status") == "BLOCKED":
            print(json.dumps({"status": "RESEARCH_QUERY_BLOCKED", "query": query_run}, ensure_ascii=False, indent=2))
            return 1
    if args.research_package:
        import_result_path = root / ".agents" / "research" / "import-result.json"
        import_run = run([py, str(scripts / "import_research_package.py"), "--package", str(args.research_package.resolve()), "--run-root", str(root), "--out", str(import_result_path), "--force"], root, expect_zero=False)
        if import_run.get("result", {}).get("status") != "PASS":
            print(json.dumps({"status": "RESEARCH_IMPORT_BLOCKED", "import": import_run}, ensure_ascii=False, indent=2))
            return 1
    plan_path = root / ".agents" / "delivery-plan.json"
    if not plan_path.exists():
        run([py, str(scripts / "orchestrate.py"), "build-delivery-plan", "--run-root", str(root), "--out", str(plan_path)], root)
    core = run([py, str(scripts / "delivery_loop.py"), "--run-root", str(root), "--plan", str(plan_path), "--requirement", str(args.requirement.resolve()), "--worker", str(args.worker.resolve()), "--runtime", args.runtime, "--stop-after-core", "--timeout", str(args.timeout)], root, expect_zero=False)
    if core.get("result", {}).get("status") not in {"PRD_CORE_READY", "M1_CONTRACT_COMPLETE"}:
        print(json.dumps({"status": "PRD_CORE_BLOCKED", "core": core}, ensure_ascii=False, indent=2))
        return 1

    plan = load(plan_path)
    prd = root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
    if not prd.exists():
        print(json.dumps({"status": "PRD_MISSING", "path": str(prd)}, ensure_ascii=False))
        return 1
    delivery_dir = root / "01-delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    final_prd = delivery_dir / "PRD_DELIVERY.md"
    if final_prd.resolve() != prd.resolve():
        shutil.copyfile(prd, final_prd)
    overview = delivery_dir / "Overview.html"
    jira = delivery_dir / "Jira_Description.md"
    m2 = root / ".agents" / "m2"
    prototype = None
    manifest = None
    pair_path = root / ".agents" / "quality" / "pair-not-applicable.json"
    consistency_path = root / ".agents" / "quality" / "consistency-not-applicable.json"
    runtime_path = root / ".agents" / "quality" / "runtime-not-applicable.json"
    overview_gate_path = root / ".agents" / "quality" / "overview-gate.json"
    final_gate_path = root / ".agents" / "quality" / "final-package-gate.json"
    source_dir = args.artifact_source_dir.resolve() if args.artifact_source_dir else None
    if source_dir:
        required_sources = ["Overview.html", "Jira_Description.md"]
        if args.artifact_profile in PAIR_PROFILES:
            required_sources += ["Prototype.html", "prototype-manifest.json"]
        missing_sources = [name for name in required_sources if not (source_dir / name).is_file()]
        if missing_sources:
            print(json.dumps({"status": "ARTIFACT_SOURCE_BLOCKED", "missing": missing_sources, "sourceDir": str(source_dir)}, ensure_ascii=False))
            return 1
        if args.producer_mode == "deterministic":
            args.producer_mode = "provided"
    if args.artifact_profile in PAIR_PROFILES:
        m2.mkdir(parents=True, exist_ok=True)
        if source_dir:
            prototype = m2 / "Prototype.html"
            manifest = m2 / "prototype-manifest.json"
            overview = m2 / "Overview.html"
            shutil.copyfile(source_dir / "Prototype.html", prototype)
            shutil.copyfile(source_dir / "prototype-manifest.json", manifest)
            shutil.copyfile(source_dir / "Overview.html", overview)
            manifest_data = load(manifest, {})
            if manifest_data.get("prototypeHash") != digest(prototype):
                print(json.dumps({"status": "ARTIFACT_SOURCE_BLOCKED", "error": "prototype manifest hash does not match supplied Prototype.html"}, ensure_ascii=False))
                return 1
            previous_manifest = m2 / "previous-manifest.json"
            shutil.copyfile(manifest, previous_manifest)
            m2_run = run([
                py, str(scripts / "artifact_sync_loop.py"), "--workflow-id", args.workflow_id,
                "--prd", str(final_prd), "--prototype", str(prototype), "--manifest", str(manifest),
                "--previous-manifest", str(previous_manifest), "--overview", str(overview),
                "--from-revision", "r1", "--to-revision", "r1", "--m2-complete", "--out-dir", str(m2),
            ], root, expect_zero=False)
        else:
            m2_run = run([py, str(scripts / "m2_pipeline.py"), "--workflow-id", args.workflow_id, "--prd", str(final_prd), "--out-dir", str(m2), "--revision", "r1"], root, expect_zero=False)
        if m2_run.get("result", {}).get("status") != "M2_FINAL_PASS":
            print(json.dumps({"status": "M2_BLOCKED", "m2": m2_run}, ensure_ascii=False, indent=2))
            return 1
        prototype = m2 / "Prototype.html"
        manifest = m2 / "prototype-manifest.json"
        overview = m2 / "Overview.html"
        pair_path = m2 / "artifact-pair.json"
        consistency_path = m2 / "artifact-consistency.json"
        runtime_path = m2 / "prototype-runtime.json"
        overview_gate_path = m2 / "overview-projection-gate.json"
        final_gate_path = m2 / "final-delivery-gate.json"
    else:
        if source_dir:
            shutil.copyfile(source_dir / "Overview.html", overview)
        else:
            run([py, str(scripts / "generate_prd_overview.py"), "--prd", str(final_prd), "--revision", "r1", "--out", str(overview)], root)
        save(pair_path, {"schemaVersion": 1, "pairId": "not-applicable", "workflowId": args.workflow_id, "artifactProfile": args.artifact_profile, "prdRevision": "r1", "prototypeRevision": "r1", "pairStatus": "NOT_APPLICABLE", "prdPath": str(final_prd), "prdHash": digest(final_prd), "prototypePath": "", "prototypeHash": "0" * 64, "createdAt": datetime.now(timezone.utc).isoformat(), "updatedAt": datetime.now(timezone.utc).isoformat()})
        save(consistency_path, {"schemaVersion": 1, "workflowId": args.workflow_id, "status": "PASS", "blockingCount": 0, "checks": [], "findings": [], "checkedAt": datetime.now(timezone.utc).isoformat()})
        save(runtime_path, {"status": "PASS", "consoleErrors": 0})
        save(overview_gate_path, {"schemaVersion": 1, "status": "PASS", "blockingCount": 0, "checks": [], "findings": [], "checkedAt": datetime.now(timezone.utc).isoformat()})
        save(final_gate_path, {"schemaVersion": 2, "gate": "Q1", "result": "PASS", "blockingCount": 0, "findings": [], "checkedAt": datetime.now(timezone.utc).isoformat()})
    if source_dir:
        shutil.copyfile(source_dir / "Jira_Description.md", jira)
    else:
        run([py, str(scripts / "generate_jira_description.py"), "--prd", str(final_prd), "--requirement-key", args.requirement_id or args.workflow_id, "--out", str(jira)], root)

    capability_path = root / ".agents" / "context" / "capability-context.json"
    semantic_input_path = args.semantic_input.resolve() if args.semantic_input else root / ".agents" / "context" / "semantic-final-input.json"
    if args.semantic_input:
        shutil.copyfile(args.semantic_input, semantic_input_path)
    else:
        cmd = [py, str(scripts / "build_semantic_evidence.py"), "--prd", str(final_prd), "--workflow-id", args.workflow_id, "--revision", "r1", "--out", str(semantic_input_path)]
        if prototype: cmd.extend(["--prototype", str(prototype)])
        if manifest: cmd.extend(["--manifest", str(manifest)])
        if capability_path.exists(): cmd.extend(["--capability-context", str(capability_path)])
        run(cmd, root)
    coverage_path = root / ".agents" / "reviews" / "SEMANTIC-FINAL-PACKAGE-REVIEW.coverage.json"
    coverage_cmd = [py, str(scripts / "build_semantic_coverage.py"), "--semantic-input", str(semantic_input_path), "--prd", str(final_prd), "--out", str(coverage_path)]
    if prototype: coverage_cmd.extend(["--prototype", str(prototype)])
    if manifest: coverage_cmd.extend(["--manifest", str(manifest)])
    if capability_path.exists(): coverage_cmd.extend(["--capability-context", str(capability_path)])
    coverage_run = run(coverage_cmd, root, expect_zero=False)
    review_path = root / ".agents" / "reviews" / "SEMANTIC-FINAL-PACKAGE-REVIEW.review.json"
    review_run = run([py, str(scripts / "semantic_consistency_review.py"), "--input", str(semantic_input_path), "--coverage", str(coverage_path), "--out", str(review_path)], root, expect_zero=False)
    if review_run.get("result", {}).get("status") != "ACCEPTED":
        print(json.dumps({"status": "SEMANTIC_BLOCKED", "coverage": coverage_run.get("result"), "review": review_run.get("result"), "semanticInput": str(semantic_input_path), "reviewPath": str(review_path)}, ensure_ascii=False, indent=2))
        return 1
    add_semantic_review_task(root, plan_path, args.workflow_id, review_path, coverage_path, semantic_input_path)
    artifacts = [
        {"kind": "PRD", "path": str(final_prd.resolve()), "sha256": digest(final_prd)},
        {"kind": "OVERVIEW", "path": str(overview.resolve()), "sha256": digest(overview)},
        {"kind": "JIRA_DESCRIPTION", "path": str(jira.resolve()), "sha256": digest(jira)},
    ]
    if prototype:
        artifacts.append({"kind": "PROTOTYPE", "path": str(prototype.resolve()), "sha256": digest(prototype)})
    artifact_quality_path = root / ".agents" / "quality" / "artifact-quality.json"
    prd_producer_result = load(root / ".agents" / "results" / "PRD-PRODUCE.result.json", {})
    prd_producer_mode = prd_producer_result.get("producerMode", "unknown")
    quality_cmd = [py, str(scripts / "validate_delivery_artifacts.py"), "--prd", str(final_prd), "--artifact-profile", args.artifact_profile, "--producer-mode", args.producer_mode, "--prd-producer-mode", prd_producer_mode, "--overview", str(overview), "--jira", str(jira), "--out", str(artifact_quality_path)]
    if prototype:
        quality_cmd.extend(["--prototype", str(prototype), "--manifest", str(manifest)])
    artifact_quality_run = run(quality_cmd, root, expect_zero=False)
    if artifact_quality_run.get("result", {}).get("status") != "PASS":
        print(json.dumps({"status": "ARTIFACT_QUALITY_BLOCKED", "quality": artifact_quality_run}, ensure_ascii=False, indent=2))
        return 1
    package_evidence = {
        "schemaVersion": 1, "workflowId": args.workflow_id, "artifactProfile": args.artifact_profile, "revision": "r1",
        "artifacts": artifacts,
        "artifactQualityPath": str(artifact_quality_path),
        **({"prototypeManifestPath": str(manifest.resolve())} if manifest else {}),
        "gates": {
            "pair": load(pair_path, {}), "consistency": load(consistency_path, {}), "runtime": load(runtime_path, {}),
            "overview": load(overview_gate_path, {}), "final": load(final_gate_path, {}), "semanticReview": load(review_path, {}),
        },
        "technicalGapsPath": str((root / ".agents" / "context" / "technical-gaps.json").resolve()),
        **({"researchQueryResult": str(research_query_result_path)} if research_query_result_path.exists() else {}),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    save(root / ".agents" / "quality" / "package-evidence.json", package_evidence)
    finalize_worker = scripts / "deterministic_worker.py"
    full = run([py, str(scripts / "delivery_loop.py"), "--run-root", str(root), "--plan", str(plan_path), "--requirement", str(args.requirement.resolve()), "--worker", str(finalize_worker), "--runtime", "noop", "--timeout", str(args.timeout)], root, expect_zero=False)
    status = full.get("result", {}).get("status")
    if status != "M1_CONTRACT_COMPLETE":
        print(json.dumps({"status": "FINALIZATION_BLOCKED", "core": core.get("result"), "full": full, "artifactPhase": "PASS", "semanticInput": str(semantic_input_path)}, ensure_ascii=False, indent=2))
        return 1
    handoff = root / ".agents" / "handoffs" / "delivery-ready.handoff.json"
    quality_exit = root / ".agents" / "quality" / "delivery-quality-exit.json"
    state_consistency = root / ".agents" / "quality" / "state-consistency.json"
    run([py, str(scripts / "validate_delivery_state_consistency.py"), "--run-root", str(root), "--plan", str(plan_path), "--out", str(state_consistency)], root)
    benchmark_input = args.benchmark_input.resolve() if args.benchmark_input else root / ".agents" / "quality" / "single-run-benchmark-input.json"
    if args.benchmark_input:
        shutil.copyfile(args.benchmark_input, benchmark_input)
        data_classification = load(benchmark_input).get("dataClassification", "SYNTHETIC")
    else:
        save(benchmark_input, {
            "schemaVersion": 1, "benchmarkId": f"{args.workflow_id}-single-run", "dataClassification": "SYNTHETIC",
            "thresholds": {"minimumSamples": 3, "maximumSamples": 5, "minimumFindingRecall": 1.0, "maximumFalsePositiveRate": 0.05, "minimumReplayConsistency": 1.0},
            "samples": [{
                "schemaVersion": 1, "sampleId": args.workflow_id, "profile": args.artifact_profile,
                "caseTypes": ["SIMPLE_PRD_ONLY"], "productionEligible": False, "runRoot": str(root),
                "plan": str(plan_path), "qualityExit": str(quality_exit), "finalGate": str(final_gate_path),
                "pair": str(pair_path), "overviewGate": str(overview_gate_path), "runtimeEvidence": str(runtime_path),
                "prd": str(final_prd), "groundTruthFindingIds": [],
            }],
        })
        data_classification = "SYNTHETIC"
    benchmark_dir = root / ".agents" / "quality" / "benchmark"
    run([py, str(scripts / "run_quality_benchmark.py"), "--samples", str(benchmark_input), "--out-dir", str(benchmark_dir)], root, expect_zero=False)
    benchmark_result = benchmark_dir / "result.json"
    benchmark_data = benchmark_dir / "benchmark.json"
    research_index_path = root / ".agents" / "research" / "index.json"
    research_index = load(research_index_path, {"schemaVersion": 1, "workflowId": args.workflow_id, "records": [], "technicalGapsPath": str((root / ".agents" / "context" / "technical-gaps.json").resolve())})
    research_records = []
    for item in research_index.get("records", []):
        path = Path(item.get("path", ""))
        if path.exists(): research_records.append(str(path))
    recover_path = root / ".agents" / "recovery" / "latest.json"
    if not recover_path.exists():
        run([py, str(scripts / "recover_delivery_run.py"), "--run-root", str(root), "--plan", str(plan_path), "--out", str(recover_path)], root, expect_zero=False)
    complete_input = root / ".agents" / "quality" / "delivery-complete-input.json"
    evidence_paths = [quality_exit, final_gate_path, pair_path, consistency_path, state_consistency, benchmark_result, benchmark_data, review_path, semantic_input_path, recover_path, handoff, research_index_path, artifact_quality_path, root / ".agents" / "quality" / "package-evidence.json"]
    manifest = [{"path": path.name, "sha256": digest(path)} for path in evidence_paths if path.exists()]
    input_manifest_sha = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay_hashes = [input_manifest_sha]
    replay_consistent = False
    if args.comparison_run_root:
        comparison = args.comparison_run_root.resolve()
        comparison_paths = [comparison / ".agents" / "quality" / "delivery-quality-exit.json", comparison / ".agents" / "handoffs" / "delivery-ready.handoff.json", comparison / "01-delivery" / "PRD_DELIVERY.md"]
        comparison_manifest = [{"path": path.name, "sha256": digest(path)} for path in comparison_paths if path.exists()]
        replay_hashes.append(hashlib.sha256(json.dumps(comparison_manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
        replay_consistent = len(comparison_manifest) == len(comparison_paths) and replay_hashes[0] == replay_hashes[1]
    else:
        replay_hashes.append("0" * 64)
    save(complete_input, {
        "schemaVersion": 1, "gateId": f"{args.workflow_id}-complete", "workflowId": args.workflow_id,
        "mode": "PRODUCTION" if data_classification == "REAL" else "BASELINE",
        "evidence": {
            "deliveryQualityExit": str(quality_exit), "finalGate": str(final_gate_path), "pair": str(pair_path),
            "consistency": str(consistency_path), "stateConsistency": str(state_consistency),
            "qualityBenchmark": str(benchmark_result), "qualityBenchmarkInput": str(benchmark_data),
            "semanticReview": str(review_path), "semanticReviewInput": str(semantic_input_path),
            "recoveryReport": str(recover_path), "handoff": str(handoff), "researchIndex": str(research_index_path),
            "packageEvidence": str(root / ".agents" / "quality" / "package-evidence.json"),
            "researchRecords": research_records,
        },
        "replay": {
            "inputManifestSha256": input_manifest_sha,
            "replayRunSha256": replay_hashes,
            "consistent": replay_consistent,
        },
    })
    complete_result = root / ".agents" / "quality" / "delivery-complete-result.json"
    complete_run = run([py, str(scripts / "delivery_complete_gate.py"), "--input", str(complete_input), "--out", str(complete_result)], root, expect_zero=False)
    report = {
        "schemaVersion": 1,
        "status": "PACKAGE_READY",
        "workflowId": args.workflow_id,
        "artifactProfile": args.artifact_profile,
        "artifacts": artifacts,
        "semanticReview": str(review_path),
        "qualityExit": str(quality_exit),
        "handoff": str(handoff),
        "benchmarkResult": str(benchmark_result),
        "completeGateStatus": load(complete_result, {}).get("status", "BLOCKED"),
        "completeGate": str(complete_result),
        "completeGateInvocation": complete_run,
        "artifactQuality": str(artifact_quality_path),
        "artifactQualityLevel": load(artifact_quality_path, {}).get("qualityLevel"),
        "prdProducerMode": prd_producer_mode,
        "downstreamProducerMode": args.producer_mode,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    save(root / ".agents" / "quality" / "delivery-pipeline-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
