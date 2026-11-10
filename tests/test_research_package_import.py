import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
IMPORTER = ROOT / SCRIPTS / "import_research_package.py"


class ResearchPackageImportTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def package(self, root):
        package = root / "package"
        record = {
            "schemaVersion": 1, "researchId": "R-TECH-1", "workflowId": "WF-IMPORT",
            "clue": "interface contract absent", "clueType": "TECHNICAL_IMPLEMENTATION",
            "researchPlan": [{"source": "MCP_CODE", "query": "contract", "purpose": "verify"}],
            "sourcesChecked": [{"source": "MCP_CODE", "status": "UNAVAILABLE"}],
            "findings": [{"claim": "contract unavailable", "evidenceRefs": ["sources/integrity.json"], "confidence": "HIGH"}],
            "verdict": "NO_EVIDENCE", "decisionRequired": False, "resolutionOwner": "TECH",
            "decisionRationale": "implementation evidence missing", "nextAction": "Tech resolves before design",
            "evidenceRefs": ["sources/integrity.json"], "createdAt": "2026-11-10T00:00:00Z",
        }
        product_record = {
            "schemaVersion": 1, "researchId": "R-PRODUCT-1", "workflowId": "WF-IMPORT",
            "clue": "which visible result mode", "clueType": "BUSINESS_POLICY",
            "researchPlan": [{"source": "JIRA", "query": "result mode", "purpose": "find precedent"}],
            "sourcesChecked": [{"source": "JIRA", "status": "AVAILABLE", "evidenceRefs": ["sources/integrity.json"]}],
            "findings": [{"claim": "no precedent", "evidenceRefs": ["sources/integrity.json"], "confidence": "MEDIUM"}],
            "verdict": "NEEDS_BUSINESS_DECISION", "decisionRequired": True, "resolutionOwner": "PRODUCT",
            "decisionRationale": "user-visible choice", "nextAction": "ask product",
            "evidenceRefs": ["sources/integrity.json"], "createdAt": "2026-11-10T00:00:00Z",
        }
        decision = {
            "schemaVersion": 1, "decisionId": "D-1", "workflowId": "WF-IMPORT", "reviewerRole": "semantic-consistency-reviewer",
            "businessScenario": "choice", "currentFacts": ["fact"], "ambiguity": "choice",
            "options": [{"optionId": "A", "label": "A", "result": "A", "impact": "A", "reversibility": "reversible"}, {"optionId": "B", "label": "B", "result": "B", "impact": "B", "reversibility": "reversible"}],
            "recommendation": "A", "defaultAndRisk": "B is riskier", "owner": "product", "closeCondition": "choose",
            "researchRecordPath": "../research-records/R-PRODUCT-1.json", "researchVerdict": "NEEDS_BUSINESS_DECISION",
            "researchEvidenceRefs": ["sources/integrity.json"], "whyDecisionRequired": "user-visible choice",
            "status": "open", "createdAt": "2026-11-10T00:00:00Z",
        }
        self.write(package / "research-records" / "R-TECH-1.json", record)
        self.write(package / "research-records" / "R-PRODUCT-1.json", product_record)
        self.write(package / "decision-cards" / "D-1.json", decision)
        self.write(package / "sources" / "integrity.json", {"schemaVersion": 1, "status": "UNAVAILABLE"})
        self.write(package / "research-capabilities.json", {"schemaVersion": 1, "generatedAt": "2026-11-10T00:00:00Z", "researchFirstRequired": True, "sources": [{"source": "JIRA", "configured": True, "status": "CONFIGURED_AVAILABLE"}]})
        files = []
        for path in sorted(package.rglob("*")):
            if path.is_file():
                files.append({"path": path.relative_to(package).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size})
        self.write(package / "manifest.json", {"schemaVersion": 1, "requirementKey": "DEMO-1", "workflowId": "WF-IMPORT", "classification": "SYNTHETIC", "generatedAt": "2026-11-10T00:00:00Z", "files": files})
        return package

    def prepare_run(self, root):
        subprocess.run([sys.executable, str(ROOT / SCRIPTS / "orchestrate.py"), "init", "--run-root", str(root), "--workflow-id", "WF-IMPORT", "--requirement-name", "Import", "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE"], check=True, capture_output=True, text=True)

    def test_imports_verified_package_and_routes_technical_gaps(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self.package(root)
            run_root = root / "run"; self.prepare_run(run_root)
            out = root / "import.json"
            process = subprocess.run([sys.executable, str(IMPORTER), "--package", str(package), "--run-root", str(run_root), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["researchRecords"], 2)
            self.assertEqual(result["decisionCards"], 1)
            self.assertEqual(result["technicalGaps"], 1)
            self.assertTrue((run_root / ".agents" / "decisions" / "D-1.json").exists())
            gaps = json.loads((run_root / ".agents" / "context" / "technical-gaps.json").read_text())
            self.assertEqual(gaps["gaps"][0]["researchId"], "R-TECH-1")
            state = json.loads((run_root / ".agents" / "orchestration.json").read_text())
            self.assertEqual(len(state["researchRecords"]), 2)

    def test_rejects_tampered_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = self.package(root)
            (package / "sources" / "integrity.json").write_text("{}", encoding="utf-8")
            run_root = root / "run"; self.prepare_run(run_root)
            out = root / "import.json"
            process = subprocess.run([sys.executable, str(IMPORTER), "--package", str(package), "--run-root", str(run_root), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("hash mismatch" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
