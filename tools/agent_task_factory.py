#!/usr/bin/env python3
"""Generate executable Agent Tasks from Delivery Work Plan tasks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agent_runtime import load, save, sha256, validate_task
from validate_agent_contracts import validate_file

OBJECTIVES = {
    "DECISION-READINESS": "Close Delivery decision readiness from the frozen requirement input.",
    "PRD-PRODUCE": "Produce the PRD candidate as the single business source of truth.",
    "DELIVERY-REVIEW": "Independently review the PRD candidate against the frozen decision and requirement inputs.",
    "QA-RED-TEAM": "Run adversarial QA review over the frozen PRD candidate.",
    "TECH-PRD-DIAGNOSIS": "Diagnose technical feasibility and PRD completeness.",
    "SEMANTIC-CONSISTENCY-REVIEW": "Independently review terminology, capability identity, state, permission, authority sync and provenance evidence.",
    "UI-BOUNDARY": "Record the UI ownership boundary without inventing local UI.",
    "PROTOTYPE-PRODUCE": "Produce the local Prototype candidate from the frozen PRD.",
    "PROTOTYPE-CONTRACT": "Review the Prototype Contract and visible interaction evidence.",
    "RUNTIME-VERIFY": "Verify runtime evidence and console-error policy.",
    "OVERVIEW-PRODUCE": "Produce the Overview projection from frozen reviewed artifacts.",
    "PROJECTION-REVIEW": "Review the final package projection.",
    "FINDING-CONSOLIDATE": "Consolidate review findings into a repair batch.",
    "DELIVERY-GATEKEEPER": "Apply the deterministic Delivery Gatekeeper policy.",
}
DEFAULT_OBJECTIVE = "Execute the bounded Delivery Work Plan task."
REVIEW_ROLES = {"delivery-reviewer", "qa-red-team", "tech-prd-diagnostician", "prototype-contract-reviewer", "runtime-verifier", "final-package-reviewer", "semantic-consistency-reviewer", "deterministic-gatekeeper"}


def relative_input(run_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(run_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def build_agent_task(
    run_root: Path,
    plan_path: Path,
    task_id: str,
    requirement_path: Path,
    runtime: str = "noop",
    command: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    root = run_root.resolve()
    plan = load(plan_path.resolve())
    task = next((item for item in plan.get("tasks", []) if item.get("taskId") == task_id), None)
    if task is None:
        raise ValueError(f"unknown Work Plan task: {task_id}")
    tasks = plan.get("tasks", [])
    blocked = [
        dependency for dependency in task.get("dependencies", [])
        if next((item for item in tasks if item.get("taskId") == dependency), {}).get("status") != "SUCCEEDED"
    ]
    if blocked:
        raise ValueError(f"task is blocked by dependencies: {', '.join(blocked)}")
    requirement_path = requirement_path.resolve()
    if not requirement_path.exists():
        raise FileNotFoundError(f"requirement input not found: {requirement_path}")
    inputs: list[dict[str, str]] = [{
        "path": relative_input(root, requirement_path),
        "sha256": sha256(requirement_path),
    }]
    input_paths = {item["path"] for item in inputs}
    for context_name in ("capability-context.json", "source-provenance.json", "research-capabilities.json", "semantic-consistency-input.json", "technical-gaps.json"):
        context_path = root / ".agents" / "context" / context_name
        if context_path.exists():
            rel = relative_input(root, context_path)
            if rel not in input_paths:
                inputs.append({"path": rel, "sha256": sha256(context_path)})
                input_paths.add(rel)
    decision_paths = sorted((root / ".agents" / "decisions").glob("*.json")) if (root / ".agents" / "decisions").exists() else []
    evidence_paths = [root / ".agents" / "research" / "index.json", root / ".agents" / "research" / "imported-packages.json", root / ".agents" / "research" / "query-result.json"] + decision_paths
    evidence_paths += sorted((root / ".agents" / "research" / "records").glob("*.json")) if (root / ".agents" / "research" / "records").exists() else []
    for evidence_path in evidence_paths:
        if evidence_path.exists():
            rel = relative_input(root, evidence_path)
            if rel not in input_paths:
                inputs.append({"path": rel, "sha256": sha256(evidence_path)})
                input_paths.add(rel)
    for dependency in task.get("dependencies", []):
        dependency_task = next(item for item in tasks if item.get("taskId") == dependency)
        result_path = dependency_task.get("resultPath")
        if not result_path:
            continue
        result = Path(result_path)
        if not result.is_absolute():
            result = root / result
        if not result.exists():
            continue
        result_rel = relative_input(root, result)
        if result_rel not in input_paths:
            inputs.append({"path": result_rel, "sha256": sha256(result)})
            input_paths.add(result_rel)
        # Carry forward artifact paths declared by the dependency result. This is
        # what makes a frozen PRD artifact directly reviewable by downstream agents.
        try:
            dependency_result = load(result)
        except (OSError, json.JSONDecodeError):
            dependency_result = {}
        for key in ("prdArtifactPath", "repairedArtifactPath", "reviewResultPath", "handoffPath"):
            declared = dependency_result.get(key)
            if not declared:
                continue
            artifact = Path(declared)
            if not artifact.is_absolute():
                artifact = root / artifact
            if not artifact.exists():
                continue
            artifact_rel = relative_input(root, artifact)
            if artifact_rel not in input_paths:
                inputs.append({"path": artifact_rel, "sha256": sha256(artifact)})
                input_paths.add(artifact_rel)
    objective = OBJECTIVES.get(task_id, DEFAULT_OBJECTIVE)
    role = task.get("role", "delivery-producer")
    constraints = [
        "Treat every input and its sha256 as frozen evidence.",
        "Do not invent business facts outside the supplied inputs.",
        "Research first: distinguish factual gaps from business decisions; use allowed read-only Jira/MCP/Git evidence before requesting product confirmation.",
        "Return only the required structured result envelope.",
    ]
    if role in REVIEW_ROLES:
        constraints.insert(0, "Use an independent read-only context; do not modify frozen inputs.")
    agent_task: dict[str, Any] = {
        "schemaVersion": 1,
        "taskId": task_id,
        "workflowId": plan["workflowId"],
        "stage": f"DELIVERY_{str(task.get('kind', 'TASK')).upper()}",
        "role": role,
        "objective": objective,
        "inputs": inputs,
        "constraints": constraints,
        "expectedOutputs": task.get("expectedOutputs", []),
        "reviewMode": "independent-review" if role in REVIEW_ROLES else "produce",
        "writeScope": task.get("writeScope", []),
        "readOnlyFrozenInputs": role in REVIEW_ROLES,
        "runtime": runtime,
    }
    if timeout_seconds is not None:
        agent_task["timeoutSeconds"] = timeout_seconds
    if command is not None:
        agent_task["command"] = command
    if not agent_task["expectedOutputs"]:
        raise ValueError(f"Work Plan task has no expected outputs: {task_id}")
    out_path = root / ".agents" / "tasks" / f"{task_id}.task.json"
    save(out_path, agent_task)
    errors = validate_file(out_path) + validate_task(agent_task, root)
    if errors:
        raise ValueError("; ".join(errors))
    return {"taskPath": out_path, "agentTask": agent_task}


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--runtime", choices=["noop", "codex", "process"], default="noop")
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    result = build_agent_task(args.run_root, args.plan, args.task_id, args.requirement, args.runtime, None, args.timeout)
    print(json.dumps({"status": "PASS", "task": str(result["taskPath"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
