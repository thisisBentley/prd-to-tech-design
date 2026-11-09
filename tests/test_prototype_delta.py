import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
DELTA = ROOT / SCRIPTS / "build_prototype_delta.py"
RECON = ROOT / SCRIPTS / "reconcile_prototype_delta.py"


def manifest(revision, elements):
    return {
        "schemaVersion": 1, "manifestId": f"M-{revision}", "workflowId": "WF-1", "prototypeRevision": revision,
        "prototypePath": "prototype.html", "prototypeHash": "a" * 64, "elements": elements, "createdAt": "2026-11-09T00:00:00Z",
    }


class PrototypeDeltaTests(unittest.TestCase):
    def run_cli(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def test_delete_delta_is_semantic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous = root / "previous.json"; current = root / "current.json"; out = root / "delta.json"
            previous.write_text(json.dumps(manifest("r2", [
                {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
                {"uiElementId": "UI-approval-comment", "frIds": ["FR-008"], "acIds": ["AC-014"], "visibleLabel": "Approval comment", "states": ["default"]},
            ])), encoding="utf-8")
            current.write_text(json.dumps(manifest("r3", [
                {"uiElementId": "UI-submit", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit", "states": ["default"]},
            ])), encoding="utf-8")
            self.run_cli(DELTA, "--previous", previous, "--current", current, "--out", out)
            delta = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(delta["changeType"], "SEMANTIC")
            self.assertTrue(delta["requiresPrdReconciliation"])
            delete = next(change for change in delta["changes"] if change["action"] == "DELETE")
            self.assertEqual(delete["uiElementId"], "UI-approval-comment")
            self.assertEqual(delete["linkedFeatureIds"], ["FR-008"])
            self.assertEqual(delete["linkedAcIds"], ["AC-014"])

    def test_apply_reconciliation_removes_prd_refs_and_closes_delta(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            delta_path = root / "delta.json"; prd = root / "PRD_DELIVERY.md"; out = root / "reconciliation.json"
            delta_path.write_text(json.dumps({
                "schemaVersion": 1, "deltaId": "D-1", "workflowId": "WF-1", "fromPrototypeRevision": "r2", "toPrototypeRevision": "r3",
                "changeType": "SEMANTIC", "requiresPrdReconciliation": True,
                "changes": [{"action": "DELETE", "uiElementId": "UI-approval-comment", "linkedFeatureIds": ["FR-008"], "linkedAcIds": ["AC-014"], "reason": "removed", "evidenceRefs": ["prototype"]}],
                "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            prd.write_text("# PRD\n\n- FR-001: Submit\n- AC-001: Submit works\n- FR-008: Approval comment\n- AC-014: Approval comment persists\n- UI-approval-comment\n", encoding="utf-8")
            self.run_cli(RECON, "--delta", delta_path, "--prd", prd, "--from-prd-revision", "r2", "--to-prd-revision", "r3", "--status", "SYNCED", "--apply", "--out", out)
            reconciliation = json.loads(out.read_text(encoding="utf-8"))
            updated = prd.read_text(encoding="utf-8")
            self.assertEqual(reconciliation["status"], "SYNCED")
            self.assertNotIn("FR-008", updated)
            self.assertNotIn("AC-014", updated)
            self.assertNotIn("UI-approval-comment", updated)
            self.assertEqual(reconciliation["unresolvedDeltas"], [])

    def test_unresolved_status_when_prd_still_contains_refs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            delta_path = root / "delta.json"; prd = root / "PRD_DELIVERY.md"; out = root / "reconciliation.json"
            delta_path.write_text(json.dumps({
                "schemaVersion": 1, "deltaId": "D-2", "workflowId": "WF-1", "fromPrototypeRevision": "r2", "toPrototypeRevision": "r3",
                "changeType": "SEMANTIC", "requiresPrdReconciliation": True,
                "changes": [{"action": "DELETE", "uiElementId": "UI-approval-comment", "linkedFeatureIds": ["FR-008"], "linkedAcIds": ["AC-014"], "reason": "removed", "evidenceRefs": ["prototype"]}],
                "createdAt": "2026-11-09T00:00:00Z",
            }), encoding="utf-8")
            prd.write_text("# PRD\n- FR-008: Approval comment\n", encoding="utf-8")
            self.run_cli(RECON, "--delta", delta_path, "--prd", prd, "--from-prd-revision", "r2", "--to-prd-revision", "r3", "--status", "SYNCED", "--out", out)
            reconciliation = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(reconciliation["status"], "UNRESOLVED")
            self.assertTrue(reconciliation["unresolvedDeltas"])


if __name__ == "__main__":
    unittest.main()
