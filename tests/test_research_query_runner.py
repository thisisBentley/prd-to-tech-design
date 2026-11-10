import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
RUNNER = ROOT / SCRIPTS / "run_research_queries.py"


class ResearchQueryRunnerTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def request(self, queries):
        return {
            "schemaVersion": 1, "workflowId": "WF-RESEARCH", "requirementKey": "DEMO-1",
            "clues": [{"clueId": "C-1", "clue": "existing field mapping", "clueType": "FIELD_MAPPING", "queries": queries}],
            "budget": {"maxQueries": 5, "timeoutSeconds": 2, "retries": 2, "backoffSeconds": 0},
        }

    def adapter_script(self, root, behavior="success"):
        path = root / "adapter.py"
        path.write_text(f'''import json, os, sys
from pathlib import Path
counter = Path(os.environ.get("ADAPTER_COUNTER", {str(root / 'counter.txt')!r}))
attempt = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(attempt))
request = json.load(sys.stdin)
if {behavior!r} == "retry" and attempt == 1:
    sys.stderr.write("transient")
    raise SystemExit(2)
if {behavior!r} == "error":
    raise SystemExit(2)
print(json.dumps({{"status": "OK", "records": [{{"sourceRef": "jira://DEMO-1", "status": "CONFIRMED", "claims": [{{"claim": "field exists", "confidence": "HIGH"}}], "evidenceRefs": ["jira://DEMO-1#field"]}}]}}))
''', encoding="utf-8")
        return path

    def run_runner(self, root, behavior="success", expect=0, query_source="JIRA", config_source=None):
        adapter = self.adapter_script(root, behavior)
        request = self.request([{"queryId": "Q-1", "source": query_source, "query": "field mapping", "purpose": "verify"}])
        request_path = root / "request.json"; self.write(request_path, request)
        config = {"schemaVersion": 1, "adapters": [{"source": config_source or query_source, "command": [sys.executable, str(adapter)]}]}
        config_path = root / "adapters.json"; self.write(config_path, config)
        out = root / "result.json"
        proc = subprocess.run([sys.executable, str(RUNNER), "--request", str(request_path), "--adapters", str(config_path), "--out", str(out)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(out.read_text()) if out.exists() else {}

    def test_executes_adapter_and_normalizes_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_runner(Path(td))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["records"][0]["status"], "CONFIRMED")
            self.assertEqual(result["records"][0]["evidenceRefs"], ["jira://DEMO-1#field"])
            self.assertEqual(len(result["records"][0]["attempts"]), 1)

    def test_retries_transient_adapter_failure(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_runner(Path(td), behavior="retry")
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(len(result["records"][0]["attempts"]), 2)
            self.assertEqual(result["metrics"]["retries"], 1)

    def test_missing_adapter_is_recorded_as_unavailable_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_runner(Path(td), query_source="MCP_CODE", config_source="JIRA", expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["records"][0]["error"], "NOT_CONFIGURED")
            self.assertEqual(result["metrics"]["errors"], 1)

    def test_persistent_adapter_error_is_auditable(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_runner(Path(td), behavior="error", expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(len(result["records"][0]["attempts"]), 3)


if __name__ == "__main__":
    unittest.main()
