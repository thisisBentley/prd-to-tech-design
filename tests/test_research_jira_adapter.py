import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters" / "research" / "providers" / "project_management_space_adapter.py"


class ResearchJiraAdapterTests(unittest.TestCase):
    def test_normalizes_issue_snapshot_and_attachment_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake = root / "fake_pms.py"
            fake.write_text('''import json, sys
print(json.dumps({"key":"DEMO-1","summary":"Existing scene intent","status":"Done","url":"jira://DEMO-1","updated_at":"2026-11-10T00:00:00Z","source_hash":"abc","attachments":[{"id":"10","sha256":"a"*64}]}))
''', encoding="utf-8")
            request = {"schemaVersion": 1, "workflowId": "WF", "query": {"queryId": "Q", "source": "JIRA", "query": "DEMO-1", "purpose": "get"}}
            proc = subprocess.run([sys.executable, str(ADAPTER), "--cli", sys.executable, str(fake), "--config", str(root / "config.json"), "--space", "jira"], input=json.dumps(request), text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["records"][0]["status"], "CONFIRMED")
            self.assertTrue(any("sha256=" in ref for ref in result["records"][0]["evidenceRefs"]))
            self.assertEqual(result["records"][0]["sourceHash"], "abc")

    def test_cli_error_is_retryable_and_auditable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fake = root / "fake_pms.py"
            fake.write_text('import sys\nsys.stderr.write("temporary failure")\nraise SystemExit(2)\n', encoding="utf-8")
            request = {"schemaVersion": 1, "workflowId": "WF", "query": {"queryId": "Q", "source": "JIRA", "query": "DEMO-1", "purpose": "get"}}
            proc = subprocess.run([sys.executable, str(ADAPTER), "--cli", sys.executable, str(fake), "--config", str(root / "config.json"), "--space", "jira"], input=json.dumps(request), text=True, capture_output=True)
            self.assertEqual(proc.returncode, 2)
            result = json.loads(proc.stdout)
            self.assertTrue(result["retryable"])
            self.assertIn("temporary failure", result["error"])


if __name__ == "__main__":
    unittest.main()
