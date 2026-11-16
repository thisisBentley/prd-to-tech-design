import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
BUILDER = SCRIPTS / "build_candidate_bundle.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CandidateBundleTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(BUILDER), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_inputs(self, root: Path):
        bundle = root / "01-delivery"
        bundle.mkdir()
        prd = bundle / "PRD_DELIVERY.md"
        prd.write_text("# Demo\n\n- FR-001: view result\n- AC-001: result is visible\n", encoding="utf-8")
        overview = bundle / "Overview.html"
        overview.write_text("<html>Overview FR-001 AC-001</html>\n", encoding="utf-8")
        jira = bundle / "Jira_Description.md"
        jira.write_text("## 1. 背景\nDemo\n- FR-001\n", encoding="utf-8")
        return bundle, prd, overview, jira

    def test_builds_candidate_seal_and_frozen_copy(self):
        with tempfile.TemporaryDirectory() as td:
            bundle, prd, overview, jira = self.make_inputs(Path(td))
            result = self.run_tool(
                "--bundle", bundle, "--workflow-id", "WF-CANDIDATE", "--requirement-id", "REQ-1",
                "--requirement-name", "Demo", "--revision", "r1", "--prd", prd,
                "--overview", overview, "--jira", jira,
            )
            self.assertEqual(result["status"], "PASS")
            dd = bundle / ".delivery"
            seal = json.loads((dd / "candidate-seal.json").read_text())
            frozen = bundle / seal["frozenCopy"]
            self.assertTrue(frozen.is_dir())
            self.assertIn("requirements.json", seal["artifactHashes"])
            self.assertEqual(sha(frozen / "PRD_DELIVERY.md"), seal["artifactHashes"]["PRD_DELIVERY.md"])
            self.assertTrue((bundle / "requirements.json").exists())
            self.assertTrue((frozen / "Gates.md").exists())
            self.assertFalse((dd / "final-seal.json").exists())

    def test_reuses_identical_candidate_and_blocks_live_artifact_drift(self):
        with tempfile.TemporaryDirectory() as td:
            bundle, prd, overview, jira = self.make_inputs(Path(td))
            args = ("--bundle", bundle, "--workflow-id", "WF-CANDIDATE", "--requirement-name", "Demo", "--revision", "r1", "--prd", prd, "--overview", overview, "--jira", jira)
            first = self.run_tool(*args)
            self.assertEqual(first["status"], "PASS")
            second = self.run_tool(*args)
            self.assertEqual(second["status"], "PASS")
            overview.write_text(overview.read_text() + "drift\n", encoding="utf-8")
            result = self.run_tool(*args, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("different artifact hashes" in error for error in result["errors"]))

    def test_refuses_to_rebuild_after_final_seal(self):
        with tempfile.TemporaryDirectory() as td:
            bundle, prd, overview, jira = self.make_inputs(Path(td))
            args = ("--bundle", bundle, "--workflow-id", "WF-CANDIDATE", "--requirement-name", "Demo", "--revision", "r1", "--prd", prd, "--overview", overview, "--jira", jira)
            self.run_tool(*args)
            final = bundle / ".delivery" / "final-seal.json"
            final.write_text(json.dumps({"revision": "r1"}), encoding="utf-8")
            result = self.run_tool(*args, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("final-seal.json already exists" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
