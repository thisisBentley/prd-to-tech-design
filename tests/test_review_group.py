import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "tools" / "orchestrate.py"


class ReviewGroupTests(unittest.TestCase):
    def run_cli(self, *args, expect=0):
        proc = subprocess.run([sys.executable, str(ORCH), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(proc.stdout)

    def test_group_init_and_pending_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "demo"
            self.run_cli("init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo")
            created = self.run_cli("review-group-init", "--run-root", root, "--group-id", "delivery-r1", "--stage", "DELIVERY_REVIEW", "--target-handoff-id", "HO-1", "--target-revision", "r1", "--reviewer", "delivery-reviewer", "--reviewer", "qa-red-team")
            self.assertEqual(created["status"], "READY")
            status = self.run_cli("review-group-status", "--run-root", root)
            self.assertEqual(status["groups"][0]["status"], "PENDING")
            state = json.loads((root / ".agents" / "orchestration.json").read_text())
            self.assertEqual(len(state["reviewGroups"]), 1)


if __name__ == "__main__":
    unittest.main()
