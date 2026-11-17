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
from validate_json_schemas import validate as validate_schema
from build_audit_plan import artifact_snapshot, snapshot_sha256

REQUIRED_GATES = ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]
PASSING = {"PASS", "PASS_WITH_NONBLOCKING", "NOT_APPLICABLE", "NOT_TRIGGERED"}
HEX_RE = re.compile(r"^[a-f0-9]{64}$")
REVISION_PATH_RE = re.compile(r"(?:candidate-revisions|revisions)[/\\](r\d+)|browser-evidence[/\\][^/\\#]*?(r\d+)(?=[/\\#]|$)")
REVISION_VALUE_RE = re.compile(r"^r\d+$")
REVISION_KEYS = {"revision", "targetRevision", "sourceRevision", "prototypeRevision", "prdRevision", "candidateRevision", "finalRevision"}
HISTORICAL_KEYS = {
    "historicalEvidenceRefs",
    "archivedEvidenceRefs",
    "supersededEvidenceRefs",
    "staleRefs",
    "staleRevisionRefs",
    "activeStaleRefs",
    "archive",
    "archived",
}
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
if not SCHEMA_ROOT.exists():
    SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "references"


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


def stale_revision_refs(value: Any, current_revision: str, field: str = "$") -> list[dict[str, str]]:
    """Return non-current revision references from active evidence values only."""
    found: list[dict[str, str]] = []
    if not current_revision:
        return found
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            child = f"{field}.{key_text}"
            if key_text in HISTORICAL_KEYS or key_text.startswith(("historical", "archived", "superseded")):
                continue
            found.extend(stale_revision_refs(item, current_revision, child))
        return found
    if isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(stale_revision_refs(item, current_revision, f"{field}[{index}]"))
        return found
    if not isinstance(value, str):
        return found
    leaf = field.rsplit(".", 1)[-1]
    if leaf in REVISION_KEYS and REVISION_VALUE_RE.fullmatch(value) and value != current_revision:
        found.append({"field": field, "value": value, "expectedRevision": current_revision})
        return found
    for match in REVISION_PATH_RE.finditer(value):
        referenced = match.group(1) or match.group(2)
        if referenced and referenced != current_revision:
            found.append({"field": field, "value": value, "referencedRevision": referenced, "expectedRevision": current_revision})
    return found


