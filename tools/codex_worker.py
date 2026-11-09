#!/usr/bin/env python3
"""Codex semantic worker adapter for the PRD_ONLY Delivery loop."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROLE_PROMPTS = {
    "decision-readiness-agent": (
        "Read the frozen requirement. Return a JSON object with schemaVersion=1, status=SUCCEEDED, taskId and role from environment, "
        "outputs=[{path:'.agents/results/{taskId}.artifacts/decision-context.json',kind:'decision-context'}], decisionReadiness='READY', "
        "closedDecisions=[] and evidenceRefs=[every AI_NATIVE_INPUT_PATHS entry]."
    ),
    "prd-producer": (
        "Read the frozen requirement and dependency evidence. Return a JSON object with schemaVersion=1, status=SUCCEEDED, taskId and role from environment, "
        "outputs=[{path:'.agents/results/{taskId}.artifacts/PRD_DELIVERY.md',kind:'PRD'}], prdArtifactPath set to that absolute path, "
        "and evidenceRefs=[every AI_NATIVE_INPUT_PATHS entry]. Do not invent facts outside the supplied requirement."
    ),
    "delivery-reviewer": (
        "Independently review the supplied PRD artifact. Return schemaVersion=1, status=SUCCEEDED, taskId and role from environment, outputs=[{path:'review-result',kind:'review-result'}], "
        "reviewResultPath set to AI_NATIVE_REVIEW_PATH, verdict ACCEPTED only with evidence, else RETURNED, completionStatus='complete', blockingCount matching findings, "
        "and evidenceRefs=[every AI_NATIVE_INPUT_PATHS entry]."
    ),
    "qa-red-team": (
        "Adversarially review the supplied PRD artifact. Return the same structured JSON contract as the delivery reviewer, with reviewerRole='qa-red-team'."
    ),
    "tech-prd-diagnostician": (
        "Diagnose technical completeness and feasibility of the supplied PRD artifact. Return the same structured JSON contract as the delivery reviewer, with reviewerRole='tech-prd-diagnostician'."
    ),
    "prd-repair-agent": (
        "Repair the PRD artifact according to the frozen finding evidence and root cause. Return schemaVersion=1, status=SUCCEEDED, taskId and role from environment, "
        "outputs=[{path:'PRD_DELIVERY.md',kind:'PRD'}], repairedArtifactPath set to AI_NATIVE_ARTIFACT_PATH, repairedRootCauseId='requirement-blocking-marker', "
        "and evidenceRefs=[every AI_NATIVE_INPUT_PATHS entry]."
    ),
    "default": (
        "Execute the bounded task. Return schemaVersion=1, status=SUCCEEDED, taskId and role from environment, outputs covering every expected output, "
        "and evidenceRefs=[every AI_NATIVE_INPUT_PATHS entry]."
    ),
}


def build_prompt(task: dict, input_paths: list[str], result_path: Path, review_path: Path, artifact_path: Path) -> str:
    role = task.get("role", "")
    base = ROLE_PROMPTS.get(role, ROLE_PROMPTS["default"])
    return "\n".join([
        "You are executing one bounded AI-Native Agile Product-Engineering task.",
        base,
        "Return only compact JSON. Do not include Markdown fences or commentary.",
        f"AI_NATIVE_TASK_ID={task['taskId']}",
        f"AI_NATIVE_ROLE={role}",
        "AI_NATIVE_INPUT_PATHS=" + ",".join(input_paths),
        f"AI_NATIVE_RESULT_PATH={result_path}",
        f"AI_NATIVE_REVIEW_PATH={review_path}",
        f"AI_NATIVE_ARTIFACT_PATH={artifact_path}",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write"], default="read-only")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=float(os.environ.get("AI_NATIVE_TIMEOUT", "120")))
    args = parser.parse_args()
    manifest = Path(os.environ["AI_NATIVE_TASK_MANIFEST"])
    task = json.loads(manifest.read_text(encoding="utf-8"))
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"]).resolve()
    review_path = Path(os.environ.get("AI_NATIVE_REVIEW_PATH", result_path.parent / f"{task['taskId']}.review.json")).resolve()
    artifact_path = Path(os.environ.get("AI_NATIVE_ARTIFACT_PATH", result_path.parent / f"{task['taskId']}.artifacts" / "PRD_DELIVERY.md")).resolve()
    input_paths = [str(Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve() / item["path"] if not Path(item["path"]).is_absolute() else Path(item["path"]).resolve()) for item in task.get("inputs", [])]
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.parent.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(task, input_paths, result_path, review_path, artifact_path)
    argv = [
        args.codex, "exec", "--ephemeral", "--skip-git-repo-check",
        "--sandbox", args.sandbox,
        "--output-last-message", str(result_path),
        "-C", os.environ["AI_NATIVE_RUN_ROOT"],
    ]
    if args.model:
        argv += ["--model", args.model]
    argv.append(prompt)
    completed = subprocess.run(argv, text=True, capture_output=True, timeout=args.timeout, check=False)
    transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"])
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        print(f"codex exited with code {completed.returncode}", file=sys.stderr)
        return completed.returncode
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid codex result: {exc}", file=sys.stderr)
        return 2
    required = {"schemaVersion": 1}
    if result.get("schemaVersion") != required["schemaVersion"] or result.get("status") != "SUCCEEDED" or not isinstance(result.get("outputs"), list) or not result["outputs"]:
        print("codex result violates structured envelope", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
