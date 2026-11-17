import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
CYCLE = SCRIPTS / "run_audit_repair_cycle.py"
LOCK = SCRIPTS / "build_policy_lock.py"
AUDIT_WORKER = ROOT / "tests" / "fixtures" / "audit" / "cycle_audit_worker.py"
REPAIR_WORKER = ROOT / "tests" / "fixtures" / "audit" / "cycle_repair_worker.py"
PROFILE = ROOT / "config" / "audit-profiles" / "prd-only.json"
CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"


class AuditRepairCycleTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_bundle(self, root: Path):
        run_root = root / "run"
        bundle = run_root / "01-delivery"
        dd = bundle / ".delivery"
        bundle.mkdir(parents=True)
        dd.mkdir()
        (bundle / "PRD_DELIVERY.md").write_text("# Demo\n\n- FR-001: result\n- AC-001: visible\n", encoding="utf-8")
        (bundle / "Overview.html").write_text("<html>FR-001 AC-001</html>\n", encoding="utf-8")
        (bundle / "Jira_Description.md").write_text("## 1. 背景\nDemo\n- FR-001\n", encoding="utf-8")
        self.run_tool(LOCK, "--artifact-profile", "PRD_ONLY", "--requirement-types", "CRUD", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE", "--out", dd / "policy-lock.json")
        return run_root, bundle

    def test_cycle_repairs_active_artifact_builds_new_revision_and_reaudits(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle = self.make_bundle(Path(td))
            result = self.run_tool(CYCLE, "--run-root", run_root, "--bundle", bundle, "--workflow-id", "WF-CYCLE", "--requirement-name", "Demo", "--max-rounds", "2", "--profile", PROFILE, "--crosswalk", CROSSWALK, "--audit-worker", sys.executable, AUDIT_WORKER.resolve(), "--repair-worker", sys.executable, REPAIR_WORKER.resolve())
            self.assertEqual(result.get("status"), "AUDIT_PASS", result)
            self.assertEqual(result.get("revision"), "r2", result)
            report = json.loads(Path(result["out"]).read_text())
            self.assertEqual(len(report["rounds"]), 2)
            self.assertEqual(report["rounds"][0]["revision"], "r1")
            self.assertEqual(report["rounds"][1]["revision"], "r2")
            self.assertTrue((bundle / ".delivery" / "candidate-revisions" / "r1").exists())
            self.assertTrue((bundle / ".delivery" / "candidate-revisions" / "r2").exists())
            self.assertIn("# repaired", (bundle / "PRD_DELIVERY.md").read_text())
            self.assertEqual(json.loads((bundle / ".delivery" / "candidate-seal.json").read_text())["revision"], "r2")
            ledger = json.loads((bundle / ".delivery" / "findings.json").read_text())
            self.assertEqual(ledger["metrics"]["openBlocking"], 0)
            self.assertEqual(ledger["metrics"]["resolved"], 1)
            self.assertEqual(ledger["entries"][0]["status"], "resolved")
            self.assertEqual(ledger["entries"][0]["repairAttempts"], 1)

    def test_cycle_blocks_when_repair_worker_reports_no_change(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle = self.make_bundle(Path(td))
            no_change = Path(td) / "no_change.py"
            no_change.write_text("""import argparse,json\np=argparse.ArgumentParser(); p.add_argument('--bundle'); p.add_argument('--findings'); p.add_argument('--revision'); p.add_argument('--out'); a=p.parse_args(); open(a.out,'w').write(json.dumps({'schemaVersion':1,'status':'PASS','revision':a.revision,'changedArtifacts':[],'repairedRootCauses':[],'repairTranscript':'none'}));\n""", encoding="utf-8")
            result = self.run_tool(CYCLE, "--run-root", run_root, "--bundle", bundle, "--workflow-id", "WF-CYCLE", "--requirement-name", "Demo", "--max-rounds", "1", "--profile", PROFILE, "--crosswalk", CROSSWALK, "--audit-worker", sys.executable, AUDIT_WORKER.resolve(), "--repair-worker", sys.executable, no_change.resolve(), expect=1)
            self.assertEqual(result["status"], "AUDIT_BLOCKED")
            self.assertTrue(any("changed no active artifacts" in error for error in result["errors"]))

    def test_cycle_stops_when_same_finding_survives_two_rounds(self):
        with tempfile.TemporaryDirectory() as td:
            run_root, bundle = self.make_bundle(Path(td))
            persistent_repair = Path(td) / "persistent_repair.py"
            persistent_repair.write_text("""import argparse,json,pathlib\np=argparse.ArgumentParser(); p.add_argument('--bundle'); p.add_argument('--findings'); p.add_argument('--revision'); p.add_argument('--out'); a=p.parse_args(); path=pathlib.Path(a.bundle)/'PRD_DELIVERY.md'; path.write_text(path.read_text()+'\\nrepair attempt\\n'); open(a.out,'w').write(json.dumps({'schemaVersion':1,'status':'PASS','revision':a.revision,'changedArtifacts':['PRD_DELIVERY.md'],'repairedRootCauses':['F-REPAIR-ME'],'repairTranscript':'attempted'}));\n""", encoding="utf-8")
            result = self.run_tool(CYCLE, "--run-root", run_root, "--bundle", bundle, "--workflow-id", "WF-CYCLE", "--requirement-name", "Demo", "--max-rounds", "2", "--profile", PROFILE, "--crosswalk", CROSSWALK, "--audit-worker", sys.executable, AUDIT_WORKER.resolve(), "--repair-worker", sys.executable, persistent_repair.resolve(), expect=1)
            self.assertEqual(result["status"], "AUDIT_BLOCKED")
            self.assertTrue(any("unchanged for two repair rounds" in error for error in result["errors"]))
            ledger = json.loads((bundle / ".delivery" / "findings.json").read_text())
            self.assertEqual(ledger["entries"][0]["unresolvedRounds"], 2)
            self.assertEqual(ledger["entries"][0]["status"], "open")


if __name__ == "__main__":
    unittest.main()
