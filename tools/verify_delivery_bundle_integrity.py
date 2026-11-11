#!/usr/bin/env python3
"""Verify content, evidence and bundle readiness for a delivery package."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from validate_prototype_binding import validate as validate_binding
from validate_obligation_declarations import validate_declarations

REQUIRED_GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASSING = {"PASS", "PASS_WITH_NONBLOCKING", "NOT_APPLICABLE", "NOT_TRIGGERED"}
HEX_RE = re.compile(r"^[a-f0-9]{64}$")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def find_artifact(root: Path, name: str, frozen: Path | None) -> Path | None:
    candidates = [root / name, root / ".delivery" / name]
    if frozen:
        candidates.append(frozen / name)
    return next((path for path in candidates if path.is_file()), None)


def first_glob(root: Path, pattern: str, frozen: Path | None = None) -> Path | None:
    for base in [root, root / ".delivery", *([frozen] if frozen else [])]:
        if base:
            matches = sorted(base.glob(pattern))
            if matches:
                return matches[0]
    return None


def walk_named_hashes(value: Any, prefix: str = "") -> dict[str, str]:
    found: dict[str, str] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and HEX_RE.fullmatch(item):
                found[str(key)] = item
            found.update(walk_named_hashes(item, str(key)))
    elif isinstance(value, list):
        for item in value:
            found.update(walk_named_hashes(item, prefix))
    return found


def check(check_id: str, passed: bool, observed: Any, expected: str, evidence: list[str], component: str) -> dict[str, Any]:
    return {"checkId": check_id, "component": component, "status": "passed" if passed else "failed", "observed": observed, "expected": expected, "evidenceRefs": evidence}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle.resolve()
    dd = root / ".delivery"
    checks: list[dict[str, Any]] = []
    findings: list[str] = []

    final_path = dd / "final-seal.json"
    candidate_path = dd / "candidate-seal.json"
    final = load(final_path) if final_path.exists() else {}
    candidate = load(candidate_path) if candidate_path.exists() else {}
    revision = str(final.get("revision") or candidate.get("revision") or "")
    frozen = root / (str(candidate.get("frozenCopy") or "")) if candidate.get("frozenCopy") else None
    final_hashes = final.get("artifactHashes") or {}
    candidate_hashes = candidate.get("artifactHashes") or {}
    all_names = sorted(set(final_hashes) | set(candidate_hashes))

    checks.append(check("INTEGRITY.FINAL_SEAL", final_path.is_file(), str(final_path), "final-seal exists", [str(final_path)], "EVIDENCE"))
    checks.append(check("INTEGRITY.CANDIDATE_SEAL", candidate_path.is_file(), str(candidate_path), "candidate-seal exists", [str(candidate_path)], "EVIDENCE"))

    artifact_paths: dict[str, Path] = {}
    missing_artifacts: list[str] = []
    artifact_mismatches: list[dict[str, str]] = []
    for name in all_names:
        path = find_artifact(root, name, frozen)
        if path is None:
            missing_artifacts.append(name)
            continue
        artifact_paths[name] = path
        actual = sha256(path)
        for label, expected in (("final", final_hashes.get(name)), ("candidate", candidate_hashes.get(name))):
            if expected and expected != actual:
                artifact_mismatches.append({"artifact": name, "source": label, "expected": expected, "actual": actual})
    checks.append(check("INTEGRITY.ARTIFACTS_PRESENT", not missing_artifacts, missing_artifacts, "all sealed artifacts are locatable", [str(root)], "BUNDLE"))
    checks.append(check("INTEGRITY.ARTIFACT_HASHES", not artifact_mismatches, artifact_mismatches, "final/candidate artifact hashes equal current bytes", [str(root)], "EVIDENCE"))

    gate_dir = dd / "gate-results" / revision
    gate_results: dict[str, dict[str, Any]] = {}
    gate_errors: list[str] = []
    gate_hashes: dict[str, dict[str, str]] = {}
    for gate in REQUIRED_GATES:
        path = gate_dir / f"{gate}.json"
        if not path.is_file():
            gate_errors.append(f"missing {gate}")
            continue
        data = load(path)
        gate_results[gate] = data
        gate_hashes[gate] = data.get("objectHashes") or {}
        if data.get("result") not in PASSING:
            gate_errors.append(f"{gate}={data.get('result')}")
    checks.append(check("INTEGRITY.GATES_PASS", not gate_errors, gate_errors, "all seven gates are PASS/PASS_WITH_NONBLOCKING/not applicable", [str(gate_dir)], "EVIDENCE"))

    observed_hash_mismatches: list[dict[str, str]] = []
    for gate, data in gate_results.items():
        object_hashes = data.get("objectHashes") or {}
        for item in data.get("checks", []):
            check_id = str(item.get("checkId", ""))
            if "HASH_STABILITY" not in check_id.upper():
                continue
            observed = walk_named_hashes(item.get("observed") or {})
            for name, value in observed.items():
                expected = object_hashes.get(name) or next((v for k, v in object_hashes.items() if Path(k).name == Path(name).name), None)
                if expected and value != expected:
                    observed_hash_mismatches.append({"gate": gate, "checkId": check_id, "artifact": name, "observed": value, "objectHash": expected})
    checks.append(check("INTEGRITY.GATE_INTERNAL_HASHES", not observed_hash_mismatches, observed_hash_mismatches, "hash-stability observations equal gate objectHashes", [str(gate_dir)], "EVIDENCE"))

    final_gate_mismatches: list[dict[str, str]] = []
    for gate, data in gate_results.items():
        declared = str((final.get("gateResults") or {}).get(gate, ""))
        if declared and declared != str(data.get("result")):
            final_gate_mismatches.append({"gate": gate, "finalSeal": declared, "gateResult": str(data.get("result"))})
    checks.append(check("INTEGRITY.FINAL_GATE_RESULTS", not final_gate_mismatches, final_gate_mismatches, "final-seal gate results equal gate outputs", [str(final_path), str(gate_dir)], "EVIDENCE"))

    review_runs = {str(data.get("reviewRunId", "")) for data in gate_results.values() if data.get("reviewRunId")}
    review_run_ok = len(review_runs) == 1 and str(final.get("reviewRunId")) in review_runs
    checks.append(check("INTEGRITY.REVIEW_RUN", review_run_ok, {"gateRuns": sorted(review_runs), "final": final.get("reviewRunId")}, "one review run is shared by all gates and final-seal", [str(final_path), str(gate_dir)], "EVIDENCE"))
    checks.append(check("INTEGRITY.INDEPENDENT", final.get("independentExecution") is True and final.get("artifactsUnchangedDuringReview") is True, {"independentExecution": final.get("independentExecution"), "artifactsUnchangedDuringReview": final.get("artifactsUnchangedDuringReview")}, "independent execution and unchanged artifacts are both true", [str(final_path)], "EVIDENCE"))

    # Bundle self-containment: primary artifacts and key evidence should be under the bundle root, not only a candidate revision.
    primary = [name for name in all_names if name.lower().endswith(("prd_delivery.md", "prototype.html", "overview.html", "jira_description.md", "gates.md", "workflow.md"))]
    not_self_contained = [name for name in primary if not (root / name).is_file()]
    requirements = root / "requirements.json"
    manifest_path = root / "prototype-manifest.json"
    decision_context = dd / "decision-context.json"
    prototype_path = next((root / name for name in all_names if name.lower().endswith("prototype.html") and (root / name).is_file()), None)
    if not prototype_path:
        prototype_path = next((frozen / name for name in all_names if name.lower().endswith("prototype.html") and frozen and (frozen / name).is_file()), None)
    if not requirements.is_file():
        not_self_contained.append("requirements.json")
    if prototype_path and not manifest_path.is_file():
        not_self_contained.append("prototype-manifest.json")
    if not decision_context.is_file():
        not_self_contained.append(".delivery/decision-context.json")
    if not final_path.is_file():
        not_self_contained.append(".delivery/final-seal.json")
    generation_obligations_path = dd / "generation-obligations.json"
    obligation_declarations_path = dd / "obligation-declarations.json"
    if not generation_obligations_path.is_file():
        not_self_contained.append(".delivery/generation-obligations.json")
    if not obligation_declarations_path.is_file():
        not_self_contained.append(".delivery/obligation-declarations.json")
    checks.append(check("INTEGRITY.SELF_CONTAINED", not not_self_contained, not_self_contained, "delivery root contains primary artifacts and key evidence", [str(root)], "BUNDLE"))

    binding_result: dict[str, Any] = {"status": "NOT_APPLICABLE"}
    prd_path = next((root / name for name in all_names if name.lower().endswith("prd_delivery.md") and (root / name).is_file()), None)
    if prototype_path:
        if manifest_path.is_file():
            binding_result = validate_binding(prototype_path, manifest_path, prd_path)
        else:
            binding_result = {"status": "FAIL", "findings": ["prototype-manifest.json missing"]}
        checks.append(check("INTEGRITY.PROTOTYPE_BINDING", binding_result.get("status") == "PASS", binding_result, "prototype manifest and data-ai bindings are complete", [str(prototype_path), str(manifest_path)], "CONTENT"))

    declaration_errors: list[str] = []
    if generation_obligations_path.is_file() and obligation_declarations_path.is_file():
        try:
            declaration_errors = validate_declarations(load(generation_obligations_path), load(obligation_declarations_path))
        except Exception as exc:
            declaration_errors = [f"declaration validation failed: {exc}"]
    else:
        declaration_errors = ["generation obligations or obligation declarations missing"]
    checks.append(check("CONTENT.OBLIGATION_DECLARATIONS", not declaration_errors, declaration_errors, "every declarationRequired obligation is declared with artifact, location and evidence", [str(generation_obligations_path), str(obligation_declarations_path)], "CONTENT"))

    content_errors: list[str] = []
    if not prd_path:
        content_errors.append("PRD missing")
    else:
        prd_text = prd_path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"FR-\d{3}", prd_text):
            content_errors.append("PRD has no FR IDs")
        if not re.search(r"AC-\d{3}", prd_text):
            content_errors.append("PRD has no AC IDs")
    semantic_path = args.semantic_review.resolve() if args.semantic_review else None
    if not semantic_path:
        semantic_path = next((p for p in [
            dd / "semantic-consistency-review.json",
            root / ".agents" / "semantics" / "semantic-aggregate.json",
            root / ".agents" / "reviews" / "SEMANTIC-FINAL-PACKAGE-REVIEW.review.json",
        ] if p.is_file()), None)
    semantic_status = "MISSING"
    if semantic_path:
        semantic = load(semantic_path)
        semantic_status = str(semantic.get("status") or semantic.get("verdict") or "INCOMPLETE")
        if semantic_status not in {"PASS", "PASS_WITH_NONBLOCKING", "ACCEPTED"}:
            content_errors.append(f"semantic review is {semantic_status}")
    else:
        content_errors.append("semantic review missing")
    checks.append(check("CONTENT.SEMANTIC_REVIEW", not content_errors, {"errors": content_errors, "semanticStatus": semantic_status}, "PRD has traceable FR/AC and semantic review is accepted", [str(prd_path) if prd_path else str(root), str(semantic_path) if semantic_path else str(root)], "CONTENT"))

    policy_lock = dd / "policy-lock.json"
    checks.append(check("INTEGRITY.POLICY_LOCK", policy_lock.is_file(), str(policy_lock), "frozen gate policy lock is present", [str(policy_lock)], "BUNDLE"))
    if policy_lock.is_file():
        lock_hash = sha256(policy_lock)
        mismatched_gate_locks = []
        for gate, data in gate_results.items():
            if data.get("policyLockSha256") != lock_hash:
                mismatched_gate_locks.append({"gate": gate, "gateLock": data.get("policyLockSha256"), "policyLock": lock_hash})
        checks.append(check("INTEGRITY.POLICY_LOCK_BINDING", not mismatched_gate_locks, mismatched_gate_locks, "every gate binds the same frozen policy lock", [str(policy_lock), str(gate_dir)], "EVIDENCE"))

    failed = [item for item in checks if item["status"] == "failed"]
    content_failed = [item for item in failed if item["component"] == "CONTENT"]
    evidence_failed = [item for item in failed if item["component"] == "EVIDENCE"]
    bundle_failed = [item for item in failed if item["component"] == "BUNDLE"]
    content_ready = not content_failed
    evidence_ready = not evidence_failed
    bundle_ready = not bundle_failed
    if content_ready and evidence_ready and bundle_ready:
        status = "DESIGN_READY"
    elif not content_ready:
        status = "CONTENT_BLOCKED"
    elif not evidence_ready and not bundle_ready:
        status = "EVIDENCE_AND_BUNDLE_BLOCKED"
    elif not evidence_ready:
        status = "EVIDENCE_BLOCKED"
    else:
        status = "BUNDLE_BLOCKED"
    report = {
        "schemaVersion": 1,
        "bundle": str(root),
        "revision": revision,
        "status": status,
        "contentReady": content_ready,
        "evidenceReady": evidence_ready,
        "bundleReady": bundle_ready,
        "designReady": status == "DESIGN_READY",
        "checks": checks,
        "findings": [item["checkId"] for item in failed],
        "metrics": {"checks": len(checks), "passed": sum(1 for item in checks if item["status"] == "passed"), "failed": len(failed)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "contentReady": content_ready, "evidenceReady": evidence_ready, "bundleReady": bundle_ready, "failedChecks": len(failed), "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "DESIGN_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
