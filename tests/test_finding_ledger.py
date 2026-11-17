import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
SCHEMA_ROOT = ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas")
LEDGER = SCRIPTS / "finding_ledger.py"
sys.path.insert(0, str(SCRIPTS))
from validate_json_schemas import validate as validate_schema


class FindingLedgerTests(unittest.TestCase):
    def run_tool(self, *args):
        process = subprocess.run([sys.executable, str(LEDGER), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def findings(self, path: Path):
        path.write_text(json.dumps({
            "findings": [{
                "findingId": "F-STABLE-001",
                "title": "stable finding",
                "severity": "BLOCKING",
                "rootCauseId": "ROOT-001",
                "repairClass": "SEMANTIC",
                "owner": "prd-repair-agent",
                "policyRuleIds": ["G1.MUST.EVIDENCE"],
                "evidenceRefs": ["PRD_DELIVERY.md#L1"],
                "impact": "blocked",
                "closeCondition": "fix and re-audit",
            }],
        }), encoding="utf-8")

    def test_ledger_tracks_repeated_findings_and_closes_after_full_audit(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger = tmp / "findings.json"
            current = tmp / "current.json"
            self.findings(current)
            self.run_tool("--ledger", ledger, "sync", "--findings", current, "--workflow-id", "WF-1", "--revision", "r1")
            self.run_tool("--ledger", ledger, "sync", "--findings", current, "--workflow-id", "WF-1", "--revision", "r2")
            data = json.loads(ledger.read_text())
            self.assertEqual(data["entries"][0]["unresolvedRounds"], 2)
            self.assertEqual(data["entries"][0]["occurrenceCount"], 2)
            self.run_tool("--ledger", ledger, "repairing", "--target-revision", "r3")
            data = json.loads(ledger.read_text())
            self.assertEqual(data["entries"][0]["status"], "in_progress")
            self.assertEqual(data["entries"][0]["repairAttempts"], 1)
            self.run_tool("--ledger", ledger, "close", "--revision", "r3", "--evidence", "audit-stage-r3.json")
            data = json.loads(ledger.read_text())
            self.assertEqual(data["metrics"]["openBlocking"], 0)
            self.assertEqual(data["entries"][0]["status"], "resolved")
            schema = json.loads((SCHEMA_ROOT / "finding-ledger.schema.json").read_text())
            self.assertEqual(validate_schema(data, schema, schema), [])

    def test_finding_absent_from_one_failed_audit_reopens_without_false_stall(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            ledger = tmp / "findings.json"
            present = tmp / "present.json"
            absent = tmp / "absent.json"
            self.findings(present)
            absent.write_text(json.dumps({"findings": []}), encoding="utf-8")
            self.run_tool("--ledger", ledger, "sync", "--findings", present, "--workflow-id", "WF-1", "--revision", "r1")
            self.run_tool("--ledger", ledger, "repairing", "--target-revision", "r2")
            self.run_tool("--ledger", ledger, "sync", "--findings", absent, "--workflow-id", "WF-1", "--revision", "r2")
            self.run_tool("--ledger", ledger, "sync", "--findings", present, "--workflow-id", "WF-1", "--revision", "r3")
            data = json.loads(ledger.read_text())
            self.assertEqual(data["entries"][0]["status"], "reopened")
            self.assertEqual(data["entries"][0]["unresolvedRounds"], 1)


if __name__ == "__main__":
    unittest.main()
