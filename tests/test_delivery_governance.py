import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
GATE = ROOT / SCRIPTS / "final_delivery_gate.py"
PLANNER = ROOT / SCRIPTS / "plan_artifact_repairs.py"
VALIDATOR = ROOT / SCRIPTS / "gate_contract_validator.py"


class DeliveryGovernanceTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def fixtures(self, root, synced=True):
        pair = root / "artifact-pair.json"
        consistency = root / "consistency.json"
        review = root / "final-review.json"
        pair.write_text(json.dumps({"schemaVersion": 1, "pairId": "P-1", "workflowId": "WF-1", "artifactProfile": "PRD_PLUS_PROTOTYPE", "prdRevision": "r3", "prototypeRevision": "r3", "pairStatus": "SYNCED" if synced else "RESYNC_REQUIRED", "prdPath": "prd", "prdHash": "a" * 64, "prototypePath": "proto", "prototypeHash": "b" * 64, "createdAt": "2026-11-09T00:00:00Z", "updatedAt": "2026-11-09T00:00:00Z"}), encoding="utf-8")
        consistency.write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "pairId": "P-1", "status": "PASS" if synced else "NEEDS_FIX", "blockingCount": 0 if synced else 1, "checks": [], "findings": [] if synced else [{"type": "STALE_ARTIFACT_PAIR", "owner": "delivery-main-agent", "closeCondition": "resync", "regressionTests": ["gate"]}], "checkedAt": "2026-11-09T00:00:00Z"}), encoding="utf-8")
        review.write_text(json.dumps({"schemaVersion": 1, "reviewRunId": "R-1", "workflowId": "WF-1", "verdict": "ACCEPTED" if synced else "RETURNED", "blockingCount": 0 if synced else 1, "findings": []}), encoding="utf-8")
        return pair, consistency, review

    def test_final_gate_accepts_synced_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, consistency, review = self.fixtures(root)
            out = root / "gate.json"
            result = self.run_cli(GATE, "--pair", pair, "--consistency", consistency, "--final-review", review, "--out", out)
            self.assertEqual(result["status"], "PASS")
            self.run_cli(VALIDATOR, out, "--json")

    def test_final_gate_blocks_unsynced_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, consistency, review = self.fixtures(root, synced=False)
            out = root / "gate.json"
            result = self.run_cli(GATE, "--pair", pair, "--consistency", consistency, "--final-review", review, "--out", out, expect=1)
            self.assertEqual(result["status"], "NEEDS_FIX")
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertGreaterEqual(data["blockingCount"], 1)

    def test_planner_creates_owner_specific_repair_tasks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            pair, consistency, _ = self.fixtures(root, synced=False)
            result = self.run_cli(PLANNER, "--consistency", consistency, "--pair", pair, "--out", root / "repair-group.json")
            self.assertEqual(result["status"], "READY")
            data = json.loads((root / "repair-group.json").read_text(encoding="utf-8"))
            self.assertEqual(data["tasks"][0]["owner"], "delivery-main-agent")
            self.assertEqual(data["tasks"][0]["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()
