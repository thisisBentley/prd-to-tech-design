#!/usr/bin/env python3
"""Execute a configured artifact producer and verify its required outputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_once(producer: dict[str, Any], request: dict[str, Any], cwd: Path, timeout: float) -> dict[str, Any]:
    command = producer["command"]
    process = subprocess.run(
        command,
        cwd=str(Path(producer.get("cwd", cwd)).expanduser()),
        input=json.dumps(request, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return {"returnCode": process.returncode, "stdout": process.stdout, "stderr": process.stderr}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--kind", required=True, choices=["prd", "prototype", "overview", "jira", "semantic-evidence"])
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prd", type=Path)
    parser.add_argument("--requirement", type=Path)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    registry = load(args.registry.resolve())
    producer = next((item for item in registry.get("producers", []) if item.get("kind") == args.kind), None)
    if producer is None:
        result = {"schemaVersion": 1, "status": "NOT_CONFIGURED", "kind": args.kind, "errors": [f"no producer registered for {args.kind}"], "checkedAt": datetime.now(timezone.utc).isoformat()}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "NOT_CONFIGURED", "kind": args.kind, "out": str(args.out)}, ensure_ascii=False))
        return 0
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request = {
        "schemaVersion": 1,
        "kind": args.kind,
        "mode": producer["mode"],
        "workflowId": args.workflow_id,
        "revision": args.revision,
        "runRoot": str(args.run_root.resolve()),
        "outputDir": str(output_dir),
        "requiredArtifacts": producer["requiredArtifacts"],
        "inputs": {key: str(value.resolve()) for key, value in (("prd", args.prd), ("requirement", args.requirement), ("prototype", args.prototype)) if value},
        "generationObligationsPath": str((args.run_root.resolve() / ".agents" / "policy" / "generation-obligations.json")) if (args.run_root.resolve() / ".agents" / "policy" / "generation-obligations.json").exists() else None,
    }
    attempts: list[dict[str, Any]] = []
    timeout = float(producer.get("timeoutSeconds", 120))
    retries = int(producer.get("retries", 0))
    final_error = None
    for attempt in range(1, retries + 2):
        started = time.monotonic()
        try:
            invocation = run_once(producer, request, args.registry.resolve().parent, timeout)
            if invocation["returnCode"] == 0:
                attempts.append({"attempt": attempt, "status": "SUCCESS", "latencyMs": round((time.monotonic() - started) * 1000, 2)})
                final_error = None
                break
            final_error = f"producer exit {invocation['returnCode']}: {invocation['stderr'][-1000:]}"
        except subprocess.TimeoutExpired:
            final_error = f"producer timeout after {timeout}s"
        except Exception as exc:
            final_error = f"producer invocation failed: {exc}"
            attempts.append({"attempt": attempt, "status": "ERROR", "latencyMs": round((time.monotonic() - started) * 1000, 2), "error": final_error})
            break
        attempts.append({"attempt": attempt, "status": "RETRYABLE_ERROR" if attempt <= retries else "ERROR", "latencyMs": round((time.monotonic() - started) * 1000, 2), "error": final_error})
    errors: list[str] = []
    artifacts = []
    for name in producer["requiredArtifacts"]:
        path = output_dir / name
        if not path.is_file():
            errors.append(f"required artifact missing: {name}")
        else:
            artifacts.append({"name": name, "path": str(path), "sha256": digest(path)})
    if final_error:
        errors.append(final_error)
    result = {
        "schemaVersion": 1,
        "status": "PASS" if not errors else "BLOCKED",
        "kind": args.kind,
        "mode": producer["mode"],
        "workflowId": args.workflow_id,
        "revision": args.revision,
        "outputDir": str(output_dir),
        "requiredArtifacts": producer["requiredArtifacts"],
        "artifacts": artifacts,
        "attempts": attempts,
        "errors": errors,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "kind": args.kind, "mode": producer["mode"], "errors": len(errors), "out": str(args.out)}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
