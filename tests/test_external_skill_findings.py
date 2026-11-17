import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
TOOL = SCRIPTS / "import_external_skill_findings.py"
LEDGER = SCRIPTS / "finding_ledger.py"


class ExternalSkillFindingTests(unittest.TestCase):
    def run_tool(self, tool, *args, expect=0):
        process = subprocess.run([sys.executable, str(tool), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_stable_identity_and_ledger_sync(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "skill.json"
            source.write_text(json.dumps({"findings": [{"id": "G1-001", "title": "PRD section conflict", "severity": "P0", "ruleId": "G1.MUST.FLOW_BRANCH", "category": "SPEC_CONTRADICTION", "artifact": "PRD.md", "evidenceRefs": ["PRD.md#FR-001"]}]}), encoding="utf-8")
            batch = root / "batch.json"
            self.run_tool(TOOL, "--input", source, "--skill-id", "prd-review", "--workflow-id", "WF", "--revision", "r1", "--out", batch)
            data = json.loads(batch.read_text())
            first_id = data["findings"][0]["findingId"]
            source.write_text(json.dumps({"findings": [{"id": "G1-001", "title": "Changed wording but same root", "severity": "P0", "ruleId": "G1.MUST.FLOW_BRANCH", "category": "SPEC_CONTRADICTION", "artifact": "PRD.md", "evidenceRefs": ["PRD.md#FR-001"]}]}), encoding="utf-8")
            self.run_tool(TOOL, "--input", source, "--skill-id", "prd-review", "--workflow-id", "WF", "--revision", "r1", "--out", batch)
            self.assertEqual(json.loads(batch.read_text())["findings"][0]["findingId"], first_id)
            ledger = root / "findings.json"
            self.run_tool(LEDGER, "--ledger", ledger, "sync", "--findings", batch, "--workflow-id", "WF", "--revision", "r1")
            self.assertEqual(json.loads(ledger.read_text())["metrics"]["openBlocking"], 1)


if __name__ == "__main__":
    unittest.main()
