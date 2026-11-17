#!/usr/bin/env python3
"""Rebuild derived Delivery evidence after an active artifact repair."""
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
DEFAULT_EXTERNAL_PROFILE = ROOT / "config" / "external-skills" / "delivery-external-v2.3.0.profile.json"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str], cwd: Path) -> dict[str, Any]:
    process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(process.stdout) if process.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    return {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr, "result": payload}


def find_main(bundle: Path, explicit: Path | None, patterns: tuple[str, ...], fallback: str) -> Path:
    if explicit:
        return explicit.resolve()
    candidates: list[Path] = []
    for path in bundle.iterdir():
        if path.is_file() and any(path.match(pattern) for pattern in patterns):
            candidates.append(path)
    if not candidates:
        fallback_path = bundle / fallback
        if fallback_path.is_file():
            return fallback_path.resolve()
        raise FileNotFoundError(f"could not locate active artifact {fallback}")
    return sorted(candidates, key=lambda item: (len(item.name), item.name))[0].resolve()


def artifact_profile(bundle: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    seal = load(bundle / ".delivery" / "candidate-seal.json", {})
    if seal.get("artifactProfile"):
        return str(seal["artifactProfile"])
    evidence = load(bundle.parent / ".agents" / "quality" / "package-evidence.json", {})
    if evidence.get("artifactProfile"):
        return str(evidence["artifactProfile"])
    return "PRD_PLUS_PROTOTYPE" if list(bundle.glob("*Prototype*.html")) else "PRD_ONLY"


def producer_modes(bundle: Path) -> tuple[str, str]:
    evidence = load(bundle.parent / ".agents" / "quality" / "package-evidence.json", {})
    downstream = str(evidence.get("downstreamProducerMode") or "provided")
    prd_mode = str(evidence.get("prdProducerMode") or "unknown")
    if downstream not in {"deterministic", "provided", "semantic"}:
        downstream = "provided"
    if prd_mode not in {"deterministic", "provided", "semantic"}:
        prd_mode = "unknown"
    return downstream, prd_mode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"])
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--jira", type=Path)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--semantic-mode", choices=["off", "gate"], default="gate")
    parser.add_argument("--semantic-source", choices=["auto", "regenerate", "reuse"], default="auto", help="Reuse and rebind an existing semantic ledger when available, or regenerate it from artifacts.")
    parser.add_argument("--decision-impact-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--runtime-ac-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--external-contract-mode", choices=["off", "advisory", "gate"], default="off")
    parser.add_argument("--external-contract-profile", type=Path, default=DEFAULT_EXTERNAL_PROFILE)
    parser.add_argument("--decision-impact-input", type=Path)
    parser.add_argument("--runtime-ac-input", type=Path)
    parser.add_argument("--producer-registry", type=Path)
    parser.add_argument("--requirement", type=Path)
    parser.add_argument("--declarations-dir", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    run_root = bundle.parent
    dd = bundle / ".delivery"
    report_path = args.out.resolve() if args.out else dd / "rederive-report.json"
    workflow_id = str(load(dd / "candidate-seal.json", {}).get("workflowId") or args.workflow_id)
    profile = artifact_profile(bundle, args.artifact_profile)
    downstream_mode, prd_mode = producer_modes(bundle)
    steps: list[dict[str, Any]] = []
    errors: list[str] = []
    artifacts_unchanged = False

    try:
        prd = find_main(bundle, args.prd, ("*PRD_DELIVERY*.md", "PRD_DELIVERY.md"), "PRD_DELIVERY.md")
        overview = find_main(bundle, args.overview, ("*Overview*.html", "Overview.html"), "Overview.html")
        jira = find_main(bundle, args.jira, ("*Jira_Description*.md", "Jira_Description.md"), "Jira_Description.md")
        prototype = args.prototype.resolve() if args.prototype else (find_main(bundle, None, ("*Prototype*.html", "Prototype.html"), "Prototype.html") if profile in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"} else None)
        manifest = args.manifest.resolve() if args.manifest else ((bundle / "prototype-manifest.json").resolve() if prototype else None)
        if prototype and not prototype.is_file():
            raise FileNotFoundError(f"active Prototype is missing: {prototype}")
        if manifest and not manifest.is_file():
            raise FileNotFoundError(f"active prototype manifest is missing: {manifest}")
    except Exception as exc:
        report = {"schemaVersion": 1, "status": "BLOCKED", "workflowId": workflow_id, "revision": args.revision, "steps": steps, "errors": [str(exc)], "generatedAt": now()}
        save(report_path, report)
        print(json.dumps({"status": "BLOCKED", "errors": report["errors"], "out": str(report_path)}, ensure_ascii=False))
        return 1

    def record(name: str, result: dict[str, Any], require_status: set[str] | None = None) -> None:
        status = str(result.get("result", {}).get("status") or "")
        ok = result["returnCode"] == 0 and (require_status is None or status in require_status)
        steps.append({"step": name, "status": "PASS" if ok else "BLOCKED", "run": result, "reportedStatus": status})
        if not ok:
            errors.append(f"{name} failed with status {status or result['returnCode']}")

    def require_generation_obligations() -> bool:
        policy_lock = dd / "policy-lock.json"
        obligations = dd / "generation-obligations.json"
        if not policy_lock.is_file():
            errors.append("policy-lock.json is required for re-derivation")
            return False
        result = run([
            sys.executable, str(SCRIPTS / "build_generation_obligations.py"),
            "--policy-lock", str(policy_lock), "--workflow-id", workflow_id,
            "--revision", args.revision, "--out", str(obligations),
        ], run_root)
        record("generationObligations", result)
        run_policy = run_root / ".agents" / "policy"
        run_policy.mkdir(parents=True, exist_ok=True)
        if obligations.is_file():
            shutil.copyfile(obligations, run_policy / "generation-obligations.json")
        return result["returnCode"] == 0

    def run_semantic_producer() -> bool:
        if not args.producer_registry or not args.producer_registry.is_file() or not args.requirement or not args.requirement.is_file():
            return False
        output_dir = run_root / ".agents" / "producers" / f"semantic-evidence-{args.revision}"
        output_dir.mkdir(parents=True, exist_ok=True)
        result_path = run_root / ".agents" / "producers" / f"semantic-evidence-{args.revision}.result.json"
        command = [
            sys.executable, str(SCRIPTS / "run_producer.py"),
            "--registry", str(args.producer_registry.resolve()), "--kind", "semantic-evidence",
            "--workflow-id", workflow_id, "--revision", args.revision,
            "--run-root", str(run_root), "--output-dir", str(output_dir),
            "--prd", str(prd), "--requirement", str(args.requirement.resolve()),
            "--out", str(result_path),
        ]
        if prototype:
            command.extend(["--prototype", str(prototype)])
        result = run(command, run_root)
        record("semanticProducer", result, {"PASS"})
        if result["returnCode"] != 0:
            return False
        candidates = [output_dir / "semantic-evidence.json", output_dir / "semantic-consistency-input.json"]
        produced = next((path for path in candidates if path.is_file()), None)
        if produced is None:
            errors.append("semantic-evidence producer did not emit semantic-evidence.json or semantic-consistency-input.json")
            return False
        shutil.copyfile(produced, semantic_input)
        declaration_source = output_dir / "obligation-declarations.json"
        if declaration_source.is_file():
            declaration_dir = args.declarations_dir.resolve() if args.declarations_dir else run_root / ".agents" / "policy" / "declarations"
            declaration_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(declaration_source, declaration_dir / "semantic-evidence.json")
            steps.append({"step": "semanticProducerDeclarations", "status": "PASS", "reportedStatus": "COLLECTED"})
        return True

    semantic_input = dd / "semantic-consistency-input.json"
    semantic_review = dd / "semantic-consistency-review.json"
    semantic_transcript = dd / "semantic-review-transcript.log"
    semantic_reused_review = False
    if not require_generation_obligations():
        report = {"schemaVersion": 1, "status": "BLOCKED", "workflowId": workflow_id, "revision": args.revision, "steps": steps, "errors": errors, "generatedAt": now()}
        save(report_path, report)
        print(json.dumps({"status": "BLOCKED", "revision": args.revision, "errors": errors, "out": str(report_path)}, ensure_ascii=False))
        return 1
    if args.semantic_mode != "off":
        capability = run_root / ".agents" / "context" / "capability-context.json"
        active_paths = {"prd": prd, "overview": overview, "jira": jira, "prototype": prototype, "manifest": manifest}
        existing_semantic = load(semantic_input, {}) if semantic_input.is_file() else {}
        has_semantic_content = any(existing_semantic.get(key) for key in ("terminologyClaims", "capabilityClaims", "stateAssumptions", "permissionEdges", "crossArtifactClaims", "businessAssertions", "interactionElements"))
        reuse_semantic = args.semantic_source == "reuse" or (args.semantic_source == "auto" and has_semantic_content)
        if reuse_semantic:
            if not has_semantic_content:
                errors.append("semantic reuse requested but existing semantic evidence is missing or empty")
                steps.append({"step": "semanticEvidence", "status": "BLOCKED", "reportedStatus": "MISSING"})
            else:
                rebind = {str(item.get("path", "")).split("#", 1)[0]: str(item.get("path", "")).split("#", 1)[0] for item in existing_semantic.get("artifacts", []) if item.get("path")}
                name_rebind: dict[str, str] = {}
                hashes_unchanged = True
                for item in existing_semantic.get("artifacts", []):
                    old = str(item.get("path", "")).split("#", 1)[0]
                    old_name = Path(old).name
                    replacement = next((path for key, path in active_paths.items() if path and path.name == old_name), None)
                    if replacement is None:
                        candidate = dd / old_name
                        if candidate.is_file():
                            replacement = candidate
                    if replacement is not None:
                        if str(item.get("sha256") or "") != digest(replacement):
                            hashes_unchanged = False
                        rebind[old] = str(replacement.resolve())
                        name_rebind[old_name] = str(replacement.resolve())
                        item["path"] = str(replacement.resolve())
                        item["sha256"] = digest(replacement)
                def rewrite(value: Any) -> Any:
                    if isinstance(value, dict):
                        return {key: rewrite(item) for key, item in value.items()}
                    if isinstance(value, list):
                        return [rewrite(item) for item in value]
                    if not isinstance(value, str):
                        return value
                    base, separator, fragment = value.partition("#")
                    replacement = rebind.get(base) or name_rebind.get(Path(base).name)
                    if replacement:
                        return replacement + (separator + fragment if separator else "")
                    return value
                source_semantic_revision = str(existing_semantic.get("targetRevision") or "")
                existing_semantic = rewrite(existing_semantic)
                existing_semantic["targetRevision"] = args.revision
                existing_semantic["workflowId"] = workflow_id
                existing_semantic["semanticRebind"] = {"sourceRevision": source_semantic_revision, "targetRevision": args.revision, "mode": "REUSE_AND_REBIND", "reboundAt": now()}
                save(semantic_input, existing_semantic)
                steps.append({"step": "semanticEvidence", "status": "PASS", "reportedStatus": "REUSED_AND_REBOUND"})
                existing_review = load(semantic_review, {}) if semantic_review.is_file() else {}
                if hashes_unchanged and existing_review.get("verdict") == "ACCEPTED":
                    artifacts_unchanged = True
                    rebind_review = rewrite(existing_review)
                    rebind_review["targetRevision"] = args.revision
                    rebind_review["targetHandoffId"] = f"{workflow_id}-delivery-{args.revision}"
                    rebind_review["checkedAt"] = now()
                    save(semantic_review, rebind_review)
                    steps.append({"step": "semanticCoverage", "status": "PASS", "reportedStatus": "REUSED_WITH_UNCHANGED_ARTIFACTS"})
                    steps.append({"step": "semanticReview", "status": "PASS", "reportedStatus": "ACCEPTED_REUSED_AND_REBOUND"})
                    semantic_reused_review = True
                else:
                    semantic_reused_review = False
                    if args.producer_registry:
                        run_semantic_producer()
        else:
            semantic_reused_review = False
            produced = run_semantic_producer() if args.producer_registry else False
            if not produced:
                semantic_cmd = [
                    sys.executable, str(SCRIPTS / "build_semantic_evidence.py"),
                    "--prd", str(prd), "--workflow-id", workflow_id, "--revision", args.revision,
                    "--out", str(semantic_input),
                ]
                if prototype:
                    semantic_cmd.extend(["--prototype", str(prototype)])
                if manifest:
                    semantic_cmd.extend(["--manifest", str(manifest)])
                if capability.is_file():
                    semantic_cmd.extend(["--capability-context", str(capability)])
                record("semanticEvidence", run(semantic_cmd, run_root), {"PASS", "BUILT"})
        if not semantic_reused_review:
            coverage = dd / "semantic-consistency-coverage.json"
            coverage_cmd = [sys.executable, str(SCRIPTS / "build_semantic_coverage.py"), "--semantic-input", str(semantic_input), "--prd", str(prd), "--out", str(coverage)]
            if prototype:
                coverage_cmd.extend(["--prototype", str(prototype)])
            if manifest:
                coverage_cmd.extend(["--manifest", str(manifest)])
            if capability.is_file():
                coverage_cmd.extend(["--capability-context", str(capability)])
            record("semanticCoverage", run(coverage_cmd, run_root))
            review_cmd = [
                sys.executable, str(SCRIPTS / "semantic_consistency_review.py"),
                "--input", str(semantic_input), "--coverage", str(coverage), "--out", str(semantic_review),
                "--transcript", str(semantic_transcript), "--review-plan-id", f"rederived-{workflow_id}-{args.revision}",
                "--target-handoff-id", f"{workflow_id}-delivery-{args.revision}",
            ]
            record("semanticReview", run(review_cmd, run_root), {"ACCEPTED"})

    policy_lock = dd / "policy-lock.json"
    obligations = dd / "generation-obligations.json"
    declarations = dd / "obligation-declarations.json"
    if obligations.is_file() and declarations.is_file():
        declaration_dir = args.declarations_dir.resolve() if args.declarations_dir else run_root / ".agents" / "policy" / "declarations"
        declaration_inputs = [declarations] if load(declarations, {}).get("declarations") else []
        if declaration_dir.is_dir():
            declaration_inputs.extend(sorted(path for path in declaration_dir.glob("*.json") if path.is_file()))
        if declaration_inputs:
            collect_cmd = [
                sys.executable, str(SCRIPTS / "collect_obligation_declarations.py"),
                "--obligations", str(obligations), "--out", str(declarations),
            ]
            if declaration_dir.is_dir():
                collect_cmd.extend(["--declarations-dir", str(declaration_dir)])
            for path in declaration_inputs:
                collect_cmd.extend(["--input", str(path)])
            collect_result = run(collect_cmd, run_root)
            steps.append({"step": "obligationDeclarationCollect", "status": "PASS" if collect_result["returnCode"] == 0 else "BLOCKED", "run": collect_result, "reportedStatus": collect_result.get("result", {}).get("status")})
            if collect_result["returnCode"] != 0:
                errors.append("obligation declaration collection failed")
            validation = dd / "obligation-declarations-validation.json"
            record("obligationDeclarations", run([
                sys.executable, str(SCRIPTS / "validate_obligation_declarations.py"),
                "--obligations", str(obligations), "--declarations", str(declarations), "--out", str(validation),
            ], run_root))
        else:
            steps.append({"step": "obligationDeclarations", "status": "PASS", "reportedStatus": "DEFERRED_UNTIL_PRODUCER_DECLARATIONS"})

    hardening_dir = dd / "hardening"
    hardening_dir.mkdir(parents=True, exist_ok=True)
    statuses = {"decisionImpact": "SKIPPED", "runtimeAcCoverage": "SKIPPED", "externalSkillContract": "SKIPPED"}
    reports: dict[str, str | None] = {"decisionImpact": None, "runtimeAcCoverage": None, "externalSkillContract": None}
    if args.decision_impact_mode != "off":
        output = hardening_dir / "decision-impact-graph.json"
        cmd = [sys.executable, str(SCRIPTS / "build_decision_impact_graph.py"), "--prd", str(prd), "--workflow-id", workflow_id, "--revision", args.revision, "--artifact-root", str(bundle), "--out", str(output)]
        context = dd / "decision-context.json"
        if context.is_file():
            cmd.extend(["--decision-context", str(context)])
        impact_input = args.decision_impact_input or (hardening_dir / "decision-impact-input.json")
        if impact_input.is_file():
            cmd.extend(["--impact-input", str(impact_input.resolve())])
        result = run(cmd, run_root)
        passed = result["returnCode"] == 0 and load(output, {}).get("status") == "PASS"
        steps.append({"step": "decisionImpact", "status": "PASS" if passed else "BLOCKED", "run": result})
        statuses["decisionImpact"] = "PASS" if passed else "BLOCKED"
        reports["decisionImpact"] = output.relative_to(bundle).as_posix() if output.is_file() else None
        if args.decision_impact_mode == "gate" and not passed:
            errors.append("decisionImpact gate failed")
    if args.runtime_ac_mode != "off":
        output = hardening_dir / "runtime-ac-coverage.json"
        cmd = [sys.executable, str(SCRIPTS / "validate_runtime_ac_coverage.py"), "--prd", str(prd), "--workflow-id", workflow_id, "--revision", args.revision, "--out", str(output)]
        runtime_input = args.runtime_ac_input or (hardening_dir / "runtime-ac-input.json")
        if runtime_input.is_file():
            cmd.extend(["--coverage-input", str(runtime_input.resolve())])
        result = run(cmd, run_root)
        passed = result["returnCode"] == 0 and load(output, {}).get("status") == "PASS"
        steps.append({"step": "runtimeAcCoverage", "status": "PASS" if passed else "BLOCKED", "run": result})
        statuses["runtimeAcCoverage"] = "PASS" if passed else "BLOCKED"
        reports["runtimeAcCoverage"] = output.relative_to(bundle).as_posix() if output.is_file() else None
        if args.runtime_ac_mode == "gate" and not passed:
            errors.append("runtimeAcCoverage gate failed")
    if args.external_contract_mode != "off":
        output = hardening_dir / "external-skill-contract.json"
        result = run([
            sys.executable, str(SCRIPTS / "validate_external_skill_contract.py"),
            "--bundle", str(bundle), "--profile", str(args.external_contract_profile.resolve()),
            "--workflow-id", workflow_id, "--revision", args.revision,
            "--artifact-profile", profile, "--stage", "PRE_FINAL_SEAL", "--out", str(output),
        ], run_root)
        passed = result["returnCode"] == 0 and load(output, {}).get("status") == "PASS"
        steps.append({"step": "externalSkillContract", "status": "PASS" if passed else "BLOCKED", "run": result})
        statuses["externalSkillContract"] = "PASS" if passed else "BLOCKED"
        reports["externalSkillContract"] = output.relative_to(bundle).as_posix() if output.is_file() else None
        if args.external_contract_mode == "gate" and not passed:
            errors.append("externalSkillContract gate failed")
    summary_path = hardening_dir / "hardening-summary.json"
    save(summary_path, {
        "schemaVersion": 1, "workflowId": workflow_id, "targetRevision": args.revision,
        "modes": {"decisionImpact": args.decision_impact_mode, "runtimeAcCoverage": args.runtime_ac_mode, "externalSkillContract": args.external_contract_mode},
        "statuses": statuses, "reports": reports, "blocked": [key for key, value in statuses.items() if value == "BLOCKED"], "checkedAt": now(),
    })

    quality_path = dd / "artifact-quality.json"
    quality_cmd = [
        sys.executable, str(SCRIPTS / "validate_delivery_artifacts.py"),
        "--prd", str(prd), "--artifact-profile", profile,
        "--producer-mode", downstream_mode, "--prd-producer-mode", prd_mode,
        "--overview", str(overview), "--jira", str(jira), "--out", str(quality_path),
    ]
    runtime = args.runtime.resolve() if args.runtime else (dd / "runtime-evidence.json" if (dd / "runtime-evidence.json").is_file() else None)
    if runtime:
        quality_cmd.extend(["--runtime", str(runtime)])
    if prototype:
        quality_cmd.extend(["--prototype", str(prototype)])
    if manifest:
        quality_cmd.extend(["--manifest", str(manifest)])
    quality_run = run(quality_cmd, run_root)
    record("artifactQuality", quality_run, {"PASS"})

    if quality_path.is_file() and not errors:
        run_quality = run_root / ".agents" / "quality"
        run_quality.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(quality_path, run_quality / "artifact-quality.json")
        artifacts = [
            {"kind": "PRD", "path": str(prd), "sha256": digest(prd)},
            {"kind": "OVERVIEW", "path": str(overview), "sha256": digest(overview)},
            {"kind": "JIRA_DESCRIPTION", "path": str(jira), "sha256": digest(jira)},
        ]
        if prototype:
            artifacts.append({"kind": "PROTOTYPE", "path": str(prototype), "sha256": digest(prototype)})
        package_evidence = load(run_quality / "package-evidence.json", {}) or {"schemaVersion": 1}
        package_evidence.update({
            "schemaVersion": 1, "workflowId": workflow_id, "artifactProfile": profile,
            "revision": args.revision, "artifacts": artifacts,
            "artifactQualityPath": str((run_quality / "artifact-quality.json").resolve()),
            "downstreamProducerMode": downstream_mode, "prdProducerMode": prd_mode,
            "policyLockPath": str(policy_lock), "policyLockSha256": digest(policy_lock),
            "generationObligationsPath": str(obligations), "generationObligationsSha256": digest(obligations),
            "hardeningSummaryPath": str(summary_path), "hardeningSummarySha256": digest(summary_path),
            "hardening": load(summary_path, {}), "createdAt": now(),
        })
        if prototype and manifest:
            package_evidence["prototypeManifestPath"] = str(manifest)
        save(run_quality / "package-evidence.json", package_evidence)

    candidate_run: dict[str, Any] | None = None
    if not errors:
        candidate_cmd = [
            sys.executable, str(SCRIPTS / "build_candidate_bundle.py"),
            "--bundle", str(bundle), "--workflow-id", workflow_id,
            "--requirement-name", workflow_id, "--revision", args.revision,
            "--refresh-projections", "--prd", str(prd), "--overview", str(overview), "--jira", str(jira),
        ]
        if prototype and manifest:
            candidate_cmd.extend(["--prototype", str(prototype), "--manifest", str(manifest)])
        candidate_run = run(candidate_cmd, run_root)
        steps.append({"step": "candidateSeal", "status": "PASS" if candidate_run["returnCode"] == 0 else "BLOCKED", "run": candidate_run})
        if candidate_run["returnCode"] != 0:
            errors.append("candidate seal rebuild failed")

    report = {
        "schemaVersion": 1, "status": "PASS" if not errors else "BLOCKED",
        "workflowId": workflow_id, "revision": args.revision, "artifactProfile": profile,
        "artifacts": {"prd": str(prd), "overview": str(overview), "jira": str(jira), "prototype": str(prototype) if prototype else None, "manifest": str(manifest) if manifest else None},
        "steps": steps, "errors": errors, "candidateSeal": str(dd / "candidate-seal.json") if (dd / "candidate-seal.json").is_file() else None,
        "hardeningSummary": str(summary_path), "generatedAt": now(),
    }
    save(report_path, report)
    print(json.dumps({"status": report["status"], "revision": args.revision, "steps": len(steps), "errors": errors, "out": str(report_path)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
