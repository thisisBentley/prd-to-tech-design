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
import os
import secrets
import tempfile
from functools import wraps
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from build_context_pack import main as build_context_pack_main
from build_delivery_plan import build as build_delivery_plan
from reconcile_delivery import reconcile
from consolidate_findings import consolidate
from validate_artifact_profile import validate_profile, validate_prototype_contract
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
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


@contextmanager
def state_lock(run_root: Path):
    import fcntl
    lock_path = run_root / ".agents" / "orchestration.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked_mutation(func):
    @wraps(func)
    def wrapper(args):
        with state_lock(args.run_root.resolve()):
            return func(args)
    return wrapper


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


@locked_mutation
def init_workflow(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    path = state_path(root)
    if path.exists() and not args.force:
        return {"status": "EXISTS", "state": str(path)}
    (root / ".agents" / "handoffs").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "reviews").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "escalations").mkdir(parents=True, exist_ok=True)
    (root / ".agents" / "research").mkdir(parents=True, exist_ok=True)
    stamp = now()
    state = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "requirement": {"id": args.requirement_id, "name": args.requirement_name},
        "status": "IN_PROGRESS",
        "currentStage": "DISCOVERY_AUTHORING",
        "artifactProfile": args.artifact_profile,
        "prototypeStatus": args.prototype_status,
        "uiOwnership": args.ui_ownership,
        "createdAt": stamp,
        "updatedAt": stamp,
        "handoffs": [],
        "reviewPlans": [],
        "reviews": [],
        "decisions": [],
        "escalations": [],
        "researchRecords": [],
        "reviewGroups": [],
        "history": [{"at": stamp, "event": "workflow_initialized"}],
    }
    save(path, state)
    return {"status": "READY", "state": str(path), "currentStage": state["currentStage"]}


