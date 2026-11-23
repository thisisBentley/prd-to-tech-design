#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--job", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
job = json.loads(args.job.read_text(encoding="utf-8"))
scenario = job["scenario"]
status = "MISSED" if os.environ.get("FAKE_CHALLENGER_MISSED") == "1" else "DETECTED"
if os.environ.get("FAKE_CHALLENGER_INCOMPLETE") == "1":
    status = "INCOMPLETE"
if os.environ.get("FAKE_CHALLENGER_ERROR") == "1":
    status = "ERROR"
if os.environ.get("FAKE_CHALLENGER_MUTATE") == "1":
    root = Path(job.get("artifactRoot") or ".")
    root.mkdir(parents=True, exist_ok=True)
    (root / "worker-mutated.txt").write_text("changed\n", encoding="utf-8")
result = {
    "schemaVersion": 1,
    "jobId": job["jobId"],
    "scenarioId": scenario["scenarioId"],
    "status": status,
    "observedFailureSignal": {
        "kind": scenario.get("expectedFailureSignal", {}).get("kind", "UNKNOWN"),
        "description": "fixture challenger evaluated the frozen scenario",
    },
    "evidenceRefs": [str(args.job.resolve())],
    "checkedAt": "2026-11-23T00:00:00+00:00",
    "transcript": "fixture challenger transcript",
}
if status == "ERROR":
    result["error"] = "fixture challenger error"
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "PASS", "scenarioId": scenario["scenarioId"]}))
