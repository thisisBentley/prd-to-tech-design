import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
SYNC = ROOT / SCRIPTS / "artifact_sync_loop.py"


class ArtifactSyncLoopTests(unittest.TestCase):
    def run_cli(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(SYNC), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def fixtures(self, root):
        prd = root / "PRD_DELIVERY.md"
        prototype = root / "Prototype.html"
        previous = root / "manifest-r2.json"
        current = root / "manifest-r3.json"
        overview = root / "Overview.html"
        final_review = root / "final-review.json"
        prd.write_text("# PRD\n\n- FR-001: Submit expense\n- AC-001: Expense submits\n- UI-submit\n- FR-008: Approval comment\n- AC-014: Approval comment persists\n- UI-approval-comment\n", encoding="utf-8")
        prototype.write_text('<button data-ai-id="UI-submit" data-ai-fr="FR-001" data-ai-ac="AC-001">Submit</button>', encoding="utf-8")
        overview.write_text("<html>overview r3</html>", encoding="utf-8")
        proto_hash = hashlib.sha256(prototype.read_bytes()).hexdigest()
        previous.write_text(json.dumps({
            "schemaVersion": 1, "manifestId": "M-2", "workflowId": "WF-1", "prototypeRevision": "r2", "prototypePath": str(prototype), "prototypeHash": proto_hash,
            "elements": [
                {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
                {"uiElementId": "UI-approval-comment", "frIds": ["FR-008"], "acIds": ["AC-014"], "visibleLabel": "Approval comment", "states": ["default"]},
            ], "createdAt": "2026-11-09T00:00:00Z",
        }), encoding="utf-8")
        current.write_text(json.dumps({
            "schemaVersion": 1, "manifestId": "M-3", "workflowId": "WF-1", "prototypeRevision": "r3", "prototypePath": str(prototype), "prototypeHash": proto_hash,
            "elements": [
                {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
            ], "createdAt": "2026-11-09T00:00:00Z",
        }), encoding="utf-8")
        final_review.write_text(json.dumps({"schemaVersion": 1, "reviewRunId": "R-FINAL", "workflowId": "WF-1", "verdict": "ACCEPTED", "blockingCount": 0, "findings": []}), encoding="utf-8")
        return prd, prototype, previous, current, overview, final_review

    def test_semantic_delete_with_apply_reconciliation_reaches_final_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, prototype, previous, current, overview, final_review = self.fixtures(root)
            result = self.run_cli("--workflow-id", "WF-1", "--prd", prd, "--prototype", prototype, "--manifest", current, "--previous-manifest", previous, "--overview", overview, "--from-revision", "r2", "--to-revision", "r3", "--apply-reconcile", "--final-review", final_review, "--out-dir", root / "out")
            self.assertEqual(result["status"], "FINAL_PASS")
            updated = prd.read_text(encoding="utf-8")
            self.assertNotIn("FR-008", updated)
            self.assertNotIn("AC-014", updated)
            gate = json.loads(Path(result["finalGate"]).read_text(encoding="utf-8"))
            self.assertEqual(gate["result"], "PASS")
            self.assertEqual(gate["blockingCount"], 0)

    def test_auto_repair_executes_owner_group_and_reaches_final_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, prototype, previous, current, overview, final_review = self.fixtures(root)
            result = self.run_cli("--workflow-id", "WF-1", "--prd", prd, "--prototype", prototype, "--manifest", current, "--previous-manifest", previous, "--overview", overview, "--from-revision", "r2", "--to-revision", "r3", "--auto-repair", "--final-review", final_review, "--out-dir", root / "out")
            self.assertEqual(result["status"], "FINAL_PASS")
            self.assertNotIn("FR-008", prd.read_text(encoding="utf-8"))
            execution = json.loads((root / "out" / "artifact-repair-execution.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["executionStatus"], "SUCCEEDED")
            self.assertEqual(execution["status"], "CLOSED")
            self.assertTrue(execution["execution"])
            gate = json.loads(Path(result["finalGate"]).read_text(encoding="utf-8"))
            self.assertEqual(gate["result"], "PASS")

    def test_semantic_delete_without_reconciliation_requires_repair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, prototype, previous, current, overview, final_review = self.fixtures(root)
            result = self.run_cli("--workflow-id", "WF-1", "--prd", prd, "--prototype", prototype, "--manifest", current, "--previous-manifest", previous, "--overview", overview, "--from-revision", "r2", "--to-revision", "r3", "--final-review", final_review, "--out-dir", root / "out", expect=1)
            self.assertEqual(result["status"], "REPAIR_REQUIRED")
            self.assertTrue(Path(result["repairGroup"]).exists())
            repair = json.loads(Path(result["repairGroup"]).read_text(encoding="utf-8"))
            self.assertTrue(any(task["findingType"] == "UNRECONCILED_PROTOTYPE_DELTA" for task in repair["tasks"]))
            self.assertIn("FR-008", prd.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
