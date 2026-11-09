import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "tools" / "orchestrate.py"


class DeliveryTaskLifecycleTests(unittest.TestCase):
    def run_cli(self, *args, expect=0):
        proc = subprocess.run([sys.executable, str(ORCH), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_dependencies_and_lifecycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; plan = root / "plan.json"
            self.run_cli("init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
            self.run_cli("build-delivery-plan", "--run-root", root, "--out", plan)
            blocked = self.run_cli("delivery-task-start", "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE")
            self.assertEqual(blocked["status"], "BLOCKED")
            self.run_cli("delivery-task-start", "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS")
            self.run_cli("delivery-task-complete", "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS", "--result", root / "decision.json")
            self.run_cli("delivery-task-start", "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE")
            self.run_cli("delivery-task-fail", "--run-root", root, "--plan", plan, "--task-id", "PRD-PRODUCE", "--error", "fixture failure")
            data = json.loads(plan.read_text())
            task = next(t for t in data["tasks"] if t["taskId"] == "PRD-PRODUCE")
            self.assertEqual(task["status"], "FAILED")
            self.assertEqual(task["error"], "fixture failure")

    def test_runtime_spawn_and_collect_sync_plan_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; plan = root / "plan.json"
            self.run_cli("init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
            self.run_cli("build-delivery-plan", "--run-root", root, "--out", plan)
            self.run_cli("delivery-task-start", "--run-root", root, "--plan", plan, "--task-id", "DECISION-READINESS")
            task = root / "DECISION-READINESS.task.json"
            task.write_text(json.dumps({
                "schemaVersion": 1, "taskId": "DECISION-READINESS", "workflowId": "WF-1", "stage": "delivery",
                "role": "decision-readiness-agent", "objective": "close readiness", "inputs": [{"path": "input.md", "sha256": hashlib.sha256(b"frozen task input\n").hexdigest()}],
                "constraints": ["use supplied decisions"], "expectedOutputs": ["result.json"],
                "reviewMode": "produce", "writeScope": ["result.json"], "readOnlyFrozenInputs": False,
                "runtime": "noop",
            }), encoding="utf-8")
            (root / "input.md").write_text("frozen task input\n", encoding="utf-8")
            spawned = self.run_cli("agent-spawn", "--run-root", root, "--task", task, "--delivery-plan", plan)
            self.assertEqual(spawned["status"], "SPAWNED")
            data = json.loads(plan.read_text())
            started = next(item for item in data["tasks"] if item["taskId"] == "DECISION-READINESS")
            self.assertEqual(started["status"], "RUNNING")
            self.assertEqual(started["runtimeRecordPath"], spawned["record"])
            result = root / "decision.json"; result.write_text(json.dumps({"schemaVersion": 1, "status": "READY", "outputs": [{"path": "decision.json"}]}), encoding="utf-8")
            collected = self.run_cli("agent-collect", "--run-root", root, "--task-id", "DECISION-READINESS", "--result", result, "--delivery-plan", plan)
            self.assertEqual(collected["status"], "SUCCEEDED")
            data = json.loads(plan.read_text())
            completed = next(item for item in data["tasks"] if item["taskId"] == "DECISION-READINESS")
            self.assertEqual(completed["status"], "SUCCEEDED")
            self.assertEqual(completed["resultPath"], str(result.resolve()))
            self.assertEqual(completed["runtimeRecordPath"], spawned["record"])

    def test_runtime_cancel_syncs_failed_plan_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; plan = root / "plan.json"; task = root / "CANCEL.task.json"
            self.run_cli("init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
            plan.write_text(json.dumps({
                "schemaVersion": 1, "planId": "PLAN-1", "workflowId": "WF-1", "requirementId": "DEMO", "artifactProfile": "PRD_ONLY", "iteration": "r1",
                "tasks": [{"taskId": "CANCEL", "role": "prd-producer", "kind": "producer", "dependencies": [], "readScope": [], "writeScope": [], "expectedOutputs": ["out"], "status": "PENDING"}],
                "createdAt": "2026-01-01T00:00:00Z",
            }), encoding="utf-8")
            task.write_text(json.dumps({
                "schemaVersion": 1, "taskId": "CANCEL", "workflowId": "WF-1", "stage": "delivery", "role": "prd-producer",
                "objective": "cancel audit", "inputs": [{"path": "input.md", "sha256": hashlib.sha256(b"frozen task input\n").hexdigest()}], "constraints": ["stop safely"], "expectedOutputs": ["out"],
                "reviewMode": "produce", "writeScope": ["out"], "readOnlyFrozenInputs": False, "runtime": "noop",
            }), encoding="utf-8")
            (root / "input.md").write_text("frozen task input\n", encoding="utf-8")
            self.run_cli("agent-spawn", "--run-root", root, "--task", task, "--delivery-plan", plan)
            cancelled = self.run_cli("agent-collect", "--run-root", root, "--task-id", "CANCEL", "--cancel", "--delivery-plan", plan)
            self.assertEqual(cancelled["status"], "CANCELLED")
            data = json.loads(plan.read_text())
            item = next(x for x in data["tasks"] if x["taskId"] == "CANCEL")
            self.assertEqual(item["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
