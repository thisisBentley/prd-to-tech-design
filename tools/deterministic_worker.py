#!/usr/bin/env python3
"""Deterministic contract worker for autonomous PRD_ONLY regression runs."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def resolve_run_path(value: str) -> Path:
    path = Path(value)
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    return (run_root / path).resolve() if not path.is_absolute() else path.resolve()


def input_paths(task: dict) -> list[str]:
    return [str(resolve_run_path(item["path"])) for item in task.get("inputs", [])]


def prd_artifact_path(task: dict) -> Path:
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    return run_root / ".agents" / "artifacts" / "PRD_DELIVERY.md"


def write_prd(task: dict) -> Path:
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    requirement_path = next((path for path in input_paths(task) if path.endswith("requirement.md")), input_paths(task)[0])
    requirement = Path(requirement_path).read_text(encoding="utf-8")
    section = None
    functional: list[str] = []
    permissions: list[str] = []
    states: list[str] = []
    for raw in requirement.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            section = "permissions" if ("permission" in title or "权限" in title) else ("states" if ("state" in title or "状态" in title) else None)
            continue
        item = line.removeprefix("- ").strip()
        if section == "permissions":
            permissions.append(item)
        elif section == "states":
            states.append(item)
        else:
            functional.append(item)
    lines = [
        "# PRD_DELIVERY",
        "",
        "## Requirement Source",
        "",
        f"- source: {requirement_path}",
        "",
        "## Requirement Summary",
        "",
        requirement.strip(),
        "",
        "## Functional Requirements",
        "",
    ]
    if functional:
        lines.extend(f"- FR-{index:03d}: {line}" for index, line in enumerate(functional, start=1))
    else:
        lines.append("- FR-001: Implement the supplied requirement without the blocking marker.")
    lines.extend([
        "",
        "## Acceptance Criteria",
        "",
    ])
    for index, item in enumerate(functional or ["Implement the supplied requirement"], start=1):
        lines.append(f"- AC-{index:03d}: FR-{index:03d} is implemented and verifiable: {item}")
    lines.extend([
        "",
        "## Permissions",
        "",
    ])
    lines.extend(f"- {item}" for item in permissions or ["UNSPECIFIED role may interact with the feature"])
    lines.extend(["", "## States", ""])
    lines.extend(f"- {item}" for item in states or ["default: precondition explicitly defined by the requirement"])
    lines.extend([
        "",
        "## Exceptions and Recovery",
        "",
        "- Execution failure is isolated and recoverable according to the requirement.",
        "",
        "## Non-Goals",
        "",
        "- No facts outside the frozen requirement are introduced.",
    ])
    path = prd_artifact_path(task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _capability_context_ok(run_root: Path, task: dict) -> tuple[bool, list[str]]:
    context = run_root / ".agents" / "context" / "capability-context.json"
    if not context.exists():
        return True, []
    try:
        capability = json.loads(context.read_text(encoding="utf-8"))
    except Exception:
        return False, [str(context.resolve())]
    required = ["capabilityId", "canonicalName", "status", "sourceRefs", "confidence", "decisionStatus"]
    if any(not capability.get(key) for key in required):
        return False, [str(context.resolve())]
    if capability.get("decisionStatus") == "HOLD" or not capability.get("sourceRefs"):
        return False, [str(context.resolve())]
    prd = run_root / ".agents" / "artifacts" / "PRD_DELIVERY.md"
    requirement = next((Path(item["path"]) for item in task.get("inputs", []) if str(item.get("path", "")).endswith("requirement.md")), None)
    text = prd.read_text(encoding="utf-8") if prd.exists() else ""
    if requirement and requirement.exists():
        text += "\n" + requirement.read_text(encoding="utf-8")
    aliases = [capability.get("canonicalName", "")] + list(capability.get("knownAliases", []) or [])
    if any(alias in text for alias in aliases) and capability.get("canonicalName") not in text:
        return False, [str(context.resolve()), str(prd.resolve())]
    return True, [str(context.resolve())]


def _review_has_blocker(path: str) -> bool:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    return int(data.get("blockingCount", 0)) > 0


def write_review(task: dict) -> tuple[dict, Path]:
    role = task["role"]
    paths = input_paths(task)
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    prd = prd_artifact_path(task)
    if prd.exists() and not task["taskId"].startswith("DECISION"):
        paths = [str(prd)] + paths
    recheck = task["taskId"].startswith("RECHECK-")
    final_review = role == "final-package-reviewer"
    gatekeeper = role == "deterministic-gatekeeper"
    quality_exit = task["taskId"] == "DELIVERY-QUALITY-EXIT"
    review_sources = [path for path in paths if path.endswith(("requirement.md", "PRD_DELIVERY.md"))]
    original_blocking = any("BLOCKING" in Path(path).read_text(encoding="utf-8").upper() for path in review_sources)
    semantic_input = run_root / ".agents" / "context" / "semantic-consistency-input.json"
    if role == "semantic-consistency-reviewer" and semantic_input.exists():
        from semantic_consistency_review import load as load_semantic, review as semantic_review
        from build_semantic_coverage import evaluate as build_coverage
        transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"]).resolve()
        semantic_data = load_semantic(semantic_input)
        artifacts = {item.get("domain"): item for item in semantic_data.get("artifacts", [])}
        business_path = Path(artifacts.get("BUSINESS", {}).get("path", ""))
        if not business_path.is_absolute(): business_path = run_root / business_path
        interaction = artifacts.get("INTERACTION")
        interaction_path = Path(interaction.get("path", "")) if interaction else None
        if interaction_path and not interaction_path.is_absolute(): interaction_path = run_root / interaction_path
        capability_path = run_root / ".agents" / "context" / "capability-context.json"
        coverage = build_coverage(semantic_data, business_path, interaction_path if interaction_path and interaction_path.exists() else None, capability_path if capability_path.exists() else None, None)
        coverage_path = run_root / ".agents" / "reviews" / "SEMANTIC-CONSISTENCY-REVIEW.coverage.json"
        coverage_path.parent.mkdir(parents=True, exist_ok=True)
        coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        review = semantic_review(
            semantic_data, semantic_input, transcript,
            f"RP-{task['workflowId']}-SEMANTIC", f"HO-{task['workflowId']}-R1", coverage,
        )
        review_path = run_root / ".agents" / "reviews" / f"{task['taskId']}.review.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return review, review_path
    if gatekeeper:
        decision_paths = [path for path in paths if path.endswith("DECISION-READINESS.result.json")]
        decision_ready = True
        if quality_exit and decision_paths:
            try:
                decision_data = json.loads(Path(decision_paths[-1]).read_text(encoding="utf-8"))
                decision_ready = decision_data.get("readiness") == "READY" and decision_data.get("decision") == "PROCEED"
            except Exception:
                decision_ready = False
        evidence_bad = [path for path in paths if not Path(path).exists()]
        # Quality Exit is the authority for latest-review closure. Historical base
        # reviews remain immutable evidence and must not override accepted rechecks.
        stale_review = []
        escalation_dir = run_root / ".agents" / "escalations"
        open_escalations = list(escalation_dir.glob("*.json")) if escalation_dir.exists() else []
        capability_ok, capability_refs = _capability_context_ok(run_root, task)
        if evidence_bad or stale_review or open_escalations or not decision_ready or not capability_ok:
            verdict = "BLOCKED"
            findings = [{
                "findingId": f"F-{task['taskId']}-001",
                "severity": "BLOCKING",
                "title": "Delivery package has unresolved evidence or blockers",
                "evidenceRefs": evidence_bad or stale_review or [str(p.resolve()) for p in open_escalations] or capability_refs,
                "impact": "A deterministic gate cannot pass a package with missing evidence or unresolved blocking findings.",
                "closeCondition": "Repair the evidence chain and rerun affected reviews until all blocker counts are zero.",
                "owner": "prd-producer",
                "rootCauseId": "delivery-package-not-ready",
                "repairClass": "SEMANTIC",
                "expectedInvariant": "Every review in the final evidence chain has blockingCount=0 and every evidence path exists.",
                "regressionTests": ["rerun deterministic gatekeeper"],
            }]
        else:
            verdict = "ACCEPTED"
            findings = []
    elif recheck or final_review:
        verdict = "ACCEPTED"
        findings = []
    else:
        blocking = original_blocking
        verdict = "RETURNED" if blocking else "ACCEPTED"
        findings = []
        if blocking:
            findings.append({
                "findingId": f"F-{task['taskId']}-001",
                "severity": "BLOCKING",
                "title": "Requirement contains an explicit blocking marker",
                "evidenceRefs": paths,
                "impact": "PRD cannot be accepted while the frozen requirement declares BLOCKING.",
                "closeCondition": "Remove the explicit BLOCKING marker and rerun affected review.",
                "owner": "prd-producer",
                "rootCauseId": "requirement-blocking-marker",
                "repairClass": "SEMANTIC",
                "expectedInvariant": "PRD_ONLY requirement input must not contain a BLOCKING marker.",
                "regressionTests": ["rerun deterministic reviewer"],
            })
    checks = [{
        "checkId": f"{role}-{'recheck-closure' if recheck else ('final-package' if final_review else 'gate-policy' if gatekeeper else 'frozen-input')}",
        "status": "passed",
        "evidenceRefs": paths,
        "observed": "closure evidence accepted" if recheck else ("final package accepted" if final_review else ("gate policy accepted" if gatekeeper else ("no BLOCKING marker" if not original_blocking else "repair closure accepted"))),
        "expected": "accepted with zero blockers",
    }]
    review_id = "review-" + secrets.token_hex(4)
    review = {
        "schemaVersion": 1,
        "reviewRunId": review_id,
        "reviewPlanId": "plan-" + review_id,
        "workflowId": task["workflowId"],
        "producerRole": "prd-producer",
        "reviewerRole": role,
        "reviewType": "gatekeeper" if gatekeeper else "independent",
        "targetHandoffId": f"HO-{task['workflowId']}-R1",
        "targetRevision": "r1",
        "independentContext": True,
        "reviewerContextId": f"context-{role}-deterministic",
        "reviewerTranscript": str(Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"]).resolve()),
        "verdict": verdict,
        "completionStatus": "complete",
        "checks": checks,
        "findings": findings,
        "blockingCount": len(findings),
        "evidenceRefs": paths,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    review_path = run_root / ".agents" / "reviews" / f"{task['taskId']}.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return review, review_path


def write_handoff(task: dict) -> Path:
    run_root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    paths = input_paths(task)
    technical_gaps_path = run_root / ".agents" / "context" / "technical-gaps.json"
    technical_gaps = []
    if technical_gaps_path.exists():
        try:
            technical_gaps = json.loads(technical_gaps_path.read_text(encoding="utf-8")).get("gaps", [])
        except Exception:
            technical_gaps = [{"clue": "technical gaps evidence is unreadable", "nextAction": "repair technical-gaps.json", "evidenceRefs": [str(technical_gaps_path.resolve())]}]
    confirmed_decisions = []
    decision_dir = run_root / ".agents" / "decisions"
    if decision_dir.exists():
        for decision_path in sorted(decision_dir.glob("*.json")):
            try:
                decision = json.loads(decision_path.read_text(encoding="utf-8"))
                if decision.get("status") in {"confirmed", "closed"}:
                    confirmed_decisions.append(decision.get("decisionId"))
            except Exception:
                pass
    handoff = {
        "schemaVersion": 1,
        "handoffId": "HO-DELIVERY-READY-" + secrets.token_hex(4),
        "workflowId": task["workflowId"],
        "fromAgent": "prd-producer",
        "toAgents": ["tech-prd-diagnostician"],
        "phase": "delivery",
        "revision": "r1",
        "artifacts": [{"path": path, "sha256": Path(path).exists() and __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest() or "0" * 64, "kind": "delivery evidence"} for path in paths],
        "decisions": confirmed_decisions,
        "openFindings": [],
        "unknowns": [],
        "technicalUnknowns": technical_gaps,
        "requestedReviews": ["final-gatekeeper"],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "producerContextId": f"context-{task['role']}-deterministic",
        "artifactProfile": "PRD_ONLY",
        "prototypeStatus": "NOT_TRIGGERED",
        "uiOwnership": "NONE",
    }
    handoff_path = run_root / ".agents" / "handoffs" / "delivery-ready.handoff.json"
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text(json.dumps(handoff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return handoff_path


def main() -> int:
    manifest = Path(os.environ["AI_NATIVE_TASK_MANIFEST"])
    task = json.loads(manifest.read_text(encoding="utf-8"))
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    outputs = [{"path": output, "kind": "contract-smoke"} for output in task["expectedOutputs"]]
    review_path = None
    handoff_path = None
    artifact_path = None
    if task["taskId"] == "PRD-PRODUCE":
        artifact_path = write_prd(task)
        outputs.insert(0, {"path": str(artifact_path.resolve()), "kind": "PRD"})
    if task["taskId"].startswith("PRD-REPAIR-"):
        artifact_path = write_prd(task)
        outputs.insert(0, {"path": str(artifact_path.resolve()), "kind": "PRD"})
    if task.get("role") in {"delivery-reviewer", "qa-red-team", "tech-prd-diagnostician", "semantic-consistency-reviewer", "final-package-reviewer", "deterministic-gatekeeper"} or task["taskId"].startswith("RECHECK-"):
        review, review_path = write_review(task)
        outputs.append({"path": str(review_path), "kind": "review-result"})
    if task["taskId"] == "DELIVERY-HANDOFF":
        handoff_path = write_handoff(task)
        outputs.append({"path": str(handoff_path), "kind": "delivery-handoff"})
    payload = {
        "schemaVersion": 1,
        "status": "SUCCEEDED",
        "taskId": task["taskId"],
        "role": task["role"],
        "outputs": outputs,
    }
    if task["taskId"] == "DECISION-READINESS":
        payload.update({"readiness": "READY", "decision": "PROCEED", "blockingConditions": [], "requiredDecisions": [], "researchRecords": [], "resolvedFacts": [], "technicalGaps": [], "evidenceRefs": input_paths(task)})
    if artifact_path is not None:
        payload["producerMode"] = "deterministic"
        payload["prdArtifactPath"] = str(artifact_path.resolve())
        payload["prdArtifactSha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    if review_path is not None:
        payload["reviewResultPath"] = str(review_path.resolve())
        payload["verdict"] = review["verdict"]
    if handoff_path is not None:
        payload["handoffPath"] = str(handoff_path.resolve())
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if review_path is not None and task["taskId"] in {"DELIVERY-GATEKEEPER", "DELIVERY-QUALITY-EXIT"} and review.get("verdict") != "ACCEPTED":
        transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"])
        transcript.parent.mkdir(parents=True, exist_ok=True)
        transcript.write_text(f"deterministic gate blocked {task['taskId']}: {review.get('verdict')}\n", encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "taskId": task["taskId"], "verdict": review.get("verdict")}, ensure_ascii=False))
        return 1
    transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"])
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(f"contract worker completed {task['taskId']}\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
