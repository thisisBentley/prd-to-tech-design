#!/usr/bin/env python3
"""Execute the deterministic Delivery Quality Exit as a Work Plan task."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    manifest_path = Path(os.environ["AI_NATIVE_TASK_MANIFEST"]).resolve()
    task = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = Path(os.environ["AI_NATIVE_RUN_ROOT"]).resolve()
    plan = Path(os.environ.get("AI_NATIVE_DELIVERY_PLAN", root / ".agents" / "delivery-plan.json")).resolve()
    output = root / ".agents" / "quality" / "delivery-quality-exit.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    tool = Path(__file__).resolve().parent / "delivery_quality_exit.py"
    process = subprocess.run(
        [sys.executable, str(tool), "--run-root", str(root), "--plan", str(plan), "--out", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    transcript = Path(os.environ.get("AI_NATIVE_TRANSCRIPT_PATH", root / ".agents" / "runtime" / "transcripts" / "quality.log"))
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(process.stdout + process.stderr, encoding="utf-8")
    if not output.exists():
        print(process.stdout + process.stderr, file=sys.stderr)
        return process.returncode or 2
    quality = json.loads(output.read_text(encoding="utf-8"))
    status = quality.get("status")
    verdict = "ACCEPTED" if status == "PASS" else "BLOCKED"
    result = {
        "schemaVersion": 1,
        "status": "SUCCEEDED" if status == "PASS" else "FAILED",
        "taskId": task["taskId"],
        "role": task["role"],
        "verdict": verdict,
        "qualityResultPath": str(output),
        "blockingCount": int(quality.get("blockingCount", 0)),
        "outputs": [{"path": str(output), "kind": "delivery-quality-exit"}],
        "evidenceRefs": [str(plan), str(output)],
    }
    result_path = Path(os.environ["AI_NATIVE_RESULT_PATH"])
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "blockingCount": result["blockingCount"]}, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
