#!/usr/bin/env python3
"""Run Audit -> repair -> new revision -> full re-audit until pass or bounded failure."""
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

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
DEFAULT_PROFILE = ROOT / "config" / "audit-profiles" / "prd-only.json"
DEFAULT_CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path) -> dict[str, Any]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        result = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        result = {}
    return {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "result": result}


def revision_number(value: str) -> int:
    try:
        return int(value.removeprefix("r"))
    except ValueError:
        raise ValueError(f"revision must be r<number>, got {value!r}")


def live_snapshot(bundle: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(bundle.rglob("*")):
        if not path.is_file() or ".delivery" in path.parts:
            continue
        result[path.relative_to(bundle).as_posix()] = sha(path)
    return result


def audit_findings(bundle: Path, revision: str) -> list[dict[str, Any]]:
    result_dir = bundle / ".delivery" / "audit-runs" / revision / "results"
    findings: list[dict[str, Any]] = []
    for path in sorted(result_dir.glob("*.result.json")):
        try:
            result = load(path)
        except Exception:
            continue
        for finding in result.get("findings") or []:
            item = dict(finding)
            item.setdefault("sourceResult", str(path))
            item.setdefault("rootCauseId", item.get("findingId", path.stem))
            item.setdefault("repairClass", "SEMANTIC")
            item.setdefault("ruleIds", item.get("policyRuleIds", []))
            findings.append(item)
    return findings


def next_revision(value: str) -> str:
    return f"r{revision_number(value) + 1}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-name", required=True)
    parser.add_argument("--requirement-id", default="")
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--crosswalk", type=Path, default=DEFAULT_CROSSWALK)
    parser.add_argument("--audit-worker", nargs="+", required=True)
    parser.add_argument("--repair-worker", nargs="+", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    bundle = args.bundle.resolve()
    out_path = args.out.resolve() if args.out else run_root / ".agents" / "audit" / "repair-cycle-report.json"
    current_revision = args.revision
    rounds: list[dict[str, Any]] = []
    errors: list[str] = []

    candidate_builder = [
        sys.executable, str(SCRIPTS / "build_candidate_bundle.py"),
        "--bundle", str(bundle), "--workflow-id", args.workflow_id,
        "--requirement-id", args.requirement_id or args.workflow_id,
        "--requirement-name", args.requirement_name, "--revision", current_revision,
        "--prd", str(bundle / "PRD_DELIVERY.md"),
        "--overview", str(bundle / "Overview.html"),
        "--jira", str(bundle / "Jira_Description.md"),
    ]
    prototype = bundle / "Prototype.html"
    manifest = bundle / "prototype-manifest.json"
    if prototype.exists() and manifest.exists():
        candidate_builder += ["--prototype", str(prototype), "--manifest", str(manifest)]
    candidate_builder_run = run(candidate_builder, run_root)
    if candidate_builder_run["returnCode"] != 0:
        errors.append("initial Candidate Seal build failed")
    elif not (bundle / ".delivery" / "candidate-seal.json").exists():
        errors.append("initial Candidate Seal was not produced")

    if not errors:
        for round_number in range(args.max_rounds + 1):
            stage_path = run_root / ".agents" / "audit" / f"stage-{current_revision}.json"
            stage_run = run([
                sys.executable, str(SCRIPTS / "run_delivery_audit_stage.py"),
                "--run-root", str(run_root), "--bundle", str(bundle),
                "--workflow-id", args.workflow_id, "--revision", current_revision,
                "--profile", str(args.profile.resolve()), "--crosswalk", str(args.crosswalk.resolve()),
                "--worker", *args.audit_worker, "--timeout", str(args.timeout), "--out", str(stage_path),
            ], run_root)
            stage = load(stage_path) if stage_path.exists() else {}
            round_record: dict[str, Any] = {
                "round": round_number,
                "revision": current_revision,
                "stage": stage,
                "stageRun": stage_run,
            }
            rounds.append(round_record)
            if stage.get("status") == "AUDIT_PASS":
                report = {
                    "schemaVersion": 1, "status": "AUDIT_PASS", "workflowId": args.workflow_id,
                    "finalRevision": current_revision, "rounds": rounds, "errors": errors, "checkedAt": now(),
                }
                save(out_path, report)
                print(json.dumps({"status": "AUDIT_PASS", "revision": current_revision, "rounds": len(rounds), "out": str(out_path)}, ensure_ascii=False))
                return 0
            if round_number >= args.max_rounds:
                errors.append("maximum audit repair rounds exceeded")
                break

            findings = audit_findings(bundle, current_revision)
            if not findings:
                errors.append(f"audit failed for {current_revision} but produced no repair findings")
                break
            findings_path = run_root / ".agents" / "audit" / f"repair-findings-{current_revision}.json"
            save(findings_path, {
                "schemaVersion": 1, "workflowId": args.workflow_id, "revision": current_revision,
                "findings": findings, "createdAt": now(),
            })
            before = live_snapshot(bundle)
            next_rev = next_revision(current_revision)
            repair_report_path = run_root / ".agents" / "audit" / f"repair-report-{current_revision}-to-{next_rev}.json"
            repair_run = run([
                *args.repair_worker,
                "--bundle", str(bundle), "--findings", str(findings_path),
                "--revision", next_rev, "--out", str(repair_report_path),
            ], run_root)
            repair_report = load(repair_report_path) if repair_report_path.exists() else {}
            round_record["findings"] = str(findings_path)
            round_record["repair"] = repair_run
            round_record["repairReport"] = str(repair_report_path)
            after = live_snapshot(bundle)
            changed = sorted(key for key in set(before) | set(after) if before.get(key) != after.get(key))
            if repair_run["returnCode"] != 0 or repair_report.get("status") != "PASS":
                errors.append(f"repair worker blocked revision {current_revision}")
                break
            if not changed:
                errors.append(f"repair worker reported success but changed no active artifacts for {current_revision}")
                break
            declared = set(repair_report.get("changedArtifacts") or [])
            if declared and not declared.intersection(changed):
                errors.append("repair worker changed artifacts do not match changedArtifacts")
                break

            builder = [
                sys.executable, str(SCRIPTS / "build_candidate_bundle.py"),
                "--bundle", str(bundle), "--workflow-id", args.workflow_id,
                "--requirement-id", args.requirement_id or args.workflow_id,
                "--requirement-name", args.requirement_name, "--revision", next_rev,
                "--refresh-projections", "--prd", str(bundle / "PRD_DELIVERY.md"),
                "--overview", str(bundle / "Overview.html"), "--jira", str(bundle / "Jira_Description.md"),
            ]
            if prototype.exists() and manifest.exists():
                builder += ["--prototype", str(prototype), "--manifest", str(manifest)]
            builder_run = run(builder, run_root)
            round_record["candidateBuild"] = builder_run
            if builder_run["returnCode"] != 0:
                errors.append(f"Candidate Seal build failed for {next_rev}")
                break
            current_revision = next_rev

    report = {
        "schemaVersion": 1, "status": "AUDIT_BLOCKED", "workflowId": args.workflow_id,
        "finalRevision": current_revision, "rounds": rounds, "errors": errors, "checkedAt": now(),
    }
    save(out_path, report)
    print(json.dumps({"status": report["status"], "errors": errors, "rounds": len(rounds), "out": str(out_path)}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
