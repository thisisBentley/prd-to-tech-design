import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
TOOL = SCRIPTS / "resolve_evidence.py"
SCHEMA_ROOT = ROOT / ("references" if ROOT.name == "ai-native-delivery" else "schemas")
sys.path.insert(0, str(SCRIPTS))
from validate_json_schemas import validate as validate_schema


class EvidenceResolverTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def fixture(self, root: Path):
        artifacts = root / "artifacts"
        artifacts.mkdir()
        (artifacts / "PRD.md").write_text("# PRD\n\n## FR-001\nUser sees result.\n", encoding="utf-8")
        (artifacts / "prototype.html").write_text('<html><div data-ai-id="UI-RESULT">Result</div></html>', encoding="utf-8")
        (artifacts / "data.json").write_text(json.dumps({"checks": [{"status": "passed"}]}), encoding="utf-8")
        plan = {
            "workflowId": "WF-EVR", "revision": "r1",
            "jobs": [{"jobId": "JOB-1", "sourcePolicyRuleIds": ["G1.MUST.BACKGROUND_GOAL_SCOPE"]}],
        }
        plan_path = root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result = {
            "jobId": "JOB-1",
            "checks": [{
                "checkId": "CHECK-1", "status": "passed",
                "evidenceRefs": ["PRD.md#FR-001", "prototype.html#UI-RESULT", "data.json#/checks/0/status", "PRD.md#L3-L4"],
                "observed": "FR-001 result is grounded in the frozen PRD", "expected": "requirement exists",
                "policyRuleIds": ["G1.MUST.BACKGROUND_GOAL_SCOPE"],
            }],
        }
        results = root / "results"; results.mkdir()
        (results / "JOB-1.result.json").write_text(json.dumps(result), encoding="utf-8")
        declarations = root / "declarations.json"
        declarations.write_text(json.dumps({"declarations": [{
            "obligationId": "OBL-1", "ruleId": "G1.MUST.BACKGROUND_GOAL_SCOPE",
            "artifact": "PRD.md", "location": "FR-001", "evidenceRefs": ["PRD.md#FR-001"],
        }]}), encoding="utf-8")
        return artifacts, plan_path, results, declarations

    def test_resolves_markdown_html_json_and_line_ranges(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); artifacts, plan, results, declarations = self.fixture(root)
            out = root / "report.json"
            result = self.run_tool("--artifact-root", artifacts, "--plan", plan, "--results-dir", results, "--declarations", declarations, "--out", out)
            self.assertEqual(result["status"], "PASS")
            report = json.loads(out.read_text())
            self.assertEqual(report["metrics"]["unresolved"], 0)
            fragment_types = {item["fragmentType"] for item in report["resolutions"]}
            self.assertTrue({"MARKDOWN_HEADING", "HTML_ANCHOR", "JSON_POINTER", "LINE_RANGE"} <= fragment_types)
            schema = json.loads((SCHEMA_ROOT / "evidence-resolution-report.schema.json").read_text())
            self.assertEqual(validate_schema(report, schema, schema), [])

    def test_unresolved_fragment_and_vacuous_observation_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); artifacts, plan, results, declarations = self.fixture(root)
            path = results / "JOB-1.result.json"
            data = json.loads(path.read_text())
            data["checks"][0]["evidenceRefs"] = ["PRD.md#DOES-NOT-EXIST"]
            data["checks"][0]["observed"] = data["checks"][0]["expected"]
            path.write_text(json.dumps(data), encoding="utf-8")
            out = root / "report.json"
            self.run_tool("--artifact-root", artifacts, "--plan", plan, "--results-dir", results, "--declarations", declarations, "--out", out, expect=1)
            report = json.loads(out.read_text())
            codes = {item["code"] for item in report["findings"]}
            self.assertIn("VACUOUS_AUDIT_EVIDENCE", codes)
            self.assertIn("UNRESOLVED_AUDIT_EVIDENCE", codes)


if __name__ == "__main__":
    unittest.main()
