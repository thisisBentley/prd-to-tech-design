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
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    python = sys.executable
    out = args.out_dir.resolve(); out.mkdir(parents=True, exist_ok=True)
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
    if args.overview:
        pair_cmd.extend(["--overview", str(args.overview), "--overview-revision", args.to_revision])
    steps.append({"step": "artifact-pair", **run(pair_cmd, out)})
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
        print(json.dumps({"status": "REPAIR_REQUIRED", "steps": steps, "repairGroup": str(repair_group_path)}, ensure_ascii=False, indent=2)); return 1

    final_gate_path = None
    final_status = "CONSISTENCY_PASSED"
    if args.final_review:
        final_gate_path = out / "final-delivery-gate.json"
        final_run = run([python, str(scripts / "final_delivery_gate.py"), "--pair", str(pair_path), "--consistency", str(consistency_path), "--final-review", str(args.final_review), "--out", str(final_gate_path)], out)
        steps.append({"step": "final-delivery-gate", **final_run})
        final_status = "FINAL_PASS" if final_run["returnCode"] == 0 else "FINAL_BLOCKED"
    print(json.dumps({"status": final_status, "steps": steps, "pair": str(pair_path), "consistency": str(consistency_path), "repairGroup": str(repair_group_path) if repair_group_path else None, "finalGate": str(final_gate_path) if final_gate_path else None}, ensure_ascii=False, indent=2))
    return 0 if final_status == "FINAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
