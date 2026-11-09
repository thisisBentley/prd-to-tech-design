#!/usr/bin/env python3
"""Deterministic contract worker for Delivery DAG smoke runs."""
from __future__ import annotations

import json
import os
from pathlib import Path


def main() -> int:
    manifest = Path(os.environ["AI_NATIVE_TASK_MANIFEST"])
    task = json.loads(manifest.read_text(encoding="utf-8"))
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schemaVersion": 1,
        "status": "SUCCEEDED",
        "taskId": task["taskId"],
        "role": task["role"],
        "outputs": [{"path": output, "kind": "contract-smoke"} for output in task["expectedOutputs"]],
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    transcript = Path(os.environ["AI_NATIVE_TRANSCRIPT_PATH"])
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(f"contract worker completed {task['taskId']}\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
