import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "tools" / "orchestrate.py"


class DeliveryPlanTests(unittest.TestCase):
    def test_prototype_profile_has_prototype_and_runtime_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "demo"; out = root / ".delivery" / "iterations" / "r1" / "work-plan.json"
            subprocess.run([sys.executable, str(ORCH), "init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--prototype-status", "TRIGGERED", "--ui-ownership", "LOCAL"], check=True, capture_output=True, text=True)
            result = subprocess.run([sys.executable, str(ORCH), "build-context-pack", "--help"], capture_output=True, text=True)
            # Smoke the plan builder directly; the orchestrator command is the next integration point.
            builder = ROOT / "tools" / "build_delivery_plan.py"
            proc = subprocess.run([sys.executable, str(builder), "--run-root", root, "--iteration", "r1", "--out", out], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            plan = json.loads(out.read_text())
            ids = {task["taskId"] for task in plan["tasks"]}
            self.assertIn("PROTOTYPE-CONTRACT", ids)
            self.assertIn("RUNTIME-VERIFY", ids)

    def test_external_ui_profile_has_boundary_not_prototype(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "demo"; out = root / "plan.json"
            subprocess.run([sys.executable, str(ORCH), "init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "EXTERNAL_UI_BOUNDARY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "EXTERNAL"], check=True, capture_output=True, text=True)
            builder = ROOT / "tools" / "build_delivery_plan.py"
            subprocess.run([sys.executable, str(builder), "--run-root", root, "--out", out], check=True, capture_output=True, text=True)
            plan = json.loads(out.read_text())
            ids = {task["taskId"] for task in plan["tasks"]}
            self.assertIn("UI-BOUNDARY", ids)
            self.assertNotIn("PROTOTYPE-PRODUCE", ids)
            self.assertNotIn("RUNTIME-VERIFY", ids)


if __name__ == "__main__":
    unittest.main()
