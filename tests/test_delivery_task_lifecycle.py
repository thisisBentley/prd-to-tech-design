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


if __name__ == "__main__":
    unittest.main()
