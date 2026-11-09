#!/usr/bin/env python3
"""Deterministic contract worker for Delivery DAG smoke and review runs."""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path


def task_input_paths(task: dict) -> list[str]:
    run_root = Path(os.environ.get("AI_NATIVE_RUN_ROOT", ".")).resolve()
    paths = []
    for item in task.get("inputs", []):
        path = Path(item["path"])
        paths.append(str((run_root / path).resolve() if not path.is_absolute() else path.resolve()))
    return paths


def write_review(task: dict, task_manifest_path: Path, result_path: Path) -> dict:
    workflow_id = task["workflowId"]
    revision = "r1"
    role = task["role"]
    paths = task_input_paths(task)
    requirement_path = next((p for p in paths if p.endswith("requirement.md")), paths[0])
    requirement = Path(requirement_path).read_text(encoding="utf-8")
    blocking = "BLOCKING" in requirement.upper()
    verdict = "RETURNED" if blocking else "ACCEPTED"
    findings = []
    if blocking:
        findings.append({
            "findingId": f"F-{task['taskId']}-001",
            "severity": "BLOCKING",
            "title": "Requirement contains an explicit blocking marker",
            "evidenceRefs": [requirement_path],
            "impact": "PRD cannot be accepted while the frozen requirement declares BLOCKING.",
            "closeCondition": "Remove the explicit BLOCKING marker and rerun affected review.",
            "owner": "prd-producer",
            "rootCauseId": "requirement-blocking-marker",
            "repairClass": "SEMANTIC",
            "expectedInvariant": "PRD_ONLY requirement input must not contain a BLOCKING marker.",
            "regressionTests": ["rerun deterministic reviewer"],
        })
    checks = [{
        "checkId": f"{role}-frozen-input",
        "status": "passed" if not blocking else "failed",
        "evidenceRefs": paths,
        "observed": "BLOCKING marker present" if blocking else "No BLOCKING marker present",
        "expected": "No BLOCKING marker present",
    }]
    review_id = "review-" + secrets.token_hex(4)
    review = {
        "schemaVersion": 1,
        "reviewRunId": review_id,
        "reviewPlanId": "plan-" + review_id,
        "workflowId": workflow_id,
        "producerRole": "prd-producer",
        "reviewerRole": role,
        "reviewType": "independent",
        "targetHandoffId": f"HO-{workflow_id}-R1",
        "targetRevision": revision,
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
    review_path = Path(os.environ["AI_NATIVE_RUN_ROOT"]) / ".agents" / "reviews" / f"{task['taskId']}.review.json"
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return review, review_path


def main() -> int:
    manifest = Path(os.environ["AI_NATIVE_TASK_MANIFEST"])
    task = json.loads(manifest.read_text(encoding="utf-8"))
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    outputs = [{"path": output, "kind": "contract-smoke"} for output in task["expectedOutputs"]]
    review_path = None
    if task.get("role") in {"delivery-reviewer", "qa-red-team", "tech-prd-diagnostician", "final-package-reviewer", "deterministic-gatekeeper"}:
        review, review_path = write_review(task, manifest, result_path)
        outputs.append({"path": str(review_path), "kind": "review-result"})
    payload = {
        "schemaVersion": 1,
        "status": "SUCCEEDED",
        "taskId": task["taskId"],
        "role": task["role"],
        "outputs": outputs,
    }
    if review_path is not None:
        payload["reviewResultPath"] = str(review_path.resolve())
        payload["verdict"] = review["verdict"]
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"])
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(f"contract worker completed {task['taskId']}\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
