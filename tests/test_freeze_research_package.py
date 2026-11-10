import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "freeze_research_package.py"
IMPORTER = ROOT / SCRIPTS / "import_research_package.py"


class FreezeResearchPackageTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def package(self, root):
        record = {
            "schemaVersion": 1, "researchId": "R-1", "workflowId": "WF-FREEZE",
            "clue": "field mapping", "clueType": "FIELD_MAPPING",
            "researchPlan": [{"source": "JIRA", "query": "field", "purpose": "verify"}],
            "sourcesChecked": [{"source": "JIRA", "status": "AVAILABLE", "evidenceRefs": ["sources/jira.json"]}],
            "findings": [{"claim": "field exists", "evidenceRefs": ["sources/jira.json"], "confidence": "HIGH"}],
            "verdict": "FACT_RESOLVED", "decisionRequired": False, "resolutionOwner": "DELIVERY",
            "nextAction": "write back", "evidenceRefs": ["sources/jira.json"], "createdAt": "2026-11-10T00:00:00Z",
        }
        self.write(root / "research-records" / "R-1.json", record)
        self.write(root / "sources" / "jira.json", {"source": "JIRA", "key": "DEMO-1"})
        self.write(root / "research-capabilities.json", {"schemaVersion": 1, "generatedAt": "2026-11-10T00:00:00Z", "researchFirstRequired": True, "sources": [{"source": "JIRA", "configured": True, "status": "CONFIGURED_AVAILABLE"}]})

    def test_freezes_valid_package_that_can_be_imported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "package"; self.package(package)
            proc = subprocess.run([sys.executable, str(TOOL), "--root", str(package), "--requirement-key", "DEMO-1", "--workflow-id", "WF-FREEZE", "--classification", "REAL"], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads(proc.stdout)
            self.assertEqual(result["status"], "FROZEN")
            manifest = json.loads((package / "manifest.json").read_text())
            self.assertEqual(manifest["classification"], "REAL")
            self.assertEqual(len(manifest["files"]), 3)

            run = root / "run"
            subprocess.run([sys.executable, str(ROOT / SCRIPTS / "orchestrate.py"), "init", "--run-root", str(run), "--workflow-id", "WF-FREEZE", "--requirement-name", "Freeze", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE"], check=True, capture_output=True)
            out = root / "import.json"
            proc = subprocess.run([sys.executable, str(IMPORTER), "--package", str(package), "--run-root", str(run), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_rejects_workflow_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            package = Path(td) / "package"; self.package(package)
            record_path = package / "research-records" / "R-1.json"
            record = json.loads(record_path.read_text()); record["workflowId"] = "WRONG"
            self.write(record_path, record)
            proc = subprocess.run([sys.executable, str(TOOL), "--root", str(package), "--requirement-key", "DEMO-1", "--workflow-id", "WF-FREEZE"], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("workflowId mismatch", proc.stdout)


if __name__ == "__main__":
    unittest.main()
