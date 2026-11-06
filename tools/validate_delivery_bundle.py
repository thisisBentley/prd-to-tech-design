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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
    if result in PASSING:
        executable = [c for c in checks if c.get("status") != "not_applicable"]
        if not executable:
            errors.append(f"{p.name}: PASS has no executable checks")
        if any(c.get("status") in {"unverified", "not_executed"} for c in checks):
            errors.append(f"{p.name}: PASS contains unverified/not_executed checks")
        if any(not (c.get("evidenceRefs") or []) for c in checks):
            errors.append(f"{p.name}: PASS has checks without evidenceRefs")
    if result == "NEEDS_FIX" and int(data.get("blockingCount", 0)) <= 0:
        errors.append(f"{p.name}: NEEDS_FIX requires a blocker")
    return data, errors


def extract_markdown_gate(text: str, gate: str) -> str | None:
    match = re.search(rf"^\|\s*{re.escape(gate)}\s*\|\s*([A-Z_]+)\s*\|", text, re.M)
    return match.group(1) if match else None


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

    # Q1 must be recomputed from upstream gates and blocker counts.
    upstream = ["R0", "G1", "O1", "U1", "U2", "QA"]
    upstream_passing = all(results[g] in PASSING for g in upstream)
    if upstream_passing and results["Q1"] not in PASSING:
        errors.append("Q1 is not consistent with all passing upstream gates")
    if not upstream_passing and results["Q1"] in PASSING:
        errors.append("Q1 PASS is not supported by upstream gate results")
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

    if final.get("status") == "DESIGN_READY":
        if any(results[g] not in PASSING for g in REQUIRED_GATES):
            errors.append("DESIGN_READY requires all seven gates passing")
        if open_blockers != 0:
            errors.append("DESIGN_READY requires zero blocking findings")
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
