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

from finding_ledger import close_ledger, empty_ledger, mark_repairing, sync_ledger

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
    findings: dict[str, dict[str, Any]] = {}
    sources: dict[str, list[str]] = {}
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
            finding_id = str(item.get("findingId") or "")
            if not finding_id:
                finding_id = f"{path.stem}:{len(findings) + 1}"
                item["findingId"] = finding_id
            sources.setdefault(finding_id, []).append(str(path))
            findings.setdefault(finding_id, item)
    for finding_id, item in findings.items():
        item["sourceResults"] = list(dict.fromkeys(sources.get(finding_id, [])))
    return list(findings.values())


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
    parser.add_argument("--rederive-mode", choices=["off", "gate"], default="off")
    parser.add_argument("--derived-rebuild-mode", choices=["off", "gate"], default="off")
    parser.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"])
    parser.add_argument("--semantic-mode", choices=["off", "gate"], default="gate")
    parser.add_argument("--decision-impact-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--runtime-ac-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--external-contract-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--external-contract-profile", type=Path, default=ROOT / "config" / "external-skills" / "delivery-external-v2.3.0.profile.json")
    parser.add_argument("--decision-impact-input", type=Path)
    parser.add_argument("--runtime-ac-input", type=Path)
    parser.add_argument("--producer-registry", type=Path)
    parser.add_argument("--requirement", type=Path)
    parser.add_argument("--declarations-dir", type=Path)
    parser.add_argument("--source-drift-mode", choices=["off", "gate"], default="off")
    parser.add_argument("--source-map", type=Path, default=ROOT / "config" / "audit-source-map.json")
    parser.add_argument("--source-lock", type=Path, default=ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.lock.json")
    parser.add_argument("--source-root", type=Path, default=Path.home() / ".codex" / "skills")
    parser.add_argument("--external-findings", type=Path, help="Raw external Skill finding report to ingest before the Repair Cycle.")
    parser.add_argument("--external-skill-id", help="Stable external Skill identifier used for Finding Ledger identity.")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    run_root = args.run_root.resolve()
    bundle = args.bundle.resolve()
    out_path = args.out.resolve() if args.out else run_root / ".agents" / "audit" / "repair-cycle-report.json"
    current_revision = args.revision
    rounds: list[dict[str, Any]] = []
    errors: list[str] = []
    ledger_path = bundle / ".delivery" / "findings.json"
    previous_failure_count: int | None = None
    external_findings: list[dict[str, Any]] = []
    external_batch_path: Path | None = None
    external_import_run: dict[str, Any] | None = None
    external_injected = False

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
        if args.external_findings:
            if not args.external_skill_id:
                errors.append("--external-skill-id is required with --external-findings")
            else:
                external_batch_path = run_root / ".agents" / "audit" / f"external-findings-{args.revision}.json"
                external_import_run = run([
                    sys.executable, str(SCRIPTS / "import_external_skill_findings.py"),
                    "--input", str(args.external_findings.resolve()),
                    "--skill-id", args.external_skill_id,
                    "--workflow-id", args.workflow_id,
                    "--revision", args.revision,
                    "--out", str(external_batch_path),
                    "--sync-ledger", "--ledger", str(ledger_path),
                ], run_root)
                if external_import_run["returnCode"] != 0 or not external_batch_path.is_file():
                    errors.append("external Skill finding import failed")
                else:
                    external_batch = load(external_batch_path)
                    external_findings = list(external_batch.get("findings") or [])
        for round_number in range(args.max_rounds + 1):
            stage_path = run_root / ".agents" / "audit" / f"stage-{current_revision}.json"
            stage_run = run([
                sys.executable, str(SCRIPTS / "run_delivery_audit_stage.py"),
                "--run-root", str(run_root), "--bundle", str(bundle),
                "--workflow-id", args.workflow_id, "--revision", current_revision,
                "--profile", str(args.profile.resolve()), "--crosswalk", str(args.crosswalk.resolve()),
                "--worker", *args.audit_worker, "--timeout", str(args.timeout), "--out", str(stage_path),
                "--source-drift-mode", args.source_drift_mode,
                "--source-map", str(args.source_map.resolve()), "--source-lock", str(args.source_lock.resolve()),
                "--source-root", str(args.source_root.resolve()),
            ], run_root)
            stage = load(stage_path) if stage_path.exists() else {}
            round_record: dict[str, Any] = {
                "round": round_number,
                "revision": current_revision,
                "stage": stage,
                "stageRun": stage_run,
            }
            rounds.append(round_record)
            external_repair_pending = bool(external_findings and not external_injected and current_revision == args.revision)
            if stage.get("status") == "AUDIT_PASS" and not external_repair_pending:
                derived_rebuild = None
                if args.derived_rebuild_mode == "gate" and current_revision != args.revision:
                    rebuild_path = run_root / ".agents" / "audit" / f"derived-rebuild-{current_revision}.json"
                    rebuild_run = run([
                        sys.executable, str(SCRIPTS / "rebuild_derived_evidence.py"),
                        "--bundle", str(bundle),
                        "--source-revision", args.revision,
                        "--target-revision", current_revision,
                        "--manifest-out", str(rebuild_path),
                        "--sync-consumer-rebind",
                        "--force",
                    ], run_root)
                    derived_rebuild = load(rebuild_path) if rebuild_path.exists() else {}
                    if rebuild_run["returnCode"] != 0 or derived_rebuild.get("status") != "PASS":
                        errors.append(f"derived evidence rebuild blocked {current_revision}")
                        report = {
                            "schemaVersion": 1, "status": "AUDIT_BLOCKED", "workflowId": args.workflow_id,
                            "finalRevision": current_revision, "findingLedger": str(ledger_path), "findingMetrics": ledger["metrics"],
                            "rounds": rounds, "errors": errors, "derivedRebuild": str(rebuild_path), "checkedAt": now(),
                        }
                        save(out_path, report)
                        print(json.dumps({"status": "AUDIT_BLOCKED", "errors": errors, "out": str(out_path)}, ensure_ascii=False))
                        return 1
                if not ledger_path.is_file():
                    save(ledger_path, empty_ledger(args.workflow_id, current_revision))
                ledger = close_ledger(ledger_path, current_revision, [str(stage_path), str(run_root / ".agents" / "audit" / f"stage-{current_revision}.json")])
                report = {
                    "schemaVersion": 1, "status": "AUDIT_PASS", "workflowId": args.workflow_id,
                    "finalRevision": current_revision, "findingLedger": str(ledger_path), "findingMetrics": ledger["metrics"],
                    "rounds": rounds, "errors": errors, "derivedRebuild": derived_rebuild,
                    "externalFindingBatch": str(external_batch_path) if external_batch_path else None,
                    "externalFindingCount": len(external_findings), "externalImportRun": external_import_run,
                    "checkedAt": now(),
                }
                save(out_path, report)
                print(json.dumps({"status": "AUDIT_PASS", "revision": current_revision, "rounds": len(rounds), "out": str(out_path)}, ensure_ascii=False))
                return 0
            if round_number >= args.max_rounds:
                errors.append("maximum audit repair rounds exceeded")
                break

            findings = audit_findings(bundle, current_revision)
            ledger_findings_path = None
            if external_repair_pending:
                ledger_findings_path = run_root / ".agents" / "audit" / f"ledger-findings-{current_revision}.json"
                save(ledger_findings_path, {"schemaVersion": 1, "workflowId": args.workflow_id, "revision": current_revision, "findings": findings, "createdAt": now()})
                findings = [*findings, *external_findings]
                external_injected = True
                if external_batch_path:
                    round_record["externalFindingBatch"] = str(external_batch_path)
            if not findings:
                errors.append(f"audit failed for {current_revision} but produced no repair findings")
                break
            findings_path = run_root / ".agents" / "audit" / f"repair-findings-{current_revision}.json"
            save(findings_path, {
                "schemaVersion": 1, "workflowId": args.workflow_id, "revision": current_revision,
                "findings": findings, "ledger": str(ledger_path), "createdAt": now(),
            })
            ledger = sync_ledger(ledger_path, ledger_findings_path or findings_path, args.workflow_id, current_revision)
            round_record["findingLedger"] = str(ledger_path)
            round_record["findingMetrics"] = ledger["metrics"]
            stalled = [item["findingId"] for item in ledger["entries"] if item["status"] not in {"resolved", "accepted_risk", "closed_by_decision"} and int(item.get("unresolvedRounds", 0)) >= 2]
            if stalled:
                errors.append("findings unchanged for two repair rounds: " + ", ".join(stalled))
                break
            if previous_failure_count is not None and len(findings) > previous_failure_count:
                errors.append(f"repair increased total findings from {previous_failure_count} to {len(findings)}")
                break
            before = live_snapshot(bundle)
            next_rev = next_revision(current_revision)
            repair_report_path = run_root / ".agents" / "audit" / f"repair-report-{current_revision}-to-{next_rev}.json"
            ledger = mark_repairing(ledger_path, next_rev)
            round_record["repairFindingMetrics"] = ledger["metrics"]
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

            if args.rederive_mode == "gate":
                rederive_report = run_root / ".agents" / "audit" / f"rederive-{next_rev}.json"
                builder = [
                    sys.executable, str(SCRIPTS / "rederive_delivery_evidence.py"),
                    "--bundle", str(bundle), "--workflow-id", args.workflow_id,
                    "--revision", next_rev,
                    "--semantic-mode", args.semantic_mode,
                    "--decision-impact-mode", args.decision_impact_mode,
                    "--runtime-ac-mode", args.runtime_ac_mode,
                    "--external-contract-mode", args.external_contract_mode,
                    "--external-contract-profile", str(args.external_contract_profile.resolve()),
                    "--out", str(rederive_report),
                ]
                if args.artifact_profile:
                    builder.extend(["--artifact-profile", args.artifact_profile])
                if args.decision_impact_input:
                    builder.extend(["--decision-impact-input", str(args.decision_impact_input.resolve())])
                if args.runtime_ac_input:
                    builder.extend(["--runtime-ac-input", str(args.runtime_ac_input.resolve())])
                if args.producer_registry:
                    builder.extend(["--producer-registry", str(args.producer_registry.resolve())])
                if args.requirement:
                    builder.extend(["--requirement", str(args.requirement.resolve())])
                if args.declarations_dir:
                    builder.extend(["--declarations-dir", str(args.declarations_dir.resolve())])
                builder_run = run(builder, run_root)
                round_record["rederiveReport"] = str(rederive_report)
            else:
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
                errors.append(f"derived evidence or Candidate Seal rebuild failed for {next_rev}")
                break
            previous_failure_count = len(findings)
            current_revision = next_rev

    report = {
        "schemaVersion": 1, "status": "AUDIT_BLOCKED", "workflowId": args.workflow_id,
        "finalRevision": current_revision, "findingLedger": str(ledger_path) if ledger_path.exists() else None,
        "findingMetrics": load(ledger_path).get("metrics") if ledger_path.exists() else None,
        "rounds": rounds, "errors": errors, "externalFindingBatch": str(external_batch_path) if external_batch_path else None,
        "externalFindingCount": len(external_findings), "externalImportRun": external_import_run, "checkedAt": now(),
    }
    save(out_path, report)
    print(json.dumps({"status": report["status"], "errors": errors, "rounds": len(rounds), "out": str(out_path)}, ensure_ascii=False))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