@locked_mutation
def register_handoff(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    spath, state = read_state(root)
    path = args.file.resolve()
    handoff = load(path)
    errors = validate_handoff(handoff, str(path))
    if handoff.get("workflowId") != state.get("workflowId"):
        errors.append("handoff workflowId does not match state")
    for profile_key in ("artifactProfile", "prototypeStatus", "uiOwnership"):
        value = handoff.get(profile_key)
        current = state.get(profile_key)
        if value is not None and current not in (None, "UNKNOWN") and value != current:
            errors.append(f"handoff {profile_key} does not match state")
        elif value is not None and current in (None, "UNKNOWN"):
            state[profile_key] = value
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


@locked_mutation
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


@locked_mutation
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


@locked_mutation
def register_research(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve(); spath, state = read_state(root)
    path = args.file.resolve(); data = load(path)
    from validate_agent_contracts import validate_research_record
    errors = validate_research_record(data, str(path))
    if data.get("workflowId") != state.get("workflowId"):
        errors.append("research workflowId does not match state")
    if errors: return {"status": "FAIL", "errors": errors}
    rel = relative_or_absolute(root, path)
    records = state.setdefault("researchRecords", [])
    if rel not in records: records.append(rel)
    append_history(state, "research_registered", {"researchId": data["researchId"], "verdict": data.get("verdict"), "decisionRequired": data.get("decisionRequired")})
    save(spath, state)
    return {"status": "REGISTERED", "researchId": data["researchId"], "verdict": data.get("verdict")}


@locked_mutation
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


@locked_mutation
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


@locked_mutation
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


def update_delivery_task(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    plan_path = args.plan.resolve()
    with state_lock(root):
        plan = load(plan_path)
        tasks = plan.get("tasks") or []
        task = next((item for item in tasks if item.get("taskId") == args.task_id), None)
        if task is None:
            return {"status": "FAIL", "errors": [f"unknown taskId: {args.task_id}"]}
        if args.action == "start":
            blocked = [dep for dep in task.get("dependencies", []) if next((item.get("status") for item in tasks if item.get("taskId") == dep), None) != "SUCCEEDED"]
            if blocked:
                return {"status": "BLOCKED", "taskId": args.task_id, "dependencies": blocked}
            if task.get("status") not in {"PENDING", "READY"}:
                return {"status": "FAIL", "errors": [f"task cannot start from status={task.get('status')}"]}
            task["status"] = "RUNNING"; task["startedAt"] = now(); task.pop("error", None)
        elif args.action == "complete":
            if task.get("status") != "RUNNING":
                return {"status": "FAIL", "errors": [f"task cannot complete from status={task.get('status')}"]}
            task["status"] = "SUCCEEDED"; task["completedAt"] = now()
            if args.result: task["resultPath"] = str(args.result)
        elif args.action == "fail":
            task["status"] = "FAILED"; task["completedAt"] = now(); task["error"] = args.error or "task failed"
        save(plan_path, plan)
        return {"status": "PASS", "taskId": args.task_id, "taskStatus": task["status"], "plan": str(plan_path)}

def sync_delivery_task_from_runtime(root: Path, plan_path: Path, task_id: str, runtime_record_path: Path) -> dict[str, Any]:
    from agent_runtime import load

    with state_lock(root):
        plan = load(plan_path)
        task = next((item for item in plan.get("tasks", []) if item.get("taskId") == task_id), None)
        if task is None:
            return {"status": "FAIL", "errors": [f"unknown taskId in plan: {task_id}"]}
        record = load(runtime_record_path)
        status = record.get("status")
        if status == "SUCCEEDED":
            task["status"] = "SUCCEEDED"
            task["completedAt"] = now()
            if record.get("structuredResultPath"):
                task["resultPath"] = record["structuredResultPath"]
            task.pop("error", None)
        elif status in {"FAILED", "CANCELLED"}:
            task["status"] = "FAILED"
            task["completedAt"] = now()
            task["error"] = record.get("error") or f"runtime status={status}"
        elif status in {"SPAWNED", "RUNNING"}:
            task["status"] = "RUNNING"
            if record.get("startedAt"):
                task["startedAt"] = record["startedAt"]
            elif not task.get("startedAt"):
                task["startedAt"] = now()
            task.pop("error", None)
        else:
            return {"status": "FAIL", "errors": [f"runtime status cannot sync task: {status}"]}
        task["runtimeRecordPath"] = str(runtime_record_path.resolve())
        save(plan_path, plan)
        return {"status": "PASS", "taskStatus": task["status"], "runtimeStatus": status}


def agent_spawn_command(args: argparse.Namespace) -> dict[str, Any]:
    from agent_runtime import spawn
    result = spawn(args)
    if args.plan and result.get("status") == "SPAWNED":
        record = Path(result["record"])
        sync = sync_delivery_task_from_runtime(args.run_root.resolve(), args.plan.resolve(), result["taskId"], record)
        result["taskSync"] = sync
        if sync.get("status") == "FAIL":
            result["status"] = "FAIL"
    return result


def agent_collect_command(args: argparse.Namespace) -> dict[str, Any]:
    from agent_runtime import collect
    result = collect(args)
    if args.plan and result.get("status") in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        record = Path(result["record"])
        sync = sync_delivery_task_from_runtime(args.run_root.resolve(), args.plan.resolve(), result["taskId"], record)
        result["taskSync"] = sync
        if sync.get("status") == "FAIL":
            result["status"] = "FAIL"
    return result

def reconcile_delivery_command(args: argparse.Namespace) -> dict[str, Any]:
    return reconcile(args.run_root.resolve(), args.plan.resolve())

def build_delivery_plan_command(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    state = load(state_path(root))
    result = build_delivery_plan(state, args.iteration)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "plan": str(args.out), "tasks": len(result["tasks"]), "artifactProfile": result["artifactProfile"]}

def build_context_pack_command(args: argparse.Namespace) -> dict[str, Any]:
    from build_context_pack import sha, load
    facts = []
    evidence = []
    rules = []
    forbidden = ["invent_product_facts", "modify_frozen_artifacts", "share_private_reasoning"]
    artifacts = []
    seen_facts, seen_evidence, seen_rules = set(), set(), set()
    for path in args.input:
        data = load(path)
        path_hash = sha(path)
        artifacts.append({"path": str(path.resolve()), "sha256": path_hash})
        for item in data.get("facts", []) or []:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_facts:
                facts.append({"id": item_id, "text": str(item["text"]), "sourceRef": str(item.get("sourceRef", path)), "sourceHash": str(item.get("sourceHash", path_hash))})
                seen_facts.add(item_id)
        for item in data.get("evidence", []) or []:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in seen_evidence:
                record = {"id": item_id, "ref": str(item.get("ref", path)), "sha256": str(item.get("sha256", path_hash))}
                if "quote" in item: record["quote"] = str(item["quote"])
                evidence.append(record); seen_evidence.add(item_id)
        for rule in data.get("rules", []) or []:
            if rule not in seen_rules: rules.append(str(rule)); seen_rules.add(rule)
    result = {"schemaVersion": 1, "packId": f"context-pack-{args.pack_type.lower()}-{secrets.token_hex(4)}", "packType": args.pack_type, "requirementId": args.requirement_id, "revision": args.revision, "sourceArtifacts": artifacts, "facts": facts, "evidence": evidence, "rules": rules, "forbidden": forbidden, "createdAt": now()}
    if args.project_id: result["projectId"] = args.project_id
    if args.role: result["role"] = args.role
    if args.scope: result["scope"] = args.scope
    if args.parent_pack_id: result["parentPackIds"] = args.parent_pack_id
    args.out.parent.mkdir(parents=True, exist_ok=True); args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "pack": str(args.out), "facts": len(facts), "evidence": len(evidence)}

def consolidate_findings_command(args: argparse.Namespace) -> dict[str, Any]:
    result = consolidate(args.review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": result["status"], "batch": str(args.out), "rootCauses": len(result.get("groups") or []), "blockingCount": result.get("blockingCount", 0)}

@locked_mutation
def review_group_init(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    spath, state = read_state(root)
    group_dir = root / ".agents" / "review-groups"
    group_dir.mkdir(parents=True, exist_ok=True)
    group_path = group_dir / f"{args.group_id}.json"
    if group_path.exists():
        return {"status": "EXISTS", "group": str(group_path)}
    group = {
        "schemaVersion": 1,
        "groupId": args.group_id,
        "workflowId": state["workflowId"],
        "stage": args.stage,
        "targetHandoffId": args.target_handoff_id,
        "targetRevision": args.target_revision,
        "requiredReviewers": args.reviewer,
        "status": "PENDING",
        "createdAt": now(),
        "updatedAt": now()
    }
    save(group_path, group)
    rel = relative_or_absolute(root, group_path)
    if rel not in state.setdefault("reviewGroups", []): state["reviewGroups"].append(rel)
    append_history(state, "review_group_initialized", {"groupId": args.group_id, "stage": args.stage, "reviewers": args.reviewer})
    save(spath, state)
    return {"status": "READY", "group": str(group_path), "groupId": args.group_id}


def review_group_status(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_root.resolve()
    _, state = read_state(root)
    groups = []
    for rel in state.get("reviewGroups", []):
        path = root / rel
        if not path.exists(): continue
        group = load(path)
        reviews = registered_reviews(root, state)
        matched = [r for r in reviews if r.get("targetHandoffId") == group.get("targetHandoffId") and r.get("targetRevision") == group.get("targetRevision") and r.get("reviewerRole") in group.get("requiredReviewers", [])]
        verdicts = {r.get("reviewerRole"): r.get("verdict") for r in matched}
        if any(v == "BLOCKED" for v in verdicts.values()): status = "BLOCKED"
        elif any(v == "RETURNED" for v in verdicts.values()): status = "RETURNED"
        elif any(v == "INCOMPLETE" for v in verdicts.values()): status = "INCOMPLETE"
        elif all(role in verdicts and verdicts[role] in ACCEPTED for role in group.get("requiredReviewers", [])): status = "ALL_ACCEPTED"
        else: status = "RUNNING" if matched else "PENDING"
        group["status"] = status
        group["reviews"] = verdicts
        group["updatedAt"] = now()
        save(path, group)
        groups.append(group)
    return {"status": "PASS", "groups": groups}


def validate_profile_command(args: argparse.Namespace) -> dict[str, Any]:
    profile = load(args.profile)
    errors = validate_profile(profile, str(args.profile))
    if args.prototype_contract:
        errors.extend(validate_prototype_contract(load(args.prototype_contract), str(args.prototype_contract)))
    return {"status": "PASS" if not errors else "FAIL", "profile": str(args.profile), "prototypeContract": str(args.prototype_contract) if args.prototype_contract else None, "errors": errors}


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
    init.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY", "UNKNOWN"], default="UNKNOWN")
    init.add_argument("--prototype-status", choices=["TRIGGERED", "NOT_TRIGGERED", "UNKNOWN"], default="UNKNOWN")
    init.add_argument("--ui-ownership", choices=["LOCAL", "EXTERNAL", "NONE", "UNKNOWN"], default="UNKNOWN")
    init.add_argument("--force", action="store_true")
    handoff = sub.add_parser("register-handoff")
    handoff.add_argument("--run-root", type=Path, required=True); handoff.add_argument("--file", type=Path, required=True)
    review = sub.add_parser("register-review")
    review.add_argument("--run-root", type=Path, required=True); review.add_argument("--review", type=Path, required=True); review.add_argument("--plan", type=Path, required=True)
    research = sub.add_parser("register-research")
    research.add_argument("--run-root", type=Path, required=True); research.add_argument("--file", type=Path, required=True)
    decision = sub.add_parser("register-decision")
    decision.add_argument("--run-root", type=Path, required=True); decision.add_argument("--file", type=Path, required=True)
    escalation = sub.add_parser("register-escalation")
    escalation.add_argument("--run-root", type=Path, required=True); escalation.add_argument("--file", type=Path, required=True)
    adv = sub.add_parser("advance"); adv.add_argument("--run-root", type=Path, required=True)
    gate = sub.add_parser("gatekeeper"); gate.add_argument("--run-root", type=Path, required=True)
    validate = sub.add_parser("validate"); validate.add_argument("--run-root", type=Path, required=True)
    status = sub.add_parser("status"); status.add_argument("--run-root", type=Path, required=True)
    profile = sub.add_parser("validate-profile", help="Validate Artifact Profile and Prototype Contract Preflight")
    profile.add_argument("--profile", type=Path, required=True)
    profile.add_argument("--prototype-contract", type=Path)
    group = sub.add_parser("review-group-init", help="Create a ReviewGroup")
    group.add_argument("--run-root", type=Path, required=True)
    group.add_argument("--group-id", required=True)
    group.add_argument("--stage", required=True)
    group.add_argument("--target-handoff-id", required=True)
    group.add_argument("--target-revision", required=True)
    group.add_argument("--reviewer", action="append", required=True)
    gstatus = sub.add_parser("review-group-status", help="Aggregate ReviewGroup status")
    gstatus.add_argument("--run-root", type=Path, required=True)
    batch = sub.add_parser("consolidate-findings", help="Consolidate Review findings by root cause")
    batch.add_argument("--review", action="append", type=Path, required=True)
    batch.add_argument("--out", type=Path, required=True)
    context = sub.add_parser("build-context-pack", help="Build a structured Context Pack")
    context.add_argument("--pack-type", choices=["PROJECT", "REQUIREMENT", "ROLE"], required=True)
    context.add_argument("--requirement-id", required=True)
    context.add_argument("--revision", required=True)
    context.add_argument("--input", action="append", type=Path, required=True)
    context.add_argument("--out", type=Path, required=True)
    context.add_argument("--project-id")
    context.add_argument("--role")
    context.add_argument("--scope", action="append", default=[])
    context.add_argument("--parent-pack-id", action="append", default=[])
    plan = sub.add_parser("build-delivery-plan", help="Build Delivery Producer/Reviewer/Repair task DAG")
    plan.add_argument("--run-root", type=Path, required=True)
    plan.add_argument("--iteration", default="r1")
    plan.add_argument("--out", type=Path, required=True)
    reconcile_parser = sub.add_parser("reconcile-delivery", help="Register review results and consolidate findings")
    reconcile_parser.add_argument("--run-root", type=Path, required=True)
    reconcile_parser.add_argument("--plan", type=Path, required=True)
    task_start = sub.add_parser("delivery-task-start", help="Start a Delivery Work Plan task")
    task_start.add_argument("--run-root", type=Path, required=True)
    task_start.add_argument("--plan", type=Path, required=True)
    task_start.add_argument("--task-id", required=True)
    task_complete = sub.add_parser("delivery-task-complete", help="Complete a Delivery Work Plan task")
    task_complete.add_argument("--run-root", type=Path, required=True)
    task_complete.add_argument("--plan", type=Path, required=True)
    task_complete.add_argument("--task-id", required=True)
    task_complete.add_argument("--result", type=Path)
    task_fail = sub.add_parser("delivery-task-fail", help="Fail a Delivery Work Plan task")
    task_fail.add_argument("--run-root", type=Path, required=True)
    task_fail.add_argument("--plan", type=Path, required=True)
    task_fail.add_argument("--task-id", required=True)
    task_fail.add_argument("--error")
    agent_spawn = sub.add_parser("agent-spawn", help="Spawn a runtime-neutral sub-agent task")
    agent_spawn.add_argument("--run-root", type=Path, required=True)
    agent_spawn.add_argument("--task", type=Path, required=True)
    agent_spawn.add_argument("--agent-id")
    agent_spawn.add_argument("--execute", action="store_true")
    agent_spawn.add_argument("--timeout", type=float)
    agent_spawn.add_argument("--force", action="store_true")
    agent_spawn.add_argument("--delivery-plan", "--plan", dest="plan", type=Path, help="Delivery Work Plan task to sync with runtime state")
    agent_collect = sub.add_parser("agent-collect", help="Collect a sub-agent structured result")
    agent_collect.add_argument("--run-root", type=Path, required=True)
    agent_collect.add_argument("--task-id", required=True)
    agent_collect.add_argument("--result", type=Path)
    agent_collect.add_argument("--review-plan", type=Path, help="Review Plan to auto-register after collect")
    agent_collect.add_argument("--review", type=Path, help="Review Result to auto-register after collect")
    agent_collect.add_argument("--cancel", action="store_true")
    agent_collect.add_argument("--delivery-plan", "--plan", dest="plan", type=Path, help="Delivery Work Plan task to sync with runtime state")
    agent_collect.add_argument("--error")
    args = parser.parse_args()
    if args.command == "init": result = init_workflow(args)
    elif args.command == "register-handoff": result = register_handoff(args)
    elif args.command == "register-review": result = register_review(args)
    elif args.command == "register-research": result = register_research(args)
    elif args.command == "register-decision": result = register_decision(args)
    elif args.command == "register-escalation": result = register_escalation(args)
    elif args.command == "advance": result = advance(args)
    elif args.command == "gatekeeper": result = gatekeeper(args)
    elif args.command == "validate":
        errors = validate_root(args.run_root.resolve()); result = {"status": "PASS" if not errors else "FAIL", "errors": errors}
    elif args.command == "validate-profile":
        result = validate_profile_command(args)
    elif args.command == "review-group-init":
        result = review_group_init(args)
    elif args.command == "review-group-status":
        result = review_group_status(args)
    elif args.command == "consolidate-findings":
        result = consolidate_findings_command(args)
    elif args.command == "build-context-pack":
        result = build_context_pack_command(args)
    elif args.command == "build-delivery-plan":
        result = build_delivery_plan_command(args)
    elif args.command == "reconcile-delivery":
        result = reconcile_delivery_command(args)
    elif args.command == "delivery-task-start":
        result = update_delivery_task(argparse.Namespace(**vars(args), action="start"))
    elif args.command == "delivery-task-complete":
        result = update_delivery_task(argparse.Namespace(**vars(args), action="complete"))
    elif args.command == "delivery-task-fail":
        result = update_delivery_task(argparse.Namespace(**vars(args), action="fail"))
    elif args.command == "agent-spawn":
        result = agent_spawn_command(args)
    elif args.command == "agent-collect":
        result = agent_collect_command(args)
        if result.get("status") == "SUCCEEDED" and args.plan and args.review:
            registered = register_review(argparse.Namespace(run_root=args.run_root, plan=args.review_plan, review=args.review))
            result["reviewRegistration"] = registered
            if registered.get("status") == "REGISTERED":
                result["status"] = "SUCCEEDED_AND_REGISTERED"
    else:
        _, state = read_state(args.run_root.resolve()); result = {"status": state["status"], "currentStage": state["currentStage"], "workflowId": state["workflowId"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") not in {"FAIL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
