#!/usr/bin/env python3
"""Coordinate Prototype Delta, PRD reconciliation, consistency gate and pair reseal."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(argv: list[str], cwd: Path) -> dict[str, Any]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    return {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "result": payload}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--artifact-profile", default="PRD_PLUS_PROTOTYPE", choices=["PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"])
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path, required=True)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--from-revision", required=True)
    parser.add_argument("--to-revision", required=True)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--apply-reconcile", action="store_true")
    parser.add_argument("--final-review", type=Path)
    parser.add_argument("--strict-copy", action="store_true")
    parser.add_argument("--strict-permissions", action="store_true")
    parser.add_argument("--auto-repair", action="store_true", help="execute bounded owner-specific repairs and rerun the pair/gate")
    parser.add_argument("--generate-overview", action="store_true", help="generate a deterministic Overview projection from a SYNCED Pair")
    parser.add_argument("--m2-complete", action="store_true", help="run Runtime Verify, U1/U2, Overview Projection Gate and M2 Final Review")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--browser-runner", nargs="+", help="Real browser adapter command for runtime verification.")
    parser.add_argument("--browser-timeout", type=float, default=30)
    parser.add_argument("--require-real-browser", action="store_true")
    parser.add_argument("--runtime-evidence", type=Path, help="Previously captured REAL_BROWSER evidence bound to the current Prototype.")
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    python = sys.executable
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
    if args.generate_overview and args.overview is None:
        args.overview = out / "Overview.html"
    steps: list[dict[str, Any]] = []

    delta_path = out / "prototype-delta.json"
    delta_cmd = [python, str(scripts / "build_prototype_delta.py"), "--previous", str(args.previous_manifest), "--current", str(args.manifest), "--workflow-id", args.workflow_id, "--out", str(delta_path)]
    steps.append({"step": "prototype-delta", **run(delta_cmd, out)})
    if steps[-1]["returnCode"] != 0:
        print(json.dumps({"status": "FAILED", "steps": steps}, ensure_ascii=False, indent=2)); return 1
    delta = load(delta_path)

    reconciliation_path = args.reconciliation.resolve() if args.reconciliation else out / "prd-reconciliation.json"
    if delta.get("requiresPrdReconciliation"):
        if args.reconciliation is None:
            recon_cmd = [python, str(scripts / "reconcile_prototype_delta.py"), "--delta", str(delta_path), "--prd", str(args.prd), "--from-prd-revision", args.from_revision, "--to-prd-revision", args.to_revision, "--status", "SYNCED" if args.apply_reconcile else "UNRESOLVED", "--out", str(reconciliation_path)]
            if args.apply_reconcile:
                recon_cmd.append("--apply")
            steps.append({"step": "prd-reconciliation", **run(recon_cmd, out)})
            if steps[-1]["returnCode"] != 0:
                print(json.dumps({"status": "FAILED", "steps": steps}, ensure_ascii=False, indent=2)); return 1
    reconciliation = load(reconciliation_path) if reconciliation_path.exists() else None

    pair_path = out / "artifact-pair.json"
    pair_cmd = [python, str(scripts / "build_artifact_pair.py"), "--workflow-id", args.workflow_id, "--artifact-profile", args.artifact_profile, "--prd", str(args.prd), "--prototype", str(args.prototype), "--prd-revision", args.to_revision, "--prototype-revision", args.to_revision, "--last-prototype-delta-id", delta["deltaId"], "--out", str(pair_path)]
    if reconciliation:
        pair_cmd.extend(["--last-prd-reconciliation-id", reconciliation["reconciliationId"]])
    if args.overview and args.overview.exists():
        pair_cmd.extend(["--overview", str(args.overview), "--overview-revision", args.to_revision])
    steps.append({"step": "artifact-pair", **run(pair_cmd, out)})
    if steps[-1]["returnCode"] != 0:
        print(json.dumps({"status": "FAILED", "steps": steps}, ensure_ascii=False, indent=2)); return 1

    if args.generate_overview:
        projection_cmd = [python, str(scripts / "generate_overview_projection.py"), "--prd", str(args.prd), "--prototype", str(args.prototype), "--manifest", str(args.manifest), "--pair", str(pair_path), "--out", str(args.overview)]
        steps.append({"step": "overview-projection", **run(projection_cmd, out)})
        if steps[-1]["returnCode"] != 0:
            print(json.dumps({"status": "FAILED", "steps": steps}, ensure_ascii=False, indent=2)); return 1
        pair_with_overview_cmd = [python, str(scripts / "build_artifact_pair.py"), "--workflow-id", args.workflow_id, "--artifact-profile", args.artifact_profile, "--prd", str(args.prd), "--prototype", str(args.prototype), "--prd-revision", args.to_revision, "--prototype-revision", args.to_revision, "--overview", str(args.overview), "--overview-revision", args.to_revision, "--last-prototype-delta-id", delta["deltaId"], "--out", str(pair_path)]
        if reconciliation:
            pair_with_overview_cmd.extend(["--last-prd-reconciliation-id", reconciliation["reconciliationId"]])
        steps.append({"step": "artifact-pair-with-overview", **run(pair_with_overview_cmd, out)})
        if steps[-1]["returnCode"] != 0:
            print(json.dumps({"status": "FAILED", "steps": steps}, ensure_ascii=False, indent=2)); return 1

    consistency_path = out / "artifact-consistency.json"
    gate_cmd = [python, str(scripts / "validate_artifact_consistency.py"), "--pair", str(pair_path), "--prd", str(args.prd), "--prototype", str(args.prototype), "--manifest", str(args.manifest), "--previous-manifest", str(args.previous_manifest), "--delta", str(delta_path), "--out", str(consistency_path)]
    if reconciliation:
        gate_cmd.extend(["--reconciliation", str(reconciliation_path)])
    if args.overview:
        gate_cmd.extend(["--overview", str(args.overview)])
    if args.strict_copy:
        gate_cmd.append("--strict-copy")
    if args.strict_permissions:
        gate_cmd.append("--strict-permissions")
    steps.append({"step": "artifact-consistency", **run(gate_cmd, out)})
    consistency = load(consistency_path) if consistency_path.exists() else {}

    repair_group_path = None
    if consistency.get("status") != "PASS":
        repair_group_path = out / "artifact-repair-group.json"
        steps.append({"step": "artifact-repair-plan", **run([python, str(scripts / "plan_artifact_repairs.py"), "--consistency", str(consistency_path), "--pair", str(pair_path), "--out", str(repair_group_path)], out)})
        if not args.auto_repair:
            print(json.dumps({"status": "REPAIR_REQUIRED", "steps": steps, "repairGroup": str(repair_group_path)}, ensure_ascii=False, indent=2)); return 1
        execution_path = out / "artifact-repair-execution.json"
        steps.append({"step": "artifact-repair-execution", **run([
            python, str(scripts / "execute_artifact_repairs.py"),
            "--repair-group", str(repair_group_path),
            "--delta", str(delta_path),
            "--prd", str(args.prd),
            "--reconciliation", str(reconciliation_path),
            "--from-prd-revision", args.from_revision,
            "--to-prd-revision", args.to_revision,
            "--out", str(execution_path),
        ], out)})
        if steps[-1]["returnCode"] != 0:
            print(json.dumps({"status": "REPAIR_BLOCKED", "steps": steps, "repairGroup": str(repair_group_path), "repairExecution": str(execution_path)}, ensure_ascii=False, indent=2)); return 1
        rerun_args: list[str] = []
        skip_next = False
        for arg in sys.argv[1:]:
            if skip_next:
                skip_next = False
                continue
            if arg == "--auto-repair":
                continue
            if arg == "--reconciliation":
                skip_next = True
                continue
            rerun_args.append(arg)
        if "--apply-reconcile" not in rerun_args:
            rerun_args.append("--apply-reconcile")
        rerun = run([python, str(Path(__file__).resolve()), *rerun_args], out)
        nested = rerun.get("result") or {"status": "FAILED", "nested": rerun}
        nested.setdefault("steps", [])
        nested["steps"] = steps + nested["steps"]
        nested["repairGroup"] = str(repair_group_path)
        nested["repairExecution"] = str(execution_path)
        print(json.dumps(nested, ensure_ascii=False, indent=2))
        return 0 if nested.get("status") == "FINAL_PASS" else 1

    m2_review_path = None
    if args.m2_complete:
        if not args.overview or not args.overview.exists():
            print(json.dumps({"status": "M2_BLOCKED", "reason": "M2 requires an Overview; pass --generate-overview or --overview."}, ensure_ascii=False, indent=2)); return 1
        runtime_path = out / "prototype-runtime.json"
        if args.runtime_evidence:
            evidence_path = args.runtime_evidence.resolve()
            evidence = load(evidence_path)
            proto_hash = __import__("hashlib").sha256(args.prototype.read_bytes()).hexdigest()
            diagnostics = evidence.get("consoleDiagnostics") or evidence.get("consoleErrors") or []
            authoritative = (
                evidence.get("status") == "PASS"
                and evidence.get("executionMode") == "real-browser"
                and evidence.get("runtimeEvidenceLevel") == "REAL_BROWSER"
                and evidence.get("prototypeHash") == proto_hash
                and not diagnostics
                and not evidence.get("pageErrors")
                and not evidence.get("requestFailures")
            )
            if authoritative:
                runtime_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                steps.append({
                    "step": "runtime-verify",
                    "returnCode": 0,
                    "stdout": json.dumps({"status": "PASS", "executionMode": "real-browser", "runtimeEvidenceLevel": "REAL_BROWSER", "source": str(evidence_path)}, ensure_ascii=False),
                    "stderr": "",
                    "result": {"status": "PASS", "executionMode": "real-browser", "runtimeEvidenceLevel": "REAL_BROWSER", "source": str(evidence_path)},
                })
            else:
                steps.append({
                    "step": "runtime-verify",
                    "returnCode": 1,
                    "stdout": json.dumps({"status": "NEEDS_FIX", "reason": "external runtime evidence is not authoritative for the current Prototype"}, ensure_ascii=False),
                    "stderr": "",
                    "result": {"status": "NEEDS_FIX", "reason": "external runtime evidence is not authoritative for the current Prototype"},
                })
        else:
            runtime_cmd = [python, str(scripts / "verify_prototype_runtime.py"), "--prototype", str(args.prototype), "--out", str(runtime_path), "--browser-timeout", str(args.browser_timeout)]
            if args.browser_runner:
                runtime_cmd.extend(["--browser-runner", *args.browser_runner])
            if args.require_real_browser:
                runtime_cmd.append("--require-real-browser")
            steps.append({"step": "runtime-verify", **run(runtime_cmd, out)})
        preflight_path = out / "prototype-preflight.json"
        steps.append({"step": "prototype-preflight-u1", **run([python, str(scripts / "preflight_prototype.py"), "--prd", str(args.prd), "--prototype", str(args.prototype), "--overview", str(args.overview), "--runtime-result", str(runtime_path), "--out", str(preflight_path)], out)})
        overview_gate_path = out / "overview-projection-gate.json"
        steps.append({"step": "overview-projection-gate-o1", **run([python, str(scripts / "overview_projection_gate.py"), "--pair", str(pair_path), "--overview", str(args.overview), "--prd", str(args.prd), "--out", str(overview_gate_path)], out)})
        m2_review_path = out / "m2-final-review.json"
        steps.append({"step": "m2-final-package-review", **run([python, str(scripts / "m2_review.py"), "--pair", str(pair_path), "--preflight", str(preflight_path), "--runtime", str(runtime_path), "--consistency", str(consistency_path), "--overview-gate", str(overview_gate_path), "--out", str(m2_review_path)], out)})
        if any(step.get("returnCode") != 0 for step in steps[-4:]):
            print(json.dumps({"status": "M2_BLOCKED", "steps": steps, "pair": str(pair_path), "consistency": str(consistency_path), "m2Review": str(m2_review_path)}, ensure_ascii=False, indent=2)); return 1

    final_gate_path = None
    final_status = "CONSISTENCY_PASSED"
    final_review_input = m2_review_path or args.final_review
    if final_review_input:
        final_gate_path = out / "final-delivery-gate.json"
        final_run = run([python, str(scripts / "final_delivery_gate.py"), "--pair", str(pair_path), "--consistency", str(consistency_path), "--final-review", str(final_review_input), "--out", str(final_gate_path)], out)
        steps.append({"step": "final-delivery-gate", **final_run})
        final_status = "M2_FINAL_PASS" if args.m2_complete and final_run["returnCode"] == 0 else ("FINAL_PASS" if final_run["returnCode"] == 0 else "FINAL_BLOCKED")
    print(json.dumps({"status": final_status, "steps": steps, "pair": str(pair_path), "consistency": str(consistency_path), "repairGroup": str(repair_group_path) if repair_group_path else None, "m2Review": str(m2_review_path) if m2_review_path else None, "finalGate": str(final_gate_path) if final_gate_path else None}, ensure_ascii=False, indent=2))
    return 0 if final_status in {"FINAL_PASS", "M2_FINAL_PASS", "CONSISTENCY_PASSED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
