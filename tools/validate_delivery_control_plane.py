#!/usr/bin/env python3
"""Validate Delivery state across orchestration, readiness, seals and handoff."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

READY_STAGES = {
    "DELIVERY_SEALED",
    "DELIVERY_REVIEW",
    "TECH_PRD_DIAGNOSIS",
    "TECH_AUTHORING",
    "TECH_SEALED",
    "TECH_REVIEW",
    "PRODUCT_ACCEPTANCE_REVIEW",
    "FINAL_GATEKEEPER",
    "READY",
}
BLOCKED_STATUSES = {"BLOCKED_DECISION", "ESCALATED", "FAILED"}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def relative(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def check(
    check_id: str,
    passed: bool,
    observed: Any,
    expected: str,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "status": "passed" if passed else "failed",
        "observed": observed,
        "expected": expected,
        "evidenceRefs": evidence,
    }


def phase2_from(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.is_file():
        return {}, None
    data = load(path)
    phase2 = data.get("phase2") if isinstance(data.get("phase2"), dict) else data
    workflow_id = data.get("workflowId") or phase2.get("workflowId")
    return phase2, workflow_id


def latest_handoff(
    root: Path,
    orchestration: dict[str, Any],
    explicit: Path | None,
) -> Path | None:
    if explicit is not None:
        return explicit.resolve()
    registered: list[Path] = []
    for rel in orchestration.get("handoffs", []):
        path = resolve(root, str(rel))
        if path and path.is_file() and str(load(path).get("phase", "")) == "delivery":
            registered.append(path)
    if registered:
        return max(registered, key=lambda item: (str(load(item).get("createdAt", "")), str(item)))
    candidates = sorted((root / ".agents" / "handoffs").glob("delivery-*.json"), key=lambda item: item.stat().st_mtime)
    return candidates[-1].resolve() if candidates else None


def validate(
    run_root: Path,
    bundle: Path,
    readiness_path: Path,
    handoff_override: Path | None,
) -> dict[str, Any]:
    root = run_root.resolve()
    bundle = bundle.resolve()
    dd = bundle / ".delivery"
    checks: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []

    bundle_state_path = dd / "state.json"
    root_state_path = root / ".delivery" / "state.json"
    if not bundle_state_path.is_file() and root_state_path.is_file():
        bundle_state_path = root_state_path
    delivery, state_workflow_id = phase2_from(bundle_state_path)
    candidate_path = dd / "candidate-seal.json"
    final_path = dd / "final-seal.json"
    orchestration_path = root / ".agents" / "orchestration.json"
    candidate = load(candidate_path) if candidate_path.is_file() else {}
    final = load(final_path) if final_path.is_file() else {}
    readiness = load(readiness_path) if readiness_path.is_file() else {}
    orchestration = load(orchestration_path) if orchestration_path.is_file() else {}
    handoff_path = latest_handoff(root, orchestration, handoff_override)
    handoff = load(handoff_path) if handoff_path and handoff_path.is_file() else {}

    delivery_revision = str(delivery.get("revision") or delivery.get("candidateRevision") or "")
    candidate_revision = str(candidate.get("revision") or "")
    final_revision = str(final.get("revision") or "")
    readiness_revision = str(readiness.get("revision") or "")
    handoff_revision = str(handoff.get("revision") or "")
    revision = final_revision or candidate_revision or delivery_revision or readiness_revision or handoff_revision

    workflow_id = str(
        state_workflow_id
        or handoff.get("workflowId")
        or orchestration.get("workflowId")
        or ""
    )

    evidence = {
        "delivery": str(bundle_state_path),
        "candidate": str(candidate_path),
        "final": str(final_path),
        "readiness": str(readiness_path),
        "orchestration": str(orchestration_path),
        "handoff": str(handoff_path) if handoff_path else str(root / ".agents" / "handoffs"),
    }

    required_missing = []
    if not bundle_state_path.is_file():
        required_missing.append(relative(root, bundle_state_path))
    if not candidate_path.is_file():
        required_missing.append(relative(root, candidate_path))
    if not final_path.is_file():
        required_missing.append(relative(root, final_path))
    if not readiness_path.is_file():
        required_missing.append(relative(root, readiness_path))
    if not orchestration_path.is_file():
        required_missing.append(relative(root, orchestration_path))
    if not handoff_path or not handoff_path.is_file():
        required_missing.append(relative(root, handoff_path) if handoff_path else ".agents/handoffs/delivery-*.json")
    checks.append(check("STATE.REQUIRED_FILES", not required_missing, required_missing, "all control-plane state files exist", list(evidence.values())))

    revision_values = {
        "delivery": delivery_revision,
        "candidateSeal": candidate_revision,
        "finalSeal": final_revision,
        "readiness": readiness_revision,
        "handoff": handoff_revision,
    }
    revision_mismatches = {key: value for key, value in revision_values.items() if value != revision}
    if not revision:
        revision_mismatches["revision"] = "missing"
    checks.append(check("STATE.REVISION_BINDING", not revision_mismatches, revision_mismatches, "delivery state, seals, readiness and handoff bind one revision", list(evidence.values())))
    if revision_mismatches:
        conflicts.append({"code": "REVISION_MISMATCH", "message": f"control-plane revisions disagree: {revision_mismatches}", "evidenceRefs": list(evidence.values())})

    workflow_values = {
        "delivery": state_workflow_id,
        "orchestration": orchestration.get("workflowId"),
        "handoff": handoff.get("workflowId"),
    }
    workflow_mismatches = {key: value for key, value in workflow_values.items() if value != workflow_id}
    if not workflow_id:
        workflow_mismatches["workflowId"] = "missing"
    checks.append(check("STATE.WORKFLOW_BINDING", not workflow_mismatches, workflow_mismatches, "delivery, orchestration and handoff bind one workflowId", [evidence["delivery"], evidence["orchestration"], evidence["handoff"]]))
    if workflow_mismatches:
        conflicts.append({"code": "WORKFLOW_MISMATCH", "message": f"control-plane workflowIds disagree: {workflow_mismatches}", "evidenceRefs": [evidence["delivery"], evidence["orchestration"], evidence["handoff"]]})

    readiness_ok = readiness.get("status") == "DESIGN_READY" and readiness.get("designReady") is True
    checks.append(check("STATE.READINESS", readiness_ok, {"status": readiness.get("status"), "designReady": readiness.get("designReady")}, "readiness is DESIGN_READY with designReady=true", [evidence["readiness"]]))
    if not readiness_ok:
        conflicts.append({"code": "READINESS_NOT_READY", "message": f"readiness is {readiness.get('status')} / designReady={readiness.get('designReady')}", "evidenceRefs": [evidence["readiness"]]})

    seal_ok = bool(revision) and candidate_revision == final_revision == delivery_revision == revision
    if final.get("status") not in (None, "DESIGN_READY"):
        seal_ok = False
    frozen_value = str(candidate.get("frozenCopy") or "")
    frozen = resolve(bundle, frozen_value)
    frozen_expected = frozen is not None and frozen.name == revision and frozen.is_dir()
    checks.append(check("STATE.SEALS", seal_ok and frozen_expected, {"candidate": candidate_revision, "final": final_revision, "delivery": delivery_revision, "finalStatus": final.get("status"), "frozenCopy": frozen_value, "frozenExists": frozen_expected}, "candidate/final/delivery revisions and final status agree and frozenCopy is current", [evidence["candidate"], evidence["final"], evidence["delivery"]]))
    if not (seal_ok and frozen_expected):
        conflicts.append({"code": "SEAL_MISMATCH", "message": "candidate seal, final seal, delivery state or frozenCopy disagree", "evidenceRefs": [evidence["candidate"], evidence["final"], evidence["delivery"]]})

    open_findings = handoff.get("openFindings") or []
    handoff_ok = (
        bool(handoff)
        and handoff.get("phase") == "delivery"
        and handoff_revision == revision
        and handoff.get("workflowId") == workflow_id
        and len(open_findings) == 0
    )
    checks.append(check("STATE.HANDOFF", handoff_ok, {"handoffId": handoff.get("handoffId"), "phase": handoff.get("phase"), "revision": handoff_revision, "workflowId": handoff.get("workflowId"), "openFindings": open_findings}, "latest Delivery handoff is current, closed and workflow-bound", [evidence["handoff"]]))
    if not handoff_ok:
        conflicts.append({"code": "HANDOFF_MISMATCH", "message": "latest Delivery handoff is missing, stale or has open findings", "evidenceRefs": [evidence["handoff"]]})

    registered_paths = {str(resolve(root, str(item))) for item in orchestration.get("handoffs", []) if resolve(root, str(item))}
    handoff_registered = bool(handoff_path) and str(handoff_path.resolve()) in registered_paths
    checks.append(check("STATE.HANDOFF_REGISTERED", handoff_registered, {"handoff": str(handoff_path.resolve()) if handoff_path else None, "registeredCount": len(registered_paths)}, "latest Delivery handoff is registered in orchestration state", [evidence["orchestration"], evidence["handoff"]]))
    if not handoff_registered:
        conflicts.append({"code": "HANDOFF_NOT_REGISTERED", "message": "latest Delivery handoff is not registered in orchestration state", "evidenceRefs": [evidence["orchestration"], evidence["handoff"]]})

    current_stage = str(orchestration.get("currentStage") or "")
    orchestration_status = str(orchestration.get("status") or "")
    stage_ok = current_stage in READY_STAGES and orchestration_status not in BLOCKED_STATUSES
    checks.append(check("STATE.ORCHESTRATION_STAGE", stage_ok, {"status": orchestration_status, "currentStage": current_stage}, "DESIGN_READY delivery is at DELIVERY_SEALED or a later non-blocked orchestration stage", [evidence["orchestration"]]))
    if not stage_ok:
        conflicts.append({"code": "ORCHESTRATION_STAGE_MISMATCH", "message": f"orchestration is {orchestration_status}/{current_stage} while Delivery is DESIGN_READY", "evidenceRefs": [evidence["orchestration"]]})

    delivery_state = {
        "path": relative(root, bundle_state_path) or "",
        "status": delivery.get("status"),
        "revision": delivery_revision or None,
        "bundleId": delivery.get("bundleId"),
    }
    orchestration_state = {
        "path": relative(root, orchestration_path) or "",
        "workflowId": orchestration.get("workflowId"),
        "status": orchestration.get("status"),
        "currentStage": orchestration.get("currentStage"),
    }
    readiness_state = {
        "path": relative(root, readiness_path) or "",
        "status": readiness.get("status"),
        "revision": readiness_revision or None,
        "designReady": readiness.get("designReady") is True,
    }
    seal_state = {
        "candidateRevision": candidate_revision or None,
        "finalRevision": final_revision or None,
        "finalStatus": final.get("status"),
        "frozenCopy": frozen_value or None,
    }
    handoff_state = {
        "path": relative(root, handoff_path),
        "handoffId": handoff.get("handoffId"),
        "revision": handoff_revision or None,
        "workflowId": handoff.get("workflowId"),
        "phase": handoff.get("phase"),
        "openFindingCount": len(open_findings),
    }
    failed = any(item["status"] == "failed" for item in checks)
    return {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "revision": revision,
        "status": "BLOCKED" if failed else "PASS",
        "deliveryState": delivery_state,
        "orchestrationState": orchestration_state,
        "readinessState": readiness_state,
        "sealState": seal_state,
        "handoffState": handoff_state,
        "checks": checks,
        "conflicts": conflicts,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--readiness", type=Path)
    parser.add_argument("--handoff", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_root.resolve()
    bundle = args.bundle.resolve() if args.bundle else root / "01-delivery"
    readiness = args.readiness.resolve() if args.readiness else root / ".agents" / "delivery-readiness.json"
    handoff = args.handoff.resolve() if args.handoff else None
    report = validate(root, bundle, readiness, handoff)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "conflicts": len(report["conflicts"]), "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