def active_evidence_files(dd: Path, revision: str, review_run_id: str | None) -> list[Path]:
    files = [path for path in sorted(dd.glob("*.json")) if path.is_file()]
    gate_dir = dd / "gate-results" / revision
    if gate_dir.is_dir():
        files.extend(path for path in sorted(gate_dir.rglob("*.json")) if path.is_file())
    if review_run_id:
        review_dir = dd / "reviews" / review_run_id
        if review_dir.is_dir():
            for path in sorted(review_dir.rglob("*.json")):
                if not path.is_file():
                    continue
                relative_parts = path.relative_to(review_dir).parts
                if any(part.startswith("candidate-stage-bundle.") or part == "archive" for part in relative_parts):
                    continue
                files.append(path)
    return list(dict.fromkeys(files))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--semantic-review", type=Path)
    parser.add_argument("--require-audit", action="store_true", help="Require a passing Audit Track plan and summary.")
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

    ledger_path = dd / "findings.json"
    if ledger_path.is_file():
        ledger_errors: list[str] = []
        try:
            ledger = load(ledger_path)
            ledger_schema = load(SCHEMA_ROOT / "finding-ledger.schema.json")
            ledger_errors.extend(validate_schema(ledger, ledger_schema, ledger_schema))
            expected_workflow_id = final.get("workflowId") or candidate.get("workflowId")
            if expected_workflow_id and ledger.get("workflowId") != expected_workflow_id:
                ledger_errors.append(f"ledger workflowId {ledger.get('workflowId')!r} != final {expected_workflow_id!r}")
            if ledger.get("currentRevision") != revision:
                ledger_errors.append(f"ledger currentRevision {ledger.get('currentRevision')!r} != final {revision!r}")
            unresolved = [item.get("findingId") for item in ledger.get("entries", []) if item.get("status") not in {"resolved", "accepted_risk", "closed_by_decision"}]
            open_blocking = [item.get("findingId") for item in ledger.get("entries", []) if item.get("severity") == "BLOCKING" and item.get("status") not in {"resolved", "accepted_risk", "closed_by_decision"}]
            if unresolved:
                ledger_errors.append("ledger has unresolved findings: " + ", ".join(str(item) for item in unresolved))
            if open_blocking:
                ledger_errors.append("ledger has open blocking findings: " + ", ".join(str(item) for item in open_blocking))
        except Exception as exc:
            ledger_errors.append(f"invalid finding ledger: {exc}")
        checks.append(check(
            "INTEGRITY.FINDING_LEDGER",
            not ledger_errors,
            {"errors": ledger_errors, "path": str(ledger_path)},
            "finding ledger is schema-valid, current-revision bound and has no unresolved finding",
            [str(ledger_path), str(final_path)],
            "EVIDENCE",
        ))

    active_files = active_evidence_files(dd, revision, str(final.get("reviewRunId") or ""))
    stale_refs: list[dict[str, str]] = []
    for evidence_path in active_files:
        if evidence_path.suffix.lower() != ".json":
            continue
        try:
            payload = load(evidence_path)
        except Exception as exc:
            stale_refs.append({"file": str(evidence_path), "field": "$", "error": f"invalid active evidence JSON: {exc}"})
            continue
        for item in stale_revision_refs(payload, revision):
            stale_refs.append({"file": str(evidence_path), **item})
    stale_file_counts: dict[str, int] = {}
    for item in stale_refs:
        key = str(item.get("file", "unknown"))
        stale_file_counts[key] = stale_file_counts.get(key, 0) + 1
    checks.append(check(
        "INTEGRITY.ACTIVE_EVIDENCE_REFS",
        not stale_refs,
        {"staleFindingCount": len(stale_refs), "fileCounts": stale_file_counts, "findings": stale_refs[:50], "truncated": len(stale_refs) > 50},
        "active evidence references only the current revision; historical references stay in explicit archive fields",
        [str(path) for path in active_files],
        "EVIDENCE",
    ))

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

    hardening_errors: list[str] = []
    hardening_summary_path = dd / "hardening" / "hardening-summary.json"
    if hardening_summary_path.is_file():
        try:
            hardening = load(hardening_summary_path)
            modes = hardening.get("modes", {})
            statuses = hardening.get("statuses", {})
            for name, mode in modes.items():
                if mode == "gate" and statuses.get(name) != "PASS":
                    hardening_errors.append(f"{name}: gate mode has status {statuses.get(name, 'MISSING')}")
            for name, report_path in (hardening.get("reports") or {}).items():
                if not report_path:
                    continue
                resolved = Path(report_path)
                if not resolved.is_absolute():
                    resolved = root / resolved
                if not resolved.is_file():
                    hardening_errors.append(f"{name}: report missing: {report_path}")
        except Exception as exc:
            hardening_errors.append(f"hardening summary is invalid: {exc}")
        checks.append(check(
            "EVIDENCE.HARDENING",
            not hardening_errors,
            hardening_errors,
            "Decision Impact Graph, Runtime AC Coverage and External Skill Contract reports satisfy every gate-mode check",
            [str(hardening_summary_path)],
            "EVIDENCE",
        ))

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

    audit_plan_path = dd / "audit-plan.json"
    audit_summary_path = dd / "audit-summary.json"
    audit_report_path = dd / "audit-runner-report.json"
    audit_relevant = args.require_audit or audit_plan_path.exists() or audit_summary_path.exists() or audit_report_path.exists()
    audit_errors: list[str] = []
    if audit_relevant:
        if not audit_plan_path.is_file():
            audit_errors.append("audit-plan.json missing")
        if not audit_summary_path.is_file():
            audit_errors.append("audit-summary.json missing")
        if not audit_report_path.is_file():
            audit_errors.append("audit-runner-report.json missing")
        audit_plan = load(audit_plan_path) if audit_plan_path.is_file() else {}
        audit_summary = load(audit_summary_path) if audit_summary_path.is_file() else {}
        audit_report = load(audit_report_path) if audit_report_path.is_file() else {}
        for name, path, value, schema_name in (
            ("audit plan", audit_plan_path, audit_plan, "audit-plan.schema.json"),
            ("audit summary", audit_summary_path, audit_summary, "audit-summary.schema.json"),
            ("audit runner report", audit_report_path, audit_report, "audit-run-report.schema.json"),
        ):
            if path.is_file():
                schema = load(SCHEMA_ROOT / schema_name)
                audit_errors.extend(f"{name}: {issue}" for issue in validate_schema(value, schema, schema))
        if audit_plan and audit_plan.get("status") != "READY":
            audit_errors.append(f"audit plan status is {audit_plan.get('status')}")
        if audit_summary and audit_summary.get("status") != "AUDIT_PASS":
            audit_errors.append(f"audit summary status is {audit_summary.get('status')}")
        if audit_report:
            if audit_report.get("status") != "COMPLETE":
                audit_errors.append(f"audit runner status is {audit_report.get('status')}")
            if audit_report.get("auditStatus") != "AUDIT_PASS":
                audit_errors.append(f"audit runner auditStatus is {audit_report.get('auditStatus')}")
            if any(item.get("status") not in {"EXECUTED", "RESUMED"} for item in audit_report.get("jobs", [])):
                audit_errors.append("audit runner contains a job that did not execute")
            if any(item.get("artifactStable") is not True for item in audit_report.get("jobs", [])):
                audit_errors.append("audit runner contains an unstable artifact snapshot")
        for field in ("missingJobs", "missingRules", "failedJobs"):
            if audit_summary.get(field):
                audit_errors.append(f"audit summary has {field}: {audit_summary[field]}")
        if int(audit_summary.get("blockingFindingCount", 1)) != 0:
            audit_errors.append("audit summary has blocking findings")
        if audit_plan_path.is_file() and audit_summary:
            if audit_summary.get("auditPlanSha256") != sha256(audit_plan_path):
                audit_errors.append("audit summary does not bind the current audit plan")
        if audit_plan_path.is_file() and audit_report:
            if audit_report.get("auditPlanSha256") != sha256(audit_plan_path):
                audit_errors.append("audit runner report does not bind the current audit plan")
        for label, value in (("audit plan", audit_plan), ("audit summary", audit_summary), ("audit runner report", audit_report)):
            if value and value.get("revision") != revision:
                audit_errors.append(f"{label} revision does not match the delivery revision")
        if policy_lock.is_file():
            lock_hash = sha256(policy_lock)
            for label, value in (("audit plan", audit_plan), ("audit summary", audit_summary), ("audit runner report", audit_report)):
                if value and value.get("policyLockSha256") != lock_hash:
                    audit_errors.append(f"{label} does not bind the delivery policy lock")
        if audit_plan:
            expected_audit_snapshot = audit_plan.get("artifactHashes") or {}
            expected_audit_digest = snapshot_sha256(expected_audit_snapshot)
            audit_artifact_root = Path(str(audit_plan.get("artifactRoot") or ""))
            if not audit_artifact_root.is_absolute():
                audit_artifact_root = root / audit_artifact_root
            audit_artifact_root = audit_artifact_root.resolve()
            if not audit_artifact_root.is_dir():
                audit_errors.append("audit plan artifactRoot does not exist")
            else:
                current_audit_digest = snapshot_sha256(artifact_snapshot(audit_artifact_root))
                if expected_audit_digest != current_audit_digest:
                    audit_errors.append("audit plan artifact snapshot does not match its frozen artifactRoot")
            candidate_frozen = Path("")
            if candidate_path.is_file():
                candidate_data = load(candidate_path)
                frozen_value = str(candidate_data.get("frozenCopy") or "")
                candidate_frozen = Path(frozen_value)
                if candidate_frozen and not candidate_frozen.is_absolute():
                    candidate_frozen = root / candidate_frozen
                candidate_frozen = candidate_frozen.resolve() if candidate_frozen and str(candidate_frozen) not in {"", "."} else Path()
            if candidate_frozen and candidate_frozen != audit_artifact_root:
                audit_errors.append("audit artifactRoot does not match candidate-seal.frozenCopy")
            for label, value in (("audit runner report", audit_report),):
                if value:
                    if value.get("artifactRoot") != str(audit_artifact_root):
                        audit_errors.append(f"{label} artifactRoot does not bind the audit plan")
                    if value.get("artifactSnapshotSha256Before") != expected_audit_digest:
                        audit_errors.append(f"{label} before snapshot does not bind the audit plan")
                    if value.get("artifactSnapshotSha256After") != expected_audit_digest:
                        audit_errors.append(f"{label} after snapshot does not bind the audit plan")
        checks.append(check(
            "AUDIT.TRACK",
            not audit_errors,
            audit_errors,
            "independent audit plan is READY and every applicable rule has passing evidence with no blockers",
            [str(audit_plan_path), str(audit_summary_path), str(audit_report_path)],
            "AUDIT",
        ))

    failed = [item for item in checks if item["status"] == "failed"]
    content_failed = [item for item in failed if item["component"] == "CONTENT"]
    evidence_failed = [item for item in failed if item["component"] == "EVIDENCE"]
    bundle_failed = [item for item in failed if item["component"] == "BUNDLE"]
    content_ready = not content_failed
    evidence_ready = not evidence_failed
    bundle_ready = not bundle_failed
    audit_ready = not any(item["component"] == "AUDIT" for item in failed)
    if content_ready and evidence_ready and bundle_ready and audit_ready:
        status = "DESIGN_READY"
    elif not content_ready:
        status = "CONTENT_BLOCKED"
    elif not evidence_ready and not bundle_ready:
        status = "EVIDENCE_AND_BUNDLE_BLOCKED"
    elif not evidence_ready:
        status = "EVIDENCE_BLOCKED"
    elif not bundle_ready:
        status = "BUNDLE_BLOCKED"
    else:
        status = "AUDIT_BLOCKED"
    report = {
        "schemaVersion": 1,
        "bundle": str(root),
        "revision": revision,
        "status": status,
        "contentReady": content_ready,
        "evidenceReady": evidence_ready,
        "bundleReady": bundle_ready,
        "auditReady": audit_ready,
        "designReady": status == "DESIGN_READY",
        "checks": checks,
        "findings": [item["checkId"] for item in failed],
        "metrics": {"checks": len(checks), "passed": sum(1 for item in checks if item["status"] == "passed"), "failed": len(failed)},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "contentReady": content_ready, "evidenceReady": evidence_ready, "bundleReady": bundle_ready, "auditReady": audit_ready, "failedChecks": len(failed), "out": str(args.out)}, ensure_ascii=False))
    return 0 if status == "DESIGN_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
