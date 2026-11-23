#!/usr/bin/env python3
"""Run frozen Rehearsal Corpus scenarios through an isolated challenger worker."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash
from trust_kernel import validate_schema_value


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path | None, default: Any = None) -> Any:
    if path is None or not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root: Path | None) -> str | None:
    if root is None or not root.is_dir():
        return None
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append({"path": path.relative_to(root).as_posix(), "sha256": digest(path)})
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--worker", nargs=argparse.REMAINDER, required=True)
    parser.add_argument("--artifact-root", type=Path)
    parser.add_argument("--job-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.worker:
        parser.error("--worker requires an executable command")

    corpus_path = args.corpus.resolve()
    corpus = load(corpus_path, {}) or {}
    errors: list[str] = []
    errors.extend(validate_schema_value(corpus, "rehearsal-corpus.schema.json"))
    authority = corpus.get("authority") or {}
    if authority.get("resultAuthority") != "NONE" or authority.get("releaseEligible") is not False or authority.get("trainingEligible") is not False:
        errors.append("Rehearsal Corpus authority is invalid")
    if corpus.get("status") == "BLOCKED":
        errors.append("Rehearsal Corpus is BLOCKED")
    scenarios = corpus.get("scenarios") or []
    if not scenarios:
        errors.append("Rehearsal Corpus has no scenarios")

    corpus_hash_before = digest(corpus_path) if corpus_path.is_file() else "0" * 64
    artifact_root = args.artifact_root.resolve() if args.artifact_root else None
    artifact_before = snapshot(artifact_root)
    job_dir = (args.job_dir or (args.run_root.resolve() / ".agents" / "challenges" / "jobs")).resolve()
    result_dir = (args.run_root.resolve() / ".agents" / "challenges" / "results").resolve()
    job_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    started_at = now()
    started_mono = time.monotonic()
    scenario_results: list[dict[str, Any]] = []
    challenge_run_id = "CHAL-" + canonical_hash({
        "workflowId": corpus.get("workflowId"),
        "revision": corpus.get("revision"),
        "corpusId": corpus.get("corpusId"),
        "corpusSha256": corpus_hash_before,
    })[:16]

    if not errors:
        for scenario in scenarios:
            scenario_id = str(scenario.get("scenarioId"))
            job_id = "CHALLENGE-" + scenario_id
            job_path = job_dir / f"{scenario_id}.job.json"
            result_path = result_dir / f"{scenario_id}.result.json"
            job = {
                "schemaVersion": 1,
                "challengeRunId": challenge_run_id,
                "jobId": job_id,
                "workflowId": corpus.get("workflowId"),
                "revision": corpus.get("revision"),
                "corpusId": corpus.get("corpusId"),
                "corpusSha256": corpus_hash_before,
                "artifactRoot": str(artifact_root) if artifact_root else None,
                "scenario": scenario,
                "authority": corpus.get("authority"),
            }
            save(job_path, job)
            scenario_started = time.monotonic()
            process = subprocess.run(
                [*args.worker, "--job", str(job_path), "--out", str(result_path)],
                cwd=str(args.run_root.resolve()), text=True, capture_output=True, timeout=args.timeout, check=False,
            )
            elapsed = round((time.monotonic() - scenario_started) * 1000, 2)
            result = load(result_path, {}) if result_path.is_file() else {}
            result_errors = validate_schema_value(result, "challenger-result.schema.json") if result else ["worker produced no result"]
            if result:
                if result.get("jobId") != job_id:
                    result_errors.append("result jobId does not match job")
                if result.get("scenarioId") != scenario_id:
                    result_errors.append("result scenarioId does not match job")
                if result.get("status") not in {"DETECTED", "MISSED", "INCOMPLETE", "ERROR"}:
                    result_errors.append("result status is invalid")
            status = str(result.get("status") or ("ERROR" if process.returncode != 0 or result_errors else "INCOMPLETE"))
            if result_errors:
                status = "ERROR"
            scenario_results.append({
                "scenarioId": scenario_id,
                "scenarioType": str(scenario.get("scenarioType") or "UNKNOWN"),
                "status": status,
                "jobPath": str(job_path),
                "resultPath": str(result_path),
                "workerExitCode": process.returncode,
                "observedFailureSignal": result.get("observedFailureSignal") or {"kind": "UNAVAILABLE", "description": "worker produced no valid failure signal"},
                **({"error": "; ".join(result_errors)} if result_errors else {}),
                "elapsedMs": elapsed,
            })
            if process.returncode != 0 and not result_errors:
                scenario_results[-1]["error"] = (process.stderr or process.stdout or "worker exited non-zero")[-1000:]
                scenario_results[-1]["status"] = "ERROR"

    corpus_hash_after = digest(corpus_path) if corpus_path.is_file() else "0" * 64
    if corpus_hash_after != corpus_hash_before:
        errors.append("Rehearsal Corpus changed during challenge execution")
    artifact_after = snapshot(artifact_root)
    if artifact_before != artifact_after:
        errors.append("candidate artifact snapshot changed during challenge execution")
    detected = sum(1 for item in scenario_results if item["status"] == "DETECTED")
    missed = sum(1 for item in scenario_results if item["status"] == "MISSED")
    incomplete = sum(1 for item in scenario_results if item["status"] == "INCOMPLETE")
    scenario_errors = sum(1 for item in scenario_results if item["status"] == "ERROR")
    if errors or scenario_errors:
        outcome = "BLOCKED"
    elif missed:
        outcome = "GAPS_FOUND"
    elif incomplete:
        outcome = "INCOMPLETE"
    elif detected == len(scenarios) and scenarios:
        outcome = "ALL_DETECTED"
    else:
        outcome = "INCOMPLETE"
    status = "BLOCKED" if errors or scenario_errors else "COMPLETE"
    finished_at = now()
    payload_without_id = {
        "schemaVersion": 1,
        "workflowId": str(corpus.get("workflowId") or "UNKNOWN"),
        "revision": str(corpus.get("revision") or "r1"),
        "corpusId": str(corpus.get("corpusId") or "UNKNOWN"),
        "corpusSha256": corpus_hash_before,
        "status": status,
        "outcome": outcome,
        "authority": {"readOnly": True, "mayModifyArtifacts": False, "resultAuthority": "NONE", "releaseEligible": False, "trainingEligible": False},
        "artifactSnapshotSha256Before": artifact_before,
        "artifactSnapshotSha256After": artifact_after,
        "scenarioResults": scenario_results,
        "metrics": {
            "scenarios": len(scenarios),
            "detected": detected,
            "missed": missed,
            "incomplete": incomplete,
            "errors": scenario_errors,
            "elapsedMs": round((time.monotonic() - started_mono) * 1000, 2),
        },
        "errors": errors,
        "startedAt": started_at,
        "finishedAt": finished_at,
        "createdAt": finished_at,
    }
    payload = {"challengeRunId": challenge_run_id, **payload_without_id}
    issues = validate_schema_value(payload, "challenger-run.schema.json")
    if issues:
        payload["status"] = "BLOCKED"
        payload["outcome"] = "BLOCKED"
        payload["errors"] = list(payload["errors"]) + issues
    save(args.out.resolve(), payload)
    print(json.dumps({
        "status": payload["status"],
        "outcome": payload["outcome"],
        "runId": payload["challengeRunId"],
        "detected": payload["metrics"]["detected"],
        "missed": payload["metrics"]["missed"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
