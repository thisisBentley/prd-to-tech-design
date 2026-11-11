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
    parser.add_argument("--decision-closure", type=Path, help="Confirmed Decision Card to apply before Decision Readiness.")
    parser.add_argument("--benchmark-input", type=Path)
    parser.add_argument("--producer-mode", choices=["deterministic", "provided", "semantic"], default="deterministic")
    parser.add_argument("--artifact-source-dir", type=Path, help="Externally produced Prototype/Overview/Jira artifacts to validate and package.")
    parser.add_argument("--producer-registry", type=Path, help="Registry of semantic/provided artifact producers.")
    parser.add_argument("--runtime-evidence", type=Path, help="Real-browser runtime evidence for externally produced Prototype artifacts.")
    parser.add_argument("--browser-runner", nargs="+", help="Real browser adapter command used by M2 runtime verification.")
    parser.add_argument("--require-real-browser", action="store_true")
    parser.add_argument("--comparison-run-root", type=Path)
    parser.add_argument("--generation-contract-mode", choices=["off", "advisory", "gate"], default="advisory", help="Pre-PRD generation contract enforcement mode.")
    parser.add_argument("--semantic-decomposition-mode", choices=["off", "advisory", "gate"], default="advisory", help="Semantic unit decomposition and layered review enforcement mode.")
    parser.add_argument("--semantic-aggregate", type=Path, help="Independent semantic review aggregate for gate mode.")
    parser.add_argument("--readiness-mode", choices=["advisory", "gate"], default="gate", help="Enforce CONTENT/EVIDENCE/BUNDLE readiness at pipeline finalize.")
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
        synthesis_out = root / ".agents" / "research" / "synthesis-result.json"
        synthesis_run = run([
            py, str(scripts / "synthesize_research.py"),
            "--request", str(args.research_request.resolve()),
            "--query-result", str(research_query_result_path),
            "--run-root", str(root), "--out", str(synthesis_out),
        ], root, expect_zero=False)
        if synthesis_run.get("result", {}).get("status") != "PASS":
            print(json.dumps({"status": "RESEARCH_SYNTHESIS_BLOCKED", "synthesis": synthesis_run}, ensure_ascii=False, indent=2))
            return 1
    if args.decision_closure:
        closed = load(args.decision_closure.resolve())
        if closed.get("status") not in {"confirmed", "closed"}:
            print(json.dumps({"status": "DECISION_CLOSURE_BLOCKED", "error": "decision closure is not confirmed/closed"}, ensure_ascii=False))
            return 1
        decision_dir = root / ".agents" / "decisions"
        decision_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(args.decision_closure.resolve(), decision_dir / args.decision_closure.name)
    open_decisions = [path for path in (root / ".agents" / "decisions").glob("*.json") if load(path, {}).get("status") not in {"confirmed", "closed"}] if (root / ".agents" / "decisions").exists() else []
    if open_decisions and not args.decision_closure:
        print(json.dumps({"status": "DECISION_REQUIRED", "openDecisions": [str(path) for path in open_decisions], "next": "--decision-closure <confirmed.json> after product selection"}, ensure_ascii=False, indent=2))
        return 2
    if args.research_package:
        import_result_path = root / ".agents" / "research" / "import-result.json"
        import_run = run([py, str(scripts / "import_research_package.py"), "--package", str(args.research_package.resolve()), "--run-root", str(root), "--out", str(import_result_path), "--force"], root, expect_zero=False)
        if import_run.get("result", {}).get("status") != "PASS":
            print(json.dumps({"status": "RESEARCH_IMPORT_BLOCKED", "import": import_run}, ensure_ascii=False, indent=2))
            return 1
    plan_path = root / ".agents" / "delivery-plan.json"
    if not plan_path.exists():
        run([py, str(scripts / "orchestrate.py"), "build-delivery-plan", "--run-root", str(root), "--out", str(plan_path)], root)
    generation_contract_path = root / ".agents" / "context" / "generation-contract.json"
    generation_contract_status = "SKIPPED"
    if args.generation_contract_mode != "off":
        generation_cmd = [
            py, str(scripts / "build_generation_contract.py"), "--requirement", str(args.requirement.resolve()),
            "--workflow-id", args.workflow_id, "--requirement-id", args.requirement_id or args.workflow_id,
            "--artifact-profile", args.artifact_profile, "--out", str(generation_contract_path),
        ]
        decision_context_path = root / "01-delivery" / ".delivery" / "decision-context.json"
        if decision_context_path.exists():
            generation_cmd.extend(["--decision-context", str(decision_context_path)])
        capability_context_path = root / ".agents" / "context" / "capability-context.json"
        if capability_context_path.exists():
            generation_cmd.extend(["--capability-context", str(capability_context_path)])
        generation_run = run(generation_cmd, root, expect_zero=False)
        generation_contract_status = load(generation_contract_path, {}).get("status", "BLOCKED") if generation_contract_path.exists() else "BLOCKED"
        if args.generation_contract_mode == "gate" and generation_contract_status != "READY":
            print(json.dumps({"status": "GENERATION_CONTRACT_BLOCKED", "contractStatus": generation_contract_status, "contract": generation_run, "path": str(generation_contract_path)}, ensure_ascii=False, indent=2))
            return 1
    delivery_dir = root / "01-delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    policy_lock_path = root / ".agents" / "policy" / "policy-lock.json"
    requirement_types: list[str] = []
    if generation_contract_path.exists():
        requirement_types = list(load(generation_contract_path, {}).get("requirementTypes") or [])
    policy_cmd = [
        py, str(scripts / "build_policy_lock.py"), "--artifact-profile", args.artifact_profile,
        "--requirement-types", ",".join(requirement_types),
        "--prototype-status", args.prototype_status, "--ui-ownership", args.ui_ownership,
        "--out", str(policy_lock_path),
    ]
    policy_run = run(policy_cmd, root, expect_zero=False)
    if policy_run.get("result", {}).get("status") != "PASS":
        print(json.dumps({"status": "POLICY_LOCK_BLOCKED", "policy": policy_run}, ensure_ascii=False, indent=2))
        return 1
    delivery_policy_lock = delivery_dir / ".delivery" / "policy-lock.json"
    delivery_policy_lock.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(policy_lock_path, delivery_policy_lock)
    obligations_path = root / ".agents" / "policy" / "generation-obligations.json"
    obligations_run = run([
        py, str(scripts / "build_generation_obligations.py"), "--policy-lock", str(policy_lock_path),
        "--workflow-id", args.workflow_id, "--revision", "r1", "--out", str(obligations_path),
    ], root, expect_zero=False)
    if obligations_run.get("result", {}).get("status") != "PASS":
        print(json.dumps({"status": "GENERATION_OBLIGATIONS_BLOCKED", "obligations": obligations_run}, ensure_ascii=False, indent=2))
        return 1
    delivery_obligations = delivery_dir / ".delivery" / "generation-obligations.json"
    shutil.copyfile(obligations_path, delivery_obligations)
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
    if args.producer_registry and source_dir:
        print(json.dumps({"status": "PRODUCER_CONFIG_BLOCKED", "error": "--producer-registry and --artifact-source-dir are mutually exclusive"}, ensure_ascii=False))
        return 1
    if args.producer_registry:
        registry = load(args.producer_registry.resolve(), {})
        registered = {item.get("kind"): item for item in registry.get("producers", [])}
        if args.artifact_profile in PAIR_PROFILES:
            required_kinds = ["prototype", "overview", "jira"]
        else:
            required_kinds = ["overview", "jira"]
        missing = [kind for kind in required_kinds if kind not in registered]
        if missing:
            print(json.dumps({"status": "PRODUCER_NOT_CONFIGURED", "missing": missing, "registry": str(args.producer_registry)}, ensure_ascii=False))
            return 1
        producer_package = root / ".agents" / "producers" / "package"
        producer_package.mkdir(parents=True, exist_ok=True)
        producer_modes: set[str] = set()
        for kind in required_kinds:
            kind_out = root / ".agents" / "producers" / kind
            producer_result = root / ".agents" / "producers" / f"{kind}.result.json"
            producer_run = run([
                py, str(scripts / "run_producer.py"), "--registry", str(args.producer_registry.resolve()),
                "--kind", kind, "--workflow-id", args.workflow_id, "--revision", "r1", "--run-root", str(root),
                "--output-dir", str(kind_out), "--prd", str(final_prd), "--requirement", str(args.requirement.resolve()),
                "--out", str(producer_result),
            ], root, expect_zero=False)
            if producer_run.get("result", {}).get("status") != "PASS":
                print(json.dumps({"status": "PRODUCER_BLOCKED", "kind": kind, "run": producer_run}, ensure_ascii=False, indent=2))
                return 1
            producer_modes.add(str(producer_run.get("result", {}).get("mode", "provided")))
            for name in registered[kind].get("requiredArtifacts", []):
                shutil.copyfile(kind_out / name, producer_package / name)
            for optional in ("runtime-evidence.json", "obligation-declarations.json"):
                if (kind_out / optional).exists():
                    shutil.copyfile(kind_out / optional, producer_package / optional)
            declaration_source = kind_out / "obligation-declarations.json"
            if declaration_source.exists():
                declaration_target = root / ".agents" / "policy" / "declarations" / f"{kind}.json"
                declaration_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(declaration_source, declaration_target)
        args.producer_mode = next(iter(producer_modes)) if len(producer_modes) == 1 else "provided"
        source_dir = producer_package
    source_runtime = source_dir / "runtime-evidence.json" if source_dir and (source_dir / "runtime-evidence.json").exists() else None
    if source_runtime:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_runtime, runtime_path)
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
            m2_cmd = [
                py, str(scripts / "artifact_sync_loop.py"), "--workflow-id", args.workflow_id,
                "--prd", str(final_prd), "--prototype", str(prototype), "--manifest", str(manifest),
                "--previous-manifest", str(previous_manifest), "--overview", str(overview),
                "--from-revision", "r1", "--to-revision", "r1", "--m2-complete", "--out-dir", str(m2),
            ]
            if args.browser_runner:
                m2_cmd.extend(["--browser-runner", *args.browser_runner])
            if args.require_real_browser:
                m2_cmd.append("--require-real-browser")
            inherited_runtime = args.runtime_evidence or (source_dir / "runtime-evidence.json" if source_dir and (source_dir / "runtime-evidence.json").exists() else None)
            if inherited_runtime:
                m2_cmd.extend(["--runtime-evidence", str(inherited_runtime.resolve())])
            m2_run = run(m2_cmd, root, expect_zero=False)
        else:
            m2_cmd = [py, str(scripts / "m2_pipeline.py"), "--workflow-id", args.workflow_id, "--prd", str(final_prd), "--out-dir", str(m2), "--revision", "r1"]
            if args.browser_runner:
                m2_cmd.extend(["--browser-runner", *args.browser_runner])
            if args.require_real_browser:
                m2_cmd.append("--require-real-browser")
            inherited_runtime = args.runtime_evidence or (source_dir / "runtime-evidence.json" if source_dir and (source_dir / "runtime-evidence.json").exists() else None)
            if inherited_runtime:
                m2_cmd.extend(["--runtime-evidence", str(inherited_runtime.resolve())])
            m2_run = run(m2_cmd, root, expect_zero=False)
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
    runtime_source = args.runtime_evidence.resolve() if args.runtime_evidence else (source_dir / "runtime-evidence.json" if source_dir and (source_dir / "runtime-evidence.json").exists() else None)
    if runtime_source:
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(runtime_source, runtime_path)
    if source_dir:
        shutil.copyfile(source_dir / "Jira_Description.md", jira)
    else:
        run([py, str(scripts / "generate_jira_description.py"), "--prd", str(final_prd), "--requirement-key", args.requirement_id or args.workflow_id, "--out", str(jira)], root)

    capability_path = root / ".agents" / "context" / "capability-context.json"
    semantic_input_path = args.semantic_input.resolve() if args.semantic_input else root / ".agents" / "context" / "semantic-final-input.json"
    if args.producer_registry and not args.semantic_input:
        registry = load(args.producer_registry.resolve(), {})
        registered = {item.get("kind"): item for item in registry.get("producers", [])}
        if "semantic-evidence" in registered:
            semantic_out_dir = root / ".agents" / "producers" / "semantic-evidence"
            semantic_producer_result = root / ".agents" / "producers" / "semantic-evidence.result.json"
            semantic_producer_cmd = [
                py, str(scripts / "run_producer.py"), "--registry", str(args.producer_registry.resolve()),
                "--kind", "semantic-evidence", "--workflow-id", args.workflow_id, "--revision", "r1",
                "--run-root", str(root), "--output-dir", str(semantic_out_dir), "--prd", str(final_prd),
                "--requirement", str(args.requirement.resolve()), "--out", str(semantic_producer_result),
            ]
            if prototype:
                semantic_producer_cmd.extend(["--prototype", str(prototype)])
            semantic_run = run(semantic_producer_cmd, root, expect_zero=False)
            if semantic_run.get("result", {}).get("status") != "PASS":
                print(json.dumps({"status": "SEMANTIC_PRODUCER_BLOCKED", "run": semantic_run}, ensure_ascii=False, indent=2))
                return 1
            shutil.copyfile(semantic_out_dir / "semantic-evidence.json", semantic_input_path)
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

    semantic_model_path = root / ".agents" / "semantics" / "delivery-semantic-model.json"
    semantic_integration_path = root / ".agents" / "semantics" / "semantic-integration-review.json"
    semantic_jobs_dir = root / ".agents" / "semantics" / "review-jobs"
    semantic_jobs_manifest = semantic_jobs_dir / "job-manifest.json"
    semantic_aggregate_path = root / ".agents" / "semantics" / "semantic-aggregate.json"
    semantic_decomposition_status = "SKIPPED"
    semantic_aggregate_status = "SKIPPED"
    semantic_decomposition_run = None
    if args.semantic_decomposition_mode != "off":
        semantic_model_cmd = [
            py, str(scripts / "build_delivery_semantic_model.py"), "--prd", str(final_prd),
            "--workflow-id", args.workflow_id, "--revision", "r1", "--artifact-profile", args.artifact_profile,
            "--out", str(semantic_model_path),
        ]
        if generation_contract_path.exists():
            semantic_model_cmd.extend(["--generation-contract", str(generation_contract_path)])
        if prototype:
            semantic_model_cmd.extend(["--prototype", str(prototype)])
        if manifest:
            semantic_model_cmd.extend(["--manifest", str(manifest)])
        semantic_model_run = run(semantic_model_cmd, root, expect_zero=False)
        semantic_review_run = run([py, str(scripts / "review_delivery_semantics.py"), "--model", str(semantic_model_path), "--out", str(semantic_integration_path)], root, expect_zero=False)
        jobs_run = run([py, str(scripts / "export_semantic_review_jobs.py"), "--model", str(semantic_model_path), "--out-dir", str(semantic_jobs_dir)], root, expect_zero=False)
        semantic_decomposition_run = {"model": semantic_model_run, "review": semantic_review_run, "jobs": jobs_run}
        semantic_decomposition_status = load(semantic_integration_path, {}).get("status", "BLOCKED") if semantic_integration_path.exists() else "BLOCKED"
        if args.semantic_aggregate:
            if not args.semantic_aggregate.exists():
                print(json.dumps({"status": "SEMANTIC_AGGREGATE_BLOCKED", "error": "semantic aggregate not found", "path": str(args.semantic_aggregate)}, ensure_ascii=False))
                return 1
            semantic_aggregate_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.semantic_aggregate.resolve(), semantic_aggregate_path)
            semantic_aggregate_status = load(semantic_aggregate_path, {}).get("status", "BLOCKED")
        if args.semantic_decomposition_mode == "gate":
            if semantic_decomposition_status not in {"PASS", "PASS_WITH_NONBLOCKING"}:
                print(json.dumps({"status": "SEMANTIC_DECOMPOSITION_BLOCKED", "review": semantic_review_run, "model": str(semantic_model_path), "jobs": str(semantic_jobs_manifest)}, ensure_ascii=False, indent=2))
                return 1
            if semantic_aggregate_status not in {"PASS", "PASS_WITH_NONBLOCKING"}:
                print(json.dumps({"status": "SEMANTIC_AGGREGATE_BLOCKED", "review": semantic_review_run, "aggregateStatus": semantic_aggregate_status, "model": str(semantic_model_path), "jobs": str(semantic_jobs_manifest)}, ensure_ascii=False, indent=2))
                return 1
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
    quality_cmd = [py, str(scripts / "validate_delivery_artifacts.py"), "--prd", str(final_prd), "--artifact-profile", args.artifact_profile, "--producer-mode", args.producer_mode, "--prd-producer-mode", prd_producer_mode, "--overview", str(overview), "--jira", str(jira), "--runtime", str(runtime_path), "--out", str(artifact_quality_path)]
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
        "runtimeEvidencePath": str(runtime_path),
        **({"prototypeManifestPath": str(manifest.resolve())} if manifest else {}),
        "gates": {
            "pair": load(pair_path, {}), "consistency": load(consistency_path, {}), "runtime": load(runtime_path, {}),
            "overview": load(overview_gate_path, {}), "final": load(final_gate_path, {}), "semanticReview": load(review_path, {}),
        },
        "technicalGapsPath": str((root / ".agents" / "context" / "technical-gaps.json").resolve()),
        **({"researchQueryResult": str(research_query_result_path)} if research_query_result_path.exists() else {}),
        **({"generationContract": str(generation_contract_path)} if generation_contract_path.exists() else {}),
        **({"semanticModel": str(semantic_model_path)} if semantic_model_path.exists() else {}),
        **({"semanticIntegrationReview": str(semantic_integration_path)} if semantic_integration_path.exists() else {}),
        **({"semanticReviewJobs": str(semantic_jobs_manifest)} if semantic_jobs_manifest.exists() else {}),
        **({"semanticAggregate": str(semantic_aggregate_path)} if semantic_aggregate_path.exists() else {}),
        "policyLockPath": str(delivery_policy_lock),
        "policyLockSha256": digest(delivery_policy_lock),
        "generationObligationsPath": str(delivery_obligations),
        "generationObligationsSha256": digest(delivery_obligations),
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
    declarations_path = root / ".agents" / "policy" / "obligation-declarations.json"
    collect_cmd = [
        py, str(scripts / "collect_obligation_declarations.py"), "--obligations", str(obligations_path),
        "--declarations-dir", str(root / ".agents" / "policy" / "declarations"), "--out", str(declarations_path),
    ]
    if source_dir and (source_dir / "obligation-declarations.json").exists():
        collect_cmd.extend(["--input", str(source_dir / "obligation-declarations.json")])
    declaration_collect_run = run(collect_cmd, root, expect_zero=False)
    declarations_validation_path = root / ".agents" / "policy" / "obligation-declarations-validation.json"
    declaration_validation_run = run([
        py, str(scripts / "validate_obligation_declarations.py"), "--obligations", str(obligations_path),
        "--declarations", str(declarations_path), "--out", str(declarations_validation_path),
    ], root, expect_zero=False)
    delivery_declarations = delivery_dir / ".delivery" / "obligation-declarations.json"
    shutil.copyfile(declarations_path, delivery_declarations)
    delivery_declarations_validation = delivery_dir / ".delivery" / "obligation-declarations-validation.json"
    shutil.copyfile(declarations_validation_path, delivery_declarations_validation)
    package_evidence_path = root / ".agents" / "quality" / "package-evidence.json"
    package_evidence = load(package_evidence_path, package_evidence)
    package_evidence.update({
        "obligationDeclarationsPath": str(delivery_declarations),
        "obligationDeclarationsSha256": digest(delivery_declarations),
        "obligationDeclarationsValidationPath": str(delivery_declarations_validation),
    })
    save(package_evidence_path, package_evidence)
    obligation_declarations_ok = declaration_validation_run.get("returnCode") == 0
    readiness_path = root / ".agents" / "delivery-readiness.json"
    readiness_run = run([
        py, str(scripts / "verify_delivery_bundle_integrity.py"),
        "--bundle", str(delivery_dir), "--semantic-review", str(review_path),
        "--out", str(readiness_path),
    ], root, expect_zero=False)
    readiness = load(readiness_path, {}) if readiness_path.exists() else {}
    readiness_status = str(readiness.get("status", "BUNDLE_BLOCKED"))
    readiness_ok = readiness_status == "DESIGN_READY" and readiness.get("designReady") is True
    if args.readiness_mode == "gate" and not readiness_ok:
        readiness_evidence = {
            "status": readiness_status,
            "contentReady": bool(readiness.get("contentReady")),
            "evidenceReady": bool(readiness.get("evidenceReady")),
            "bundleReady": bool(readiness.get("bundleReady")),
            "designReady": bool(readiness.get("designReady")),
            "readinessPath": str(readiness_path) if readiness_path.exists() else None,
            "run": readiness_run,
        }
        blocked_report = {
            "schemaVersion": 1,
            "status": "PACKAGE_BLOCKED",
            "workflowId": args.workflow_id,
            "artifactProfile": args.artifact_profile,
            "artifacts": artifacts,
            "handoff": str(handoff),
            "readinessMode": args.readiness_mode,
            "readinessStatus": readiness_status,
            "contentReady": readiness_evidence["contentReady"],
            "evidenceReady": readiness_evidence["evidenceReady"],
            "bundleReady": readiness_evidence["bundleReady"],
            "designReady": readiness_evidence["designReady"],
            "deliveryReadiness": str(readiness_path) if readiness_path.exists() else None,
            "policyLock": str(delivery_policy_lock),
            "policyLockSha256": digest(delivery_policy_lock),
            "generationObligations": str(delivery_obligations),
            "generationObligationsSha256": digest(delivery_obligations),
            "obligationDeclarations": str(delivery_declarations),
            "obligationDeclarationsSha256": digest(delivery_declarations),
            "obligationDeclarationsValidation": str(delivery_declarations_validation),
            "obligationDeclarationsOk": obligation_declarations_ok,
            "obligationDeclarationsRun": declaration_validation_run,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
        }
        save(root / ".agents" / "quality" / "delivery-pipeline-report.json", blocked_report)
        print(json.dumps({"status": "PACKAGE_BLOCKED", "readiness": readiness_evidence, "artifactPhase": "PASS", "handoff": str(handoff), "report": str(root / ".agents" / "quality" / "delivery-pipeline-report.json")}, ensure_ascii=False, indent=2))
        return 2
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
        "generationContractMode": args.generation_contract_mode,
        "generationContractStatus": generation_contract_status,
        "generationContract": str(generation_contract_path) if generation_contract_path.exists() else None,
        "semanticDecompositionMode": args.semantic_decomposition_mode,
        "semanticDecompositionStatus": semantic_decomposition_status,
        "semanticModel": str(semantic_model_path) if semantic_model_path.exists() else None,
        "semanticIntegrationReview": str(semantic_integration_path) if semantic_integration_path.exists() else None,
        "semanticReviewJobs": str(semantic_jobs_manifest) if semantic_jobs_manifest.exists() else None,
        "semanticAggregateStatus": semantic_aggregate_status,
        "semanticAggregate": str(semantic_aggregate_path) if semantic_aggregate_path.exists() else None,
        "readinessMode": args.readiness_mode,
        "readinessStatus": readiness_status,
        "contentReady": bool(readiness.get("contentReady")),
        "evidenceReady": bool(readiness.get("evidenceReady")),
        "bundleReady": bool(readiness.get("bundleReady")),
        "designReady": bool(readiness.get("designReady")),
        "deliveryReadiness": str(readiness_path) if readiness_path.exists() else None,
        "policyLock": str(delivery_policy_lock),
        "policyLockSha256": digest(delivery_policy_lock),
        "generationObligations": str(delivery_obligations),
        "generationObligationsSha256": digest(delivery_obligations),
        "obligationDeclarations": str(delivery_declarations),
        "obligationDeclarationsSha256": digest(delivery_declarations),
        "obligationDeclarationsValidation": str(delivery_declarations_validation),
        "obligationDeclarationsOk": obligation_declarations_ok,
        "obligationDeclarationsRun": declaration_validation_run,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    save(root / ".agents" / "quality" / "delivery-pipeline-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
