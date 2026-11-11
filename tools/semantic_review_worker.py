#!/usr/bin/env python3
"""Codex adapter for one isolated semantic review job.

The job JSON is read from stdin. The adapter invokes a separate Codex process in
read-only mode and emits one review-result JSON object on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_prompt(job: dict[str, Any]) -> str:
    return "\n".join([
        "You are an independent semantic reviewer. You did not produce the artifact.",
        "Read only the frozen job context below. Do not infer business facts.",
        "Find semantic contradictions, hidden assumptions, missing cross-unit links, and false closure.",
        "Return exactly one JSON object matching review-result.schema.json; no Markdown fences or commentary.",
        f"JOB_ID={job.get('jobId')}",
        f"WORKFLOW_ID={job.get('workflowId')}",
        f"TARGET_REVISION={job.get('targetRevision')}",
        "JOB_JSON_BEGIN",
        json.dumps(job, ensure_ascii=False, separators=(",", ":")),
        "JOB_JSON_END",
        "Required review-result fields: schemaVersion, reviewRunId, reviewPlanId, workflowId, producerRole, reviewerRole, reviewType, targetHandoffId, targetRevision, independentContext, verdict, checks, findings, blockingCount, evidenceRefs, checkedAt, completionStatus, reviewerContextId, reviewerTranscript.",
        "Use reviewerRole=semantic-consistency-reviewer. Set independentContext=true. Use jobId as reviewPlanId and targetHandoffId. Use a deterministic reviewRunId from jobId. Every finding must have evidenceRefs, impact, closeCondition, owner.",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    job = json.load(sys.stdin)
    prompt = build_prompt(job)
    job_dir = Path(os.environ.get("AI_NATIVE_SEMANTIC_JOB_DIR", "/tmp")).resolve()
    result_path = job_dir / f"{job['jobId']}.raw.json"
    transcript_path = job_dir / f"{job['jobId']}.log"
    job_dir.mkdir(parents=True, exist_ok=True)
    argv = [
        args.codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules",
        "--sandbox", "read-only", "--output-last-message", str(result_path), "-C", str(job_dir),
    ]
    if args.model:
        argv += ["--model", args.model]
    argv.append(prompt)
    process = subprocess.run(argv, text=True, capture_output=True, timeout=args.timeout, check=False)
    transcript_path.write_text(process.stdout + process.stderr, encoding="utf-8")
    if process.returncode != 0:
        print(json.dumps({"status": "ERROR", "error": f"codex exit {process.returncode}", "transcript": str(transcript_path)}, ensure_ascii=False))
        return process.returncode
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"invalid codex JSON: {exc}", "transcript": str(transcript_path)}, ensure_ascii=False))
        return 2
    # The worker is allowed to materialize a transcript; the runner writes the result.
    result["reviewerTranscript"] = str(transcript_path)
    result.setdefault("reviewRunId", f"REV-{job['jobId']}")
    result.setdefault("reviewPlanId", job["jobId"])
    result.setdefault("targetHandoffId", job["jobId"])
    result.setdefault("targetRevision", job.get("targetRevision", "r1"))
    result.setdefault("workflowId", job.get("workflowId", "UNKNOWN"))
    result.setdefault("reviewerRole", "semantic-consistency-reviewer")
    result.setdefault("producerRole", "prd-producer")
    result.setdefault("reviewType", "independent")
    result.setdefault("independentContext", True)
    result.setdefault("checkedAt", datetime.now(timezone.utc).isoformat())
    result.setdefault("completionStatus", "complete")
    result.setdefault("reviewerContextId", f"ctx-{job['jobId']}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
