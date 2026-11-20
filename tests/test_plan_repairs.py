import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "plan_repairs.py"


class PlanRepairTests(unittest.TestCase):
    def test_builds_tasks_only_from_planned_change_sets(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            batch = root / "batch.json"
            out = root / "plan.json"
            batch.write_text(json.dumps({
                "schemaVersion": 1,
                "batchType": "CHANGE_SET_BATCH",
                "batchId": "CHANGE-SET-BATCH-1",
                "workflowId": "WF-1",
                "targetRevision": "r2",
                "status": "READY_FOR_REPAIR",
                "changeSets": [{
                    "changeSetId": "CHANGE-SET-1",
                    "rootCauseId": "VISIBLE-001",
                    "findingIds": ["F-1"],
                    "classification": "ARTIFACT_DRIFT",
                    "repairTrack": "ARTIFACT_SYNC",
                    "businessRevisionRequired": False,
                    "ownerRole": "projection-repair-agent",
                    "affectedArtifacts": [{"path": "Overview.html", "artifactType": "OVERVIEW", "reason": "drift"}],
                    "verificationPlan": [{"checkId": "CHANGE.ARTIFACT.SYNC", "kind": "PROJECTION_SYNC", "description": "sync", "required": True}],
                    "budget": {"maxAffectedArtifacts": 6, "maxFindings": 20, "maxRepairRounds": 2, "maxChangedLines": 800},
                    "closeConditions": ["projection is current"],
                    "status": "PLANNED",
                }],
            }), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--change-set-batch", str(batch), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "READY")
            task = result["tasks"][0]
            self.assertEqual(task["changeSetId"], "CHANGE-SET-1")
            self.assertEqual(task["classification"], "ARTIFACT_DRIFT")
            self.assertEqual(task["role"], "projection-repair-agent")
            self.assertEqual(task["affectedArtifacts"], ["Overview.html"])
            self.assertEqual(task["budget"]["maxRepairRounds"], 2)


if __name__ == "__main__":
    unittest.main()
