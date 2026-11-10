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
    "prd-producer": (
        "Produce a compact PRD candidate in the final response. Use only facts supplied in input paths. "
        "The final response must be exactly one JSON object with schemaVersion=1, status=SUCCEEDED, taskId and role from prompt variables, "
        "outputs=[{path='PRD_DELIVERY.md',kind='PRD'}], prdArtifactPath=AI_NATIVE_ARTIFACT_PATH, "
        "prdMarkdown containing the complete Markdown PRD, and evidenceRefs=AI_NATIVE_INPUT_PATHS. Do not execute commands or write files."
    ),
    "prd-repair-agent": (
        "Repair the PRD according to the supplied finding evidence and updated requirement. Return exactly one JSON object with schemaVersion=1, "
        "status=SUCCEEDED, taskId and role, outputs=[{path='PRD_DELIVERY.md',kind='PRD'}], prdArtifactPath=AI_NATIVE_ARTIFACT_PATH, "
        "prdMarkdown containing the complete repaired Markdown PRD, repairedRootCauseId from the task evidence, and evidenceRefs=AI_NATIVE_INPUT_PATHS. Do not execute commands."
    ),
    "delivery-reviewer": (
        "Independently review the frozen PRD artifact and requirement. Return exactly one JSON object with schemaVersion=1, status=SUCCEEDED, "
        "taskId and role, outputs=[{path='review-result',kind='review-result'}], reviewResultPath=AI_NATIVE_REVIEW_PATH, verdict='ACCEPTED' only "
        "if every supplied fact is covered and no explicit BLOCKING source condition remains, otherwise verdict='RETURNED', completionStatus='complete', "
        "blockingCount matching findings, and evidenceRefs=AI_NATIVE_INPUT_PATHS. Do not execute commands."
    ),
    "qa-red-team": (
        "Adversarially review the frozen PRD artifact using the same structured review contract as the delivery reviewer, with reviewerRole='qa-red-team'."
    ),
    "tech-prd-diagnostician": (
        "Diagnose technical completeness and feasibility of the frozen PRD artifact using the same structured review contract, with reviewerRole='tech-prd-diagnostician'."
    ),
    "final-package-reviewer": (
        "Review the final package evidence and return the same structured review contract with verdict='ACCEPTED' only when all prior evidence is coherent and blockingCount=0."
    ),
    "deterministic-gatekeeper": (
        "Apply the supplied deterministic gate policy and return the same structured review contract with verdict='ACCEPTED' only when every required check is evidenced and blockingCount=0."
    ),
    "default": (
        "Execute the bounded task analytically without commands or file writes. "
        "The final response must be exactly one JSON object with schemaVersion=1, status=SUCCEEDED, taskId and role from prompt variables, "
        "outputs covering every expected output, and evidenceRefs=AI_NATIVE_INPUT_PATHS."
    ),
}

def build_prompt(task: dict, input_paths: list[str], result_path: Path, review_path: Path, artifact_path: Path) -> str:
    role = task.get("role", "")
    base = ROLE_PROMPTS.get(role, ROLE_PROMPTS["default"])
    return "\n".join([
        "You are executing one bounded AI-Native Agile Product-Engineering task.",
        base,
        "Read the supplied input paths directly. Return only compact JSON without Markdown fences or commentary.",
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
        args.codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
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
    if task.get("role") in {"prd-producer", "prd-repair-agent"}:
        markdown = result.get("prdMarkdown")
        if isinstance(markdown, str) and markdown.strip():
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(markdown.rstrip() + "\n", encoding="utf-8")
            result["producerMode"] = "semantic"
        elif not artifact_path.exists():
            print("producer result lacks prdMarkdown and no PRD artifact was materialized", file=sys.stderr)
            return 4
        result["prdArtifactPath"] = str(artifact_path)
        result["prdArtifactSha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if not any(item.get("path") == "PRD_DELIVERY.md" for item in result["outputs"] if isinstance(item, dict)):
            result["outputs"].insert(0, {"path": "PRD_DELIVERY.md", "kind": "PRD"})
        result_path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
