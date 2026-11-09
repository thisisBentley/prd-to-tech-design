import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORCH = ROOT / "tools" / "orchestrate.py"


class ReconcileDeliveryTests(unittest.TestCase):
    def run_cli(self, *args, expect=0):
        p = subprocess.run([sys.executable, str(ORCH), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(p.returncode, expect, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def test_reconcile_collects_review_and_creates_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"; plan = root / "plan.json"
            self.run_cli("init", "--run-root", root, "--workflow-id", "WF-1", "--requirement-name", "Demo", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE")
            self.run_cli("build-delivery-plan", "--run-root", root, "--out", plan)
            reviews = root / ".agents" / "reviews"; reviews.mkdir(parents=True, exist_ok=True)
            review = reviews / "delivery-review.json"
            review.write_text(json.dumps({
                "schemaVersion":1,"reviewRunId":"RR-1","workflowId":"WF-1","targetRevision":"r1","reviewerRole":"delivery-reviewer","verdict":"RETURNED","findings":[{"findingId":"F-1","rootCauseId":"R-1","repairClass":"SEMANTIC","severity":"BLOCKING","title":"gap","evidenceRefs":["prd"],"closeCondition":"fix","expectedInvariant":"consistent","regressionTests":["test"],"owner":"delivery-producer"}]
            }), encoding="utf-8")
            result = self.run_cli("reconcile-delivery", "--run-root", root, "--plan", plan)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["batchStatus"], "READY_FOR_REPAIR")
            self.assertEqual(result["blockingCount"], 1)
            self.assertTrue(Path(result["repairBatch"]).exists())


if __name__ == "__main__": unittest.main()
