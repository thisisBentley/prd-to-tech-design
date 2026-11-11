#!/usr/bin/env python3
"""Validate a sealed delivery bundle before finalization.

Checks candidate/final revision agreement, artifact hashes, required gate evidence,
decision/finding contracts, Gate/Workflow result consistency, and Q1 recomputation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REQUIRED_FILES = [
    "Jira_Description.md",
    "Overview.html",
    "PRD_DELIVERY.md",
    "Gates.md",
    "Workflow.md",
]
REQUIRED_GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASSING = {"PASS", "PASS_WITH_NONBLOCKING"}
MIN_PASS_CHECKS = {"R0": 1, "G1": 2, "O1": 2, "U1": 2, "U2": 2, "QA": 2, "Q1": 2}
SUSPICIOUS_WORKER_MARKERS = ("legacy", "old-workflow", "producer", "generator")
RULESET_ALLOWLIST_CANDIDATES = [
    Path(__file__).resolve().parents[1] / "references" / "approved-ruleset-versions.json",
    Path(__file__).resolve().parents[1] / "core" / "approved-ruleset-versions.json",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def approved_rulesets() -> set[str]:
    allowlist = next((path for path in RULESET_ALLOWLIST_CANDIDATES if path.exists()), None)
    if allowlist is None:
        return set()
    return {str(item) for item in read_json(allowlist).get("approved", []) if str(item).strip()}


def load_candidate(d: Path, revision: str) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    errors: list[str] = []
    seal_path = d / ".delivery" / "candidate-seal.json"
    if not seal_path.exists():
        return {}, {}, [f"missing {seal_path}"]
    seal = read_json(seal_path)
    if seal.get("revision") != revision:
        errors.append(f"candidate-seal revision {seal.get('revision')!r} != {revision!r}")
    frozen = seal.get("frozenCopy", "")
    if not frozen:
        errors.append("candidate-seal.frozenCopy is missing")
        return seal, {}, errors
    cr = d / frozen
    hashes = seal.get("artifactHashes") or {}
    for name, expected in hashes.items():
        p = cr / name
        if not p.exists():
            errors.append(f"frozen artifact missing: {p}")
            continue
        actual = sha256(p)
        if actual != expected:
            errors.append(f"frozen artifact hash mismatch: {name}")
    for suffix in REQUIRED_FILES:
        if not any(name.endswith(suffix) for name in hashes):
            errors.append(f"candidate seal is missing a required *{suffix} artifact")
    if "requirements.json" not in hashes:
        errors.append("candidate seal does not include requirements.json")
    return seal, hashes, errors


def validate_gate_result(p: Path, revision: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    if not p.exists():
        return {}, [f"missing gate result: {p}"]
    try:
        data = read_json(p)
    except Exception as exc:
        return {}, [f"invalid JSON {p}: {exc}"]
    if data.get("schemaVersion") != 2:
        errors.append(f"{p.name}: schemaVersion must be 2")
        return data, errors
    if data.get("revision") != revision:
        errors.append(f"{p.name}: revision mismatch")
    result = data.get("result")
    checks = data.get("checks") or []
    findings = data.get("findings") or []
    ruleset = str(data.get("ruleSetVersion", "")).strip()
    if ruleset not in approved_rulesets():
        errors.append(f"{p.name}: ruleSetVersion {ruleset!r} is not approved for formal PASS")
    tool = str(data.get("tool", "")).strip()
    if any(marker in tool.lower() for marker in SUSPICIOUS_WORKER_MARKERS):
        errors.append(f"{p.name}: tool {tool!r} is not an independent review worker")
    if result in PASSING:
        executable = [c for c in checks if c.get("status") != "not_applicable"]
        minimum = MIN_PASS_CHECKS.get(str(data.get("gate")), 1)
        if len(executable) < minimum:
            errors.append(f"{p.name}: PASS requires at least {minimum} executable checks")
        if any(c.get("status") in {"unverified", "not_executed", "failed"} for c in checks):
            errors.append(f"{p.name}: PASS contains failed/unverified/not_executed checks")
        if any(not (c.get("evidenceRefs") or []) for c in checks):
            errors.append(f"{p.name}: PASS has checks without evidenceRefs")
        if result == "PASS" and findings:
            errors.append(f"{p.name}: PASS cannot hide findings")
        if result == "PASS_WITH_NONBLOCKING" and not findings:
            errors.append(f"{p.name}: PASS_WITH_NONBLOCKING requires findings")
    if result == "NEEDS_FIX" and int(data.get("blockingCount", 0)) <= 0:
        errors.append(f"{p.name}: NEEDS_FIX requires a blocker")
    return data, errors


def extract_markdown_gate(text: str, gate: str) -> str | None:
    match = re.search(rf"^\|\s*{re.escape(gate)}\s*\|\s*([A-Z_]+)\s*\|", text, re.M)
    return match.group(1) if match else None


def named_hashes(value: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item):
                found[str(key)] = item
            found.update(named_hashes(item))
    elif isinstance(value, list):
        for item in value:
            found.update(named_hashes(item))
    return found


def validate_bundle(root: Path) -> list[str]:
    errors: list[str] = []
    final_path = root / ".delivery" / "final-seal.json"
    if not final_path.exists():
        return [f"missing {final_path}"]
    final = read_json(final_path)
    revision = final.get("revision")
    if not revision:
        return ["final-seal.revision is missing"]
    if final.get("revision") != revision:
        errors.append("final-seal revision mismatch")
    state_path = root / ".delivery" / "state.json"
    if state_path.exists():
        state = read_json(state_path)
        phase = state.get("phase2") or {}
        if phase.get("revision") != revision:
            errors.append(f"state phase2 revision {phase.get('revision')!r} != {revision!r}")
        if phase.get("bundleId") != final.get("bundleId"):
            errors.append("state phase2 bundleId != final bundleId")
    else:
        errors.append("missing .delivery/state.json")

    seal, hashes, seal_errors = load_candidate(root, revision)
    errors.extend(seal_errors)

    gate_dir = root / ".delivery" / "gate-results" / str(revision)
    results: dict[str, str] = {}
    completion: dict[str, str] = {}
    for gate in REQUIRED_GATES:
        data, gate_errors = validate_gate_result(gate_dir / f"{gate}.json", str(revision))
        errors.extend(gate_errors)
        results[gate] = data.get("result", "INCOMPLETE")
        completion[gate] = data.get("completionStatus", "not_executed")
        if results[gate] in PASSING and completion[gate] != "complete":
            errors.append(f"{gate}: PASS requires completionStatus=complete")

    # All formal gate results must come from the same independent worker run.
    def artifacts_ending(suffix: str) -> list[str]:
        return [name for name in hashes if name.endswith(suffix)]

    prototype_triggered = any(name.lower().endswith("prototype.html") for name in hashes)
    if prototype_triggered and not any(name.endswith("prototype-manifest.json") for name in hashes):
        errors.append("prototype bundle requires prototype-manifest.json in the candidate seal")
    required_consumed = {
        "R0": ["requirements.json"],
        "G1": artifacts_ending("PRD_DELIVERY.md"),
        "O1": artifacts_ending("Overview.html"),
        "U1": artifacts_ending("PRD_DELIVERY.md") + (artifacts_ending("Prototype.html") if prototype_triggered else []),
        "U2": artifacts_ending("Prototype.html") if prototype_triggered else [],
        "QA": artifacts_ending("PRD_DELIVERY.md"),
        "Q1": artifacts_ending("PRD_DELIVERY.md"),
    }
    review_runs = set()
    for gate in REQUIRED_GATES:
        data_path = gate_dir / f"{gate}.json"
        if not data_path.exists():
            continue
        data = read_json(data_path)
        review_runs.add(data.get("reviewRunId"))
        if data.get("frozenCopy") != seal.get("frozenCopy"):
            errors.append(f"{gate}: frozenCopy does not match candidate seal")
        consumed = data.get("objectHashes") or {}
        if not consumed:
            errors.append(f"{gate}: objectHashes must not be empty")
        for name, expected in consumed.items():
            if name in hashes and expected != hashes[name]:
                errors.append(f"{gate}: object hash for {name} does not match candidate seal")
        for item in data.get("checks", []):
            if "HASH_STABILITY" not in str(item.get("checkId", "")).upper():
                continue
            for name, observed in named_hashes(item.get("observed") or {}).items():
                expected = consumed.get(name) or next((v for k, v in consumed.items() if Path(k).name == Path(name).name), None)
                if expected and observed != expected:
                    errors.append(f"{gate}: hash-stability observation for {name} does not match objectHashes")
        for name in required_consumed.get(gate, []):
            if name not in consumed:
                errors.append(f"{gate}: does not record consumed artifact {name}")
            elif consumed.get(name) != hashes.get(name):
                errors.append(f"{gate}: consumed artifact hash mismatch for {name}")
        if data.get("result") == "PASS_WITH_NONBLOCKING" and not data.get("findings"):
            errors.append(f"{gate}: PASS_WITH_NONBLOCKING requires at least one recorded finding")
    if len(review_runs) != 1 or None in review_runs:
        errors.append(f"gate reviewRunId values are not a single non-null run: {sorted(map(str, review_runs))}")
    review_run_id = next(iter(review_runs), None)
    if review_run_id:
        envelope_path = root / ".delivery" / "reviews" / str(review_run_id) / "envelope.json"
        if not envelope_path.exists():
            errors.append(f"missing independent review envelope: {envelope_path}")
        else:
            env = read_json(envelope_path)
            if env.get("reviewRunId") != review_run_id:
                errors.append("review envelope reviewRunId mismatch")
            if env.get("revision") != revision:
                errors.append("review envelope revision mismatch")
            worker = env.get("worker") or {}
            identity = str(worker.get("identity", "")).strip()
            if worker.get("kind") not in {"subagent", "process"} or not identity:
                errors.append("review envelope must identify an independent subagent/process worker")
            if any(marker in identity.lower() for marker in SUSPICIOUS_WORKER_MARKERS):
                errors.append(f"review envelope worker {identity!r} is not independent")
            env_hashes = env.get("inputHashes") or {}
            for name, expected in hashes.items():
                if env_hashes.get(name) != expected:
                    errors.append(f"review envelope input hash mismatch: {name}")
            transcript_ref = str(env.get("transcript", "")).strip()
            if not transcript_ref:
                errors.append("review envelope transcript is required")
            else:
                candidates = [
                    root / transcript_ref,
                    envelope_path.parent / transcript_ref,
                    root / ".delivery" / "reviews" / str(review_run_id) / transcript_ref,
                ]
                transcript_path = next((candidate for candidate in candidates if candidate.exists()), None)
                if transcript_path is None or transcript_path.stat().st_size == 0:
                    errors.append(f"review envelope transcript is missing or empty: {transcript_ref}")
            for gate in REQUIRED_GATES:
                gate_data = read_json(gate_dir / f"{gate}.json") if (gate_dir / f"{gate}.json").exists() else {}
                gate_tool = str(gate_data.get("tool", "")).strip()
                if gate_tool and gate_tool != identity:
                    errors.append(f"{gate}: tool {gate_tool!r} does not match review worker {identity!r}")

    # Prototype-triggered bundles require passing provenance and cross-artifact preflight.
    if prototype_triggered:
        provenance_path = root / ".delivery" / "source-provenance.json"
        if not provenance_path.exists():
            errors.append("missing source-provenance.json")
        else:
            prov = read_json(provenance_path)
            if prov.get("status") != "PASS":
                errors.append("source provenance did not pass")
            prototype_name = next((n for n in hashes if n.lower().endswith("prototype.html")), None)
            if prototype_name and prov.get("prototypeHash") != hashes.get(prototype_name):
                errors.append("source provenance prototype hash does not match candidate seal")

        preflight_path = root / ".delivery" / "cross-artifact-preflight.json"
        if not preflight_path.exists():
            errors.append("missing cross-artifact-preflight.json")
        else:
            pre = read_json(preflight_path)
            if pre.get("result") != "PASS" or int(pre.get("blockingFindings", 0)) != 0:
                errors.append("cross-artifact preflight did not pass")

    # Q1 must be recomputed from upstream gates and blocker counts.
    upstream = ["R0", "G1", "O1", "U1", "U2", "QA"]
    upstream_passing = all(results[g] in PASSING for g in upstream)
    if upstream_passing and results["Q1"] not in PASSING:
        errors.append("Q1 is not consistent with all passing upstream gates")
    if not upstream_passing and results["Q1"] in PASSING:
        errors.append("Q1 PASS is not supported by upstream gate results")
    upstream_findings = sum(
        len(read_json(gate_dir / f"{g}.json").get("findings", []))
        for g in upstream if (gate_dir / f"{g}.json").exists()
    )
    if results["Q1"] == "PASS" and upstream_findings:
        errors.append("Q1 PASS cannot hide nonblocking upstream findings")
    if results["Q1"] == "PASS_WITH_NONBLOCKING" and not upstream_findings:
        errors.append("Q1 PASS_WITH_NONBLOCKING requires at least one upstream finding")
    open_blockers = sum(int((gate_dir / f"{g}.json").exists() and read_json(gate_dir / f"{g}.json").get("blockingCount", 0) or 0) for g in upstream)
    if final.get("openBlockingFindings", 0) != open_blockers:
        errors.append(f"final openBlockingFindings {final.get('openBlockingFindings')} != {open_blockers}")

    # Gates.md / Workflow.md byte-consistency with final results.
    artifact_by_suffix = {}
    for name in hashes:
        artifact_by_suffix[name.split("_", 1)[-1] if "_" in name else name] = name
    gates_name = next((n for n in hashes if n.endswith("Gates.md")), None)
    workflow_name = next((n for n in hashes if n.endswith("Workflow.md")), None)
    cr = root / (seal.get("frozenCopy") or "")
    if gates_name:
        text = (cr / gates_name).read_text(encoding="utf-8")
        for gate in REQUIRED_GATES:
            shown = extract_markdown_gate(text, gate)
            if shown != results[gate]:
                errors.append(f"Gates.md {gate} shows {shown!r}, expected {results[gate]!r}")
    else:
        errors.append("candidate missing Gates.md")
    if workflow_name:
        wtext = (cr / workflow_name).read_text(encoding="utf-8")
        for gate in REQUIRED_GATES:
            shown = extract_markdown_gate(wtext, gate)
            if shown != results[gate]:
                errors.append(f"Workflow.md {gate} shows {shown!r}, expected {results[gate]!r}")
    else:
        errors.append("candidate missing Workflow.md")

    dc_path = root / ".delivery" / "decision-context.json"
    if not dc_path.exists():
        errors.append("DESIGN_READY requires .delivery/decision-context.json")
    elif read_json(dc_path).get("decisionReadiness") != "READY":
        errors.append("decision-context decisionReadiness must be READY")
    total_findings = sum(
        int(read_json(gate_dir / f"{g}.json").get("blockingCount", 0))
        for g in upstream
        if (gate_dir / f"{g}.json").exists()
    )
    frc_path = root / ".delivery" / "finding-repair-context.json"
    if total_findings > 0 and not frc_path.exists():
        errors.append("blocking findings require finding-repair-context.json")
    elif frc_path.exists():
        frc = read_json(frc_path)
        if frc.get("findingReadiness") != "READY":
            errors.append("finding-repair-context findingReadiness must be READY")
        if int(frc.get("openBlockingCount", -1)) != 0:
            errors.append("finding-repair-context openBlockingCount must be 0")

    if review_run_id and final.get("reviewRunId") != review_run_id:
        errors.append("final-seal reviewRunId does not match gate review run")
    if final.get("independentExecution") is not True:
        errors.append("final-seal independentExecution must be true")
    if final.get("artifactsUnchangedDuringReview") is not True:
        errors.append("final-seal artifactsUnchangedDuringReview must be true")

    if final.get("status") == "DESIGN_READY":
        if any(results[g] not in PASSING for g in REQUIRED_GATES):
            errors.append("DESIGN_READY requires all seven gates passing")
        if open_blockers != 0:
            errors.append("DESIGN_READY requires zero blocking findings")
        policy_lock_path = root / ".delivery" / "policy-lock.json"
        if not policy_lock_path.exists():
            errors.append("DESIGN_READY requires .delivery/policy-lock.json")
        else:
            policy_hash = sha256(policy_lock_path)
            for gate in REQUIRED_GATES:
                data_path = gate_dir / f"{gate}.json"
                if not data_path.exists():
                    continue
                gate_data = read_json(data_path)
                if (gate_data.get("objectHashes") or {}) and gate_data.get("policyLockSha256") != policy_hash:
                    errors.append(f"{gate}: policyLockSha256 does not match .delivery/policy-lock.json")
        if not (root / ".delivery" / "generation-obligations.json").exists():
            errors.append("DESIGN_READY requires .delivery/generation-obligations.json")
        if not (root / ".delivery" / "obligation-declarations.json").exists():
            errors.append("DESIGN_READY requires .delivery/obligation-declarations.json")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="01-delivery bundle root")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    errors = validate_bundle(args.bundle.resolve())
    result = {"status": "PASS" if not errors else "FAIL", "bundle": str(args.bundle), "errors": errors}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"status: {result['status']}")
        for error in errors:
            print(f"- {error}")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
