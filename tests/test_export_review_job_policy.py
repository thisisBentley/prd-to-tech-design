import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
LOCK = SCRIPTS / "build_policy_lock.py"
EXPORT = SCRIPTS / "export_review_job.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExportReviewJobPolicyTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_review_job_contains_applicable_rule_cards(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "01-delivery"
            dd = root / ".delivery"
            cr = dd / "candidate-revisions" / "r1"
            cr.mkdir(parents=True)
            (dd / "policy-lock.json").parent.mkdir(parents=True, exist_ok=True)
            lock = dd / "policy-lock.json"
            self.run_tool(LOCK, "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--requirement-types", "CRUD,UI_INTERACTION", "--prototype-status", "TRIGGERED", "--ui-ownership", "LOCAL", "--out", lock)
            artifacts = {}
            for name in ["Demo_PRD_DELIVERY.md", "Demo_Prototype.html", "Demo_Overview.html", "Demo_Jira_Description.md", "Demo_Gates.md", "Demo_Workflow.md", "prototype-manifest.json", "requirements.json"]:
                path = cr / name
                path.write_text(name, encoding="utf-8")
                artifacts[name] = sha(path)
            seal = {"bundleId": "DEMO", "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1", "artifactHashes": artifacts}
            (dd / "candidate-seal.json").write_text(json.dumps(seal), encoding="utf-8")
            out = Path(td) / "review-job.json"
            result = self.run_tool(EXPORT, root, "--out", out)
            job = json.loads(out.read_text())
            self.assertEqual(result["status"], "READY")
            self.assertEqual(job["policyLockSha256"], sha(lock))
            self.assertTrue(job["applicableRules"]["G1"])
            self.assertTrue(job["rulesByGate"]["U1"])
            self.assertTrue(all("ruleId" in card for card in job["rulesByGate"]["G1"]))
            self.assertIn("one check per applicable ruleId", job["contract"]["passPolicy"])


if __name__ == "__main__":
    unittest.main()
