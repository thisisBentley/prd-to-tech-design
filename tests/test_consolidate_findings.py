import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "consolidate_findings.py"


class ConsolidateFindingsTests(unittest.TestCase):
    def test_groups_review_findings_by_root_cause(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); r1 = root / "r1.json"; r2 = root / "r2.json"; out = root / "batch.json"
            base = {
                "workflowId": "WF-1", "targetRevision": "r3", "findings": [],
            }
            for path, title in [(r1, "same root one"), (r2, "same root two")]:
                data = dict(base)
                data["findings"] = [{
                    "findingId": title, "rootCauseId": "ZERO-DENOM-001", "repairClass": "SEMANTIC", "ruleId": "G1.MUST.STATES_EXCEPTIONS",
                    "severity": "BLOCKING", "title": title, "evidenceRefs": [title],
                    "closeCondition": "isolate fixture", "expectedInvariant": "other metrics unchanged",
                    "regressionTests": ["test-zero-denom"], "owner": "delivery-producer",
                }]
                path.write_text(json.dumps(data), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--review", r1, "--review", r2, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "READY_FOR_REPAIR")
            self.assertEqual(len(result["groups"]), 1)
            self.assertEqual(len(result["groups"][0]["findingIds"]), 2)
            self.assertEqual(result["groups"][0]["rootCauseId"], "ZERO-DENOM-001")
            self.assertEqual(result["groups"][0]["ruleIds"], ["G1.MUST.STATES_EXCEPTIONS"])

    def test_mixed_revisions_fail_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); r1 = root / "r1.json"; r2 = root / "r2.json"; out = root / "batch.json"
            for path, rev in [(r1, "r1"), (r2, "r2")]:
                path.write_text(json.dumps({"workflowId": "WF-1", "targetRevision": rev, "findings": []}), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(TOOL), "--review", r1, "--review", r2, "--out", out], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(json.loads(out.read_text())["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
