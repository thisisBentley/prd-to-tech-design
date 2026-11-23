#!/usr/bin/env python3
"""Build isolated Product Manager and Architect review jobs from a consumer request."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value

COMMON_ARTIFACTS = ["prd", "overview", "jira", "prdReviewResult", "decisionContract", "decisionReadiness", "sourceLock"]
PROTOTYPE_ARTIFACTS = ["prototype", "prototypeManifest", "runtimeEvidence"]


def frozen_inputs(request: dict[str, Any]) -> list[dict[str, str]]:
    names = [*COMMON_ARTIFACTS]
    if request["artifactProfile"] in {"PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW"}:
        names.extend(PROTOTYPE_ARTIFACTS)
    result: list[dict[str, str]] = []
    for name in names:
        value = request["artifacts"].get(name)
        if not value:
            raise ValueError(f"missing required artifact: {name}")
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise ValueError(f"artifact not found: {path}")
        result.append({"path": str(path), "sha256": sha256_file(path)})
    return sorted(result, key=lambda item: item["path"])


def review_spec(role: str) -> dict[str, Any]:
    if role == "product-manager-consumer":
        return {
            "objective": "Independently decide whether the frozen PRD, Overview and optional Prototype are ready for a product review without asking the producer to fill missing business rules.",
            "questions": [
                "Are goals, scope, non-goals, roles, permissions, business rules, states, exceptions and acceptance criteria reviewable without interpretation?",
                "Are acceptance criteria executable by QA and tied to concrete FR/BR objects?",
                "Does Overview explain the proposal rather than merely repeat identifiers?",
                "If prototype is present, does it expose role, permission, error, empty and timeout behavior?",
            ],
            "evidenceTargets": ["prd", "overview", "jira", "prototype", "runtimeEvidence"],
            "counterexamples": [
                "A six-tab Overview containing only FR/AC identifiers is not reviewable.",
                "A Prototype with bindings but no exception or permission behavior does not prove the interaction.",
                "A structurally valid PRD that omits unresolved business decisions must be rejected.",
            ],
            "selectedChecks": ["PM.PRD.REVIEWABILITY", "PM.AC.EXECUTABLE", "PM.OVERVIEW.PROJECTION", "PM.PROTOTYPE.BEHAVIOR", "PM.RUNTIME.AUTHORITY"],
        }
    return {
        "objective": "Independently decide whether the frozen product facts, decision contract and source-locked technical evidence are sufficient to start architectural and technical design without rediscovering requirements.",
        "questions": [
            "Is the PRD review explicitly passed and the Decision Contract READY against the current PRD hash?",
            "Are FR/BR/AC fully traceable with zero open blocking decisions?",
            "Does the source lock contain resolvable authoritative current technical evidence?",
            "Can the architect identify interface, data, state, permission, exception and non-functional inputs without inventing product rules?",
        ],
        "evidenceTargets": ["prdReviewResult", "decisionContract", "decisionReadiness", "sourceLock", "prd"],
        "counterexamples": [
            "An internal PASS with a drifted Decision Contract cannot authorize technical design.",
            "A source lock with only the PRD or an unresolvable technical source is insufficient.",
            "Technical uncertainty that changes user-visible behavior must return to Delivery.",
        ],
        "selectedChecks": ["ARCH.PRD.REVIEW", "ARCH.DECISION.READY", "ARCH.TRACEABILITY", "ARCH.SOURCE.LOCK", "ARCH.CONSUMER.INDEPENDENCE"],
    }


def build_jobs(request: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    errors = validate_schema_value(request, "consumer-acceptance-request.schema.json")
    if errors:
        raise ValueError("invalid consumer request: " + "; ".join(errors))
    inputs = frozen_inputs(request)
    contexts = [request["producer"]["contextId"], request["productManager"]["contextId"], request["architect"]["contextId"]]
    roles = [request["producer"]["role"], request["productManager"]["role"], request["architect"]["role"]]
    if len(set(contexts)) != len(contexts) or len(set(roles)) != len(roles):
        raise ValueError("producer and consumer roles/contexts must be distinct")

    out_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    for actor_key, role in (("productManager", "product-manager-consumer"), ("architect", "architect-consumer")):
        actor = request[actor_key]
        if actor["role"] != role:
            raise ValueError(f"{actor_key}.role must be {role}")
        spec = review_spec(role)
        task_path = out_dir / f"{role}.task.json"
        plan_path = out_dir / f"{role}.review-plan.json"
        review_run_id = "CR-" + canonical_hash({"workflowId": request["workflowId"], "revision": request["targetRevision"], "role": role})[:16]
        handoff_id = "HO-" + canonical_hash({"caseId": request["caseId"], "revision": request["targetRevision"]})[:16]
        task = {
            "schemaVersion": 1,
            "taskId": f"TASK-{role.upper()}-{request['targetRevision']}",
            "workflowId": request["workflowId"],
            "stage": "consumer-acceptance",
            "role": role,
            "objective": spec["objective"],
            "inputs": inputs,
            "constraints": [
                "Read only the frozen inputs listed in this task.",
                "Do not modify PRD, Overview, Prototype, Decision Contract, Source Lock, Jira description or runtime evidence.",
                "Do not infer missing business rules or product decisions.",
                "Return a review-result JSON with evidence for every check.",
                "Reject thin content, unresolved decisions, hash drift or non-consumable technical inputs.",
                "Use a context distinct from the producer and the other consumer.",
            ],
            "expectedOutputs": [f"{role}.review-result.json"],
            "reviewMode": "independent-review",
            "artifactProfile": request["artifactProfile"],
            "readOnlyFrozenInputs": True,
            "writeScope": [str(task_path.parent.resolve())],
            "contextId": actor["contextId"],
            "producerRole": request["producer"]["role"],
            "reviewerRole": role,
            "reviewRunId": review_run_id,
            "targetHandoffId": handoff_id,
            "targetRevision": request["targetRevision"],
            "questions": spec["questions"],
            "evidenceTargets": spec["evidenceTargets"],
            "counterexamples": spec["counterexamples"],
            "selectedChecks": spec["selectedChecks"],
            "createdAt": now(),
            "timeoutSeconds": 600,
        }
        plan = {
            "schemaVersion": 1,
            "reviewPlanId": "RP-" + review_run_id,
            "reviewRunId": review_run_id,
            "workflowId": request["workflowId"],
            "reviewerRole": role,
            "targetHandoffId": handoff_id,
            "targetRevision": request["targetRevision"],
            "questions": spec["questions"],
            "evidenceTargets": spec["evidenceTargets"],
            "counterexamples": spec["counterexamples"],
            "selectedChecks": spec["selectedChecks"],
            "createdAt": now(),
        }
        task["reviewPlanId"] = plan["reviewPlanId"]
        task_errors = validate_schema_value(task, "agent-task.schema.json")
        plan_errors = validate_schema_value(plan, "review-plan.schema.json")
        if task_errors or plan_errors:
            raise ValueError("; ".join([*task_errors, *plan_errors]))
        save(task_path, task)
        save(plan_path, plan)
        jobs.append({
            "role": role,
            "contextId": actor["contextId"],
            "taskPath": str(task_path.resolve()),
            "taskSha256": sha256_file(task_path),
            "reviewPlanPath": str(plan_path.resolve()),
            "reviewPlanSha256": sha256_file(plan_path),
        })
    manifest_without_id = {
        "schemaVersion": 1,
        "workflowId": request["workflowId"],
        "caseId": request["caseId"],
        "targetRevision": request["targetRevision"],
        "caseClassification": request["caseClassification"],
        "artifactProfile": request["artifactProfile"],
        "frozenInputs": inputs,
        "jobs": jobs,
        "status": "READY",
    }
    manifest = {
        "manifestId": "CONSUMER-REVIEW-MANIFEST-" + canonical_hash(manifest_without_id)[:16],
        **manifest_without_id,
        "createdAt": now(),
    }
    errors = validate_schema_value(manifest, "consumer-review-job-manifest.schema.json")
    if errors:
        raise ValueError("invalid consumer review job manifest: " + "; ".join(errors))
    save(out_dir / "manifest.json", manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = build_jobs(load(args.request.resolve()), args.out_dir.resolve())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "status": manifest["status"],
        "manifestId": manifest["manifestId"],
        "jobs": [{"role": item["role"], "task": item["taskPath"], "reviewPlan": item["reviewPlanPath"]} for item in manifest["jobs"]],
        "manifest": str((args.out_dir.resolve() / "manifest.json")),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
