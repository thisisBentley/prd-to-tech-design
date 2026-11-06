#!/usr/bin/env python3
"""Deterministic multi-agent workflow orchestrator.

The orchestrator schedules and validates structured handoffs and reviews. It does
not author business artifacts, decide product facts, or let a producer approve
its own work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_agent_contracts import (
    validate_decision,
    validate_escalation,
    validate_handoff,
    validate_review_plan,
    validate_review_result,
)

ACCEPTED = {"ACCEPTED", "ACCEPTED_WITH_ACTIONS"}
REQUIRED_REVIEWERS = {
    "DELIVERY_INTAKE_REVIEW": [("delivery-intake-reviewer", "discovery")],
    "DELIVERY_REVIEW": [("delivery-reviewer", "delivery"), ("qa-red-team", "delivery")],
    "TECH_PRD_DIAGNOSIS": [("tech-prd-diagnostician", "delivery")],
    "TECH_REVIEW": [("tech-reviewer", "tech-solution")],
    "PRODUCT_ACCEPTANCE_REVIEW": [("product-acceptance-reviewer", "tech-solution")],
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_path(run_root: Path) -> Path:
    return run_root / ".agents" / "orchestration.json"


def read_state(run_root: Path) -> tuple[Path, dict[str, Any]]:
    path = state_path(run_root)
    if not path.exists():
        raise SystemExit(f"missing orchestration state: {path}")
    return path, load(path)


def relative_or_absolute(run_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path.resolve())


def append_history(state: dict[str, Any], event: str, details: dict[str, Any] | None = None) -> None:
    state.setdefault("history", []).append({"at": now(), "event": event, **(details or {})})
    state["updatedAt"] = now()


def init_workflow(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    path = state_path(root)
    if path.exists() and not args.force:
        return {"status": "EXISTS", "state": str(path)}
    (root / ".agents" / "handoffs").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "reviews").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "escalations").mkdir(parents=True, exist_ok=True)
    stamp = now()
    state = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "requirement": {"id": args.requirement_id, "name": args.requirement_name},
        "status": "IN_PROGRESS",
        "currentStage": "DISCOVERY_AUTHORING",
        "createdAt": stamp,
        "updatedAt": stamp,
        "handoffs": [],
        "reviewPlans": [],
        "reviews": [],
        "decisions": [],
        "escalations": [],
        "history": [{"at": stamp, "event": "workflow_initialized"}],
    }
    save(path, state)
    return {"status": "READY", "state": str(path), "currentStage": state["currentStage"]}


def register_handoff(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    spath, state = read_state(root)
    path = args.file.resolve()
    handoff = load(path)
    errors = validate_handoff(handoff, str(path))
    if handoff.get("workflowId") != state.get("workflowId"):
        errors.append("handoff workflowId does not match state")
    for art in handoff.get("artifacts", []):
        raw = art.get("path", "")
        artifact = Path(raw)
        if not artifact.is_absolute():
            artifact = root / artifact
        if not artifact.exists():
            errors.append(f"handoff artifact does not exist: {artifact}")
        elif sha256(artifact) != art.get("sha256"):
            errors.append(f"handoff artifact hash mismatch: {artifact}")
    if errors:
        return {"status": "FAIL", "errors": errors}
    rel = relative_or_absolute(root, path)
    if rel not in state["handoffs"]:
        state["handoffs"].append(rel)
    append_history(state, "handoff_registered", {"handoffId": handoff["handoffId"], "phase": handoff["phase"], "path": rel})
    save(spath, state)
    return {"status": "REGISTERED", "handoffId": handoff["handoffId"], "phase": handoff["phase"]}


def register_review(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    spath, state = read_state(root)
    review_path = args.review.resolve()
    plan_path = args.plan.resolve()
    review = load(review_path)
    plan = load(plan_path)
    errors = validate_review_result(review, str(review_path)) + validate_review_plan(plan, str(plan_path))
    if review.get("workflowId") != state.get("workflowId"):
        errors.append("review workflowId does not match state")
    if plan.get("workflowId") != state.get("workflowId"):
        errors.append("review plan workflowId does not match state")
    for key in ["reviewRunId", "reviewerRole", "targetHandoffId", "targetRevision"]:
        if plan.get(key) != review.get(key):
            errors.append(f"review plan {key} does not match review")
    if review.get("reviewPlanId") != plan.get("reviewPlanId"):
        errors.append("review reviewPlanId does not match plan")
    handoffs = [load(root / p) for p in state.get("handoffs", [])]
    target = next((h for h in handoffs if h.get("handoffId") == review.get("targetHandoffId")), None)
    if not target:
        errors.append("review targetHandoffId is not registered")
    else:
        if target.get("revision") != review.get("targetRevision"):
            errors.append("review targetRevision does not match handoff")
        if target.get("fromAgent") == review.get("reviewerRole"):
            errors.append("reviewer cannot review its own handoff")
        if target.get("fromAgent") != review.get("producerRole"):
            errors.append("review producerRole does not match handoff fromAgent")
        if target.get("producerContextId") == review.get("reviewerContextId"):
            errors.append("review must use a context distinct from the producer context")
        if review.get("reviewerRole") not in (target.get("toAgents") or []):
            errors.append("reviewerRole is not an intended consumer of the handoff")
    transcript = Path(str(review.get("reviewerTranscript", "")))
    if not transcript.is_absolute():
        transcript = root / transcript
    if not transcript.exists():
        errors.append(f"reviewer transcript does not exist: {transcript}")
    for f in state["reviews"]:
        p = root / f
        if p.exists() and load(p).get("reviewRunId") == review.get("reviewRunId"):
            errors.append("duplicate reviewRunId")
    if errors:
        return {"status": "FAIL", "errors": errors}
    p_rel = relative_or_absolute(root, plan_path)
    r_rel = relative_or_absolute(root, review_path)
    if p_rel not in state["reviewPlans"]:
        state["reviewPlans"].append(p_rel)
    if r_rel not in state["reviews"]:
        state["reviews"].append(r_rel)
    append_history(state, "review_registered", {"reviewRunId": review["reviewRunId"], "reviewerRole": review["reviewerRole"], "verdict": review["verdict"], "targetHandoffId": review["targetHandoffId"]})
    save(spath, state)
    return {"status": "REGISTERED", "reviewRunId": review["reviewRunId"], "verdict": review["verdict"]}


def register_decision(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve(); spath, state = read_state(root)
    path = args.file.resolve(); data = load(path); errors = validate_decision(data, str(path))
    if data.get("workflowId") != state.get("workflowId"): errors.append("decision workflowId does not match state")
    if errors: return {"status": "FAIL", "errors": errors}
    rel = relative_or_absolute(root, path)
    if rel not in state["decisions"]: state["decisions"].append(rel)
    if data.get("status") not in {"confirmed", "closed"}:
        state["status"] = "BLOCKED_DECISION"
    else:
        open_decisions = []
        for other in state["decisions"]:
            item = load(root / other)
            if item.get("status") not in {"confirmed", "closed"}:
                open_decisions.append(item.get("decisionId"))
        if not open_decisions and state.get("status") == "BLOCKED_DECISION":
            state["status"] = "IN_PROGRESS"
    append_history(state, "decision_registered", {"decisionId": data["decisionId"], "status": data.get("status", "open")})
    save(spath, state); return {"status": "REGISTERED", "decisionId": data["decisionId"]}


def register_escalation(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve(); spath, state = read_state(root)
    path = args.file.resolve(); data = load(path); errors = validate_escalation(data, str(path))
    if data.get("workflowId") != state.get("workflowId"): errors.append("escalation workflowId does not match state")
    if errors: return {"status": "FAIL", "errors": errors}
    rel = relative_or_absolute(root, path)
    if rel not in state["escalations"]: state["escalations"].append(rel)
    state["status"] = "ESCALATED" if data.get("status") == "open" else state["status"]
    append_history(state, "escalation_registered", {"escalationId": data["escalationId"], "status": data.get("status")})
    save(spath, state); return {"status": "REGISTERED", "escalationId": data["escalationId"]}


def registered_handoffs(root: Path, state: dict[str, Any], phase: str | None = None) -> list[dict[str, Any]]:
    out = []
    for rel in state.get("handoffs", []):
        h = load(root / rel)
        if phase is None or h.get("phase") == phase:
            out.append(h)
    return out


def latest_handoff(root: Path, state: dict[str, Any], phase: str) -> dict[str, Any] | None:
    items = registered_handoffs(root, state, phase)
    return items[-1] if items else None


def registered_reviews(root: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    return [load(root / rel) for rel in state.get("reviews", [])]


def latest_review(root: Path, state: dict[str, Any], reviewer: str, handoff_id: str) -> dict[str, Any] | None:
    matches = [r for r in registered_reviews(root, state) if r.get("reviewerRole") == reviewer and r.get("targetHandoffId") == handoff_id]
    return matches[-1] if matches else None


def review_pair_verdict(root: Path, state: dict[str, Any], stage: str) -> tuple[str | None, list[str]]:
    errors = []
    verdicts = []
    for reviewer, phase in REQUIRED_REVIEWERS[stage]:
        handoff = latest_handoff(root, state, phase)
        if not handoff:
            returned = {reviewer: "RETURNED" for reviewer, _ in REQUIRED_REVIEWERS[stage]}
            errors.append(f"missing {phase} handoff")
            return None, errors
        review = latest_review(root, state, reviewer, handoff["handoffId"])
        if not review:
            errors.append(f"missing review by {reviewer}")
            return None, errors
        verdicts.append(review["verdict"])
    if any(v == "RETURNED" for v in verdicts): return "RETURNED", errors
    if any(v == "BLOCKED" for v in verdicts): return "BLOCKED", errors
    if any(v == "INCOMPLETE" for v in verdicts): return "INCOMPLETE", errors
    if all(v in ACCEPTED for v in verdicts): return "ACCEPTED", errors
    return None, errors


def advance_stage(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    stage = state["currentStage"]
    original = stage
    event = {"from": stage, "to": stage, "status": state["status"]}
    if state["status"] == "READY":
        return event
    if stage == "DISCOVERY_AUTHORING":
        if latest_handoff(root, state, "discovery"):
            state.update(currentStage="DELIVERY_INTAKE_REVIEW", status="IN_PROGRESS")
    elif stage == "DELIVERY_INTAKE_REVIEW":
        verdict, errors = review_pair_verdict(root, state, stage)
        if verdict == "ACCEPTED": state.update(currentStage="DELIVERY_AUTHORING", status="IN_PROGRESS")
        elif verdict == "RETURNED": state.update(currentStage="DISCOVERY_AUTHORING", status="RETURNED")
        elif verdict == "BLOCKED": state.update(status="BLOCKED_DECISION")
    elif stage == "DELIVERY_AUTHORING":
        if latest_handoff(root, state, "delivery"):
            state.update(currentStage="DELIVERY_SEALED", status="IN_PROGRESS")
    elif stage == "DELIVERY_SEALED":
        state.update(currentStage="DELIVERY_REVIEW", status="IN_PROGRESS")
    elif stage == "DELIVERY_REVIEW":
        verdict, _ = review_pair_verdict(root, state, stage)
        if verdict == "ACCEPTED": state.update(currentStage="TECH_PRD_DIAGNOSIS", status="IN_PROGRESS")
        elif verdict == "RETURNED": state.update(currentStage="DELIVERY_AUTHORING", status="RETURNED")
        elif verdict == "BLOCKED": state.update(status="BLOCKED_DECISION")
    elif stage == "TECH_PRD_DIAGNOSIS":
        verdict, _ = review_pair_verdict(root, state, stage)
        if verdict == "ACCEPTED": state.update(currentStage="TECH_AUTHORING", status="IN_PROGRESS")
        elif verdict == "RETURNED": state.update(currentStage="DELIVERY_AUTHORING", status="RETURNED")
        elif verdict == "BLOCKED": state.update(status="BLOCKED_DECISION")
    elif stage == "TECH_AUTHORING":
        if latest_handoff(root, state, "tech-solution"):
            state.update(currentStage="TECH_SEALED", status="IN_PROGRESS")
    elif stage == "TECH_SEALED":
        state.update(currentStage="TECH_REVIEW", status="IN_PROGRESS")
    elif stage == "TECH_REVIEW":
        verdict, _ = review_pair_verdict(root, state, stage)
        if verdict == "ACCEPTED": state.update(currentStage="PRODUCT_ACCEPTANCE_REVIEW", status="IN_PROGRESS")
        elif verdict == "RETURNED": state.update(currentStage="TECH_AUTHORING", status="RETURNED")
        elif verdict == "BLOCKED": state.update(status="BLOCKED_DECISION")
    elif stage == "PRODUCT_ACCEPTANCE_REVIEW":
        verdict, _ = review_pair_verdict(root, state, stage)
        if verdict == "ACCEPTED": state.update(currentStage="FINAL_GATEKEEPER", status="IN_PROGRESS")
        elif verdict == "RETURNED": state.update(currentStage="TECH_AUTHORING", status="RETURNED")
        elif verdict == "BLOCKED": state.update(status="BLOCKED_DECISION")
    event = {"from": original, "to": state["currentStage"], "status": state["status"]}
    if event != {"from": original, "to": original, "status": "READY"}:
        append_history(state, "stage_advanced", event)
    return event


def advance(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve(); spath, state = read_state(root)
    if state.get("status") in {"BLOCKED_DECISION", "ESCALATED", "FAILED"}:
        return {"status": "BLOCKED", "currentStage": state.get("currentStage"), "workflowStatus": state.get("status")}
    event = advance_stage(root, state)
    save(spath, state)
    return {"status": "ADVANCED", **event}


def check_state(root: Path, state: dict[str, Any]) -> list[str]:
    errors = []
    if state.get("status") in {"BLOCKED_DECISION", "ESCALATED"}:
        errors.append(f"workflow status is {state.get('status')}")
    for kind_name, paths in [("handoff", state.get("handoffs", [])), ("review-plan", state.get("reviewPlans", [])), ("review", state.get("reviews", [])), ("decision", state.get("decisions", [])), ("escalation", state.get("escalations", []))]:
        for rel in paths:
            p = root / rel
            if not p.exists():
                errors.append(f"missing registered {kind_name}: {p}")
    for rel in state.get("handoffs", []):
        data = load(root / rel)
        errors.extend(validate_handoff(data, rel))
        if data.get("workflowId") != state.get("workflowId"):
            errors.append(f"{rel}: workflowId mismatch")
    for rel in state.get("reviewPlans", []):
        data = load(root / rel)
        errors.extend(validate_review_plan(data, rel))
    for rel in state.get("reviews", []):
        data = load(root / rel)
        errors.extend(validate_review_result(data, rel))
        transcript = Path(str(data.get("reviewerTranscript", "")))
        if not transcript.is_absolute():
            transcript = root / transcript
        if not transcript.exists():
            errors.append(f"{rel}: reviewer transcript does not exist")
    for rel in state.get("decisions", []):
        data = load(root / rel)
        errors.extend(validate_decision(data, rel))
        if data.get("status") not in {"confirmed", "closed"}:
            errors.append(f"{rel}: open Decision Card blocks READY")
    for rel in state.get("escalations", []):
        data = load(root / rel)
        errors.extend(validate_escalation(data, rel))
        if data.get("status") == "open":
            errors.append(f"{rel}: open escalation blocks READY")
    return errors


def gatekeeper(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve(); spath, state = read_state(root)
    if state.get("currentStage") != "FINAL_GATEKEEPER":
        return {"status": "FAIL", "errors": [f"gatekeeper requires FINAL_GATEKEEPER, current={state.get('currentStage')}"]}
    errors = check_state(root, state)
    required = [
        ("DELIVERY_INTAKE_REVIEW", "delivery-intake-reviewer", "discovery"),
        ("DELIVERY_REVIEW", "delivery-reviewer", "delivery"),
        ("DELIVERY_REVIEW", "qa-red-team", "delivery"),
        ("TECH_PRD_DIAGNOSIS", "tech-prd-diagnostician", "delivery"),
        ("TECH_REVIEW", "tech-reviewer", "tech-solution"),
        ("PRODUCT_ACCEPTANCE_REVIEW", "product-acceptance-reviewer", "tech-solution"),
    ]
    evidence = []
    checks = []
    for stage, reviewer, phase in required:
        handoff = latest_handoff(root, state, phase)
        review = latest_review(root, state, reviewer, handoff["handoffId"]) if handoff else None
        check_id = f"GATEKEEPER.{stage}.{reviewer}"
        if not review or review.get("verdict") not in ACCEPTED or int(review.get("blockingCount", 1)) != 0:
            checks.append({"checkId": check_id, "status": "failed", "evidenceRefs": [rel for rel in state["reviews"] if rel.endswith(f"{reviewer}-review.json")] or ["orchestration-state"], "observed": "required review not accepted", "expected": "accepted with zero blockers"})
        else:
            rel = next(rel for rel in state["reviews"] if load(root / rel).get("reviewRunId") == review["reviewRunId"])
            evidence.append(rel)
            checks.append({"checkId": check_id, "status": "passed", "evidenceRefs": [rel], "observed": f"{reviewer} accepted", "expected": "accepted with zero blockers"})
    if any(c["status"] != "passed" for c in checks): errors.append("required review chain is not accepted")
    if errors:
        state["status"] = "FAILED"
        append_history(state, "gatekeeper_failed", {"errors": errors})
        save(spath, state)
        return {"status": "FAIL", "errors": errors, "checks": checks}
    review_id = "gatekeeper-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(3)
    out = (root / ".agents" / "reviews" / f"{review_id}.json")
    result = {
        "schemaVersion": 1,
        "reviewRunId": review_id,
        "reviewPlanId": "gatekeeper:" + state["workflowId"],
        "workflowId": state["workflowId"],
        "producerRole": "orchestrator",
        "reviewerRole": "deterministic-gatekeeper",
        "reviewType": "gatekeeper",
        "targetHandoffId": latest_handoff(root, state, "tech-solution")["handoffId"],
        "targetRevision": latest_handoff(root, state, "tech-solution")["revision"],
        "independentContext": True,
        "reviewerContextId": "gatekeeper-process",
        "reviewerTranscript": str(out.with_suffix(".log")),
        "verdict": "ACCEPTED",
        "completionStatus": "complete",
        "checks": checks,
        "findings": [],
        "blockingCount": 0,
        "evidenceRefs": evidence or ["orchestration-state"],
        "checkedAt": now(),
    }
    errs = validate_review_result(result, "gatekeeper")
    if errs:
        return {"status": "FAIL", "errors": errs}
    out.with_suffix(".log").write_text(
        "deterministic gatekeeper\n" + "\n".join(f"{c['checkId']} {c['status']} {','.join(c['evidenceRefs'])}" for c in checks) + "\n",
        encoding="utf-8",
    )
    save(out, result)
    state["reviews"].append(relative_or_absolute(root, out))
    state.update(status="READY", currentStage="READY")
    append_history(state, "gatekeeper_accepted", {"reviewRunId": review_id})
    save(spath, state)
    return {"status": "READY", "review": str(out), "reviewRunId": review_id}


def validate_root(root: Path) -> list[str]:
    spath = state_path(root)
    if not spath.exists(): return [f"missing state: {spath}"]
    state = load(spath)
    errors = check_state(root, state)
    if state.get("status") == "READY":
        gk = [r for r in registered_reviews(root, state) if r.get("reviewerRole") == "deterministic-gatekeeper" and r.get("verdict") == "ACCEPTED"]
        if not gk: errors.append("READY requires accepted deterministic gatekeeper")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--run-root", type=Path, required=True)
    init.add_argument("--workflow-id", required=True)
    init.add_argument("--requirement-name", required=True)
    init.add_argument("--requirement-id")
    init.add_argument("--force", action="store_true")
    handoff = sub.add_parser("register-handoff")
    handoff.add_argument("--run-root", type=Path, required=True); handoff.add_argument("--file", type=Path, required=True)
    review = sub.add_parser("register-review")
    review.add_argument("--run-root", type=Path, required=True); review.add_argument("--review", type=Path, required=True); review.add_argument("--plan", type=Path, required=True)
    decision = sub.add_parser("register-decision")
    decision.add_argument("--run-root", type=Path, required=True); decision.add_argument("--file", type=Path, required=True)
    escalation = sub.add_parser("register-escalation")
    escalation.add_argument("--run-root", type=Path, required=True); escalation.add_argument("--file", type=Path, required=True)
    adv = sub.add_parser("advance"); adv.add_argument("--run-root", type=Path, required=True)
    gate = sub.add_parser("gatekeeper"); gate.add_argument("--run-root", type=Path, required=True)
    validate = sub.add_parser("validate"); validate.add_argument("--run-root", type=Path, required=True)
    status = sub.add_parser("status"); status.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init": result = init_workflow(args)
    elif args.command == "register-handoff": result = register_handoff(args)
    elif args.command == "register-review": result = register_review(args)
    elif args.command == "register-decision": result = register_decision(args)
    elif args.command == "register-escalation": result = register_escalation(args)
    elif args.command == "advance": result = advance(args)
    elif args.command == "gatekeeper": result = gatekeeper(args)
    elif args.command == "validate":
        errors = validate_root(args.run_root.resolve()); result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    else:
        _, state = read_state(args.run_root.resolve()); result = {"status": state["status"], "currentStage": state["currentStage"], "workflowId": state["workflowId"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") not in {"FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
