import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "validate_delivery_artifacts.py"


class DeliveryArtifactQualityTests(unittest.TestCase):
    def fixtures(self, root, production=True):
        prd = root / "PRD_DELIVERY.md"
        fr = "- FR-001: User submits an expense request." if not production else "- FR-001: User submits an expense request and sees validation."
        ac = "- AC-001: Expense submission is verified for FR-001." if production else "- AC-001: All supplied functional requirements are implemented and verifiable."
        sections = """
## Permissions
- submitter ALLOWED submit expense

## States
- draft: reachable from expense form with precondition defined
- submitted: reached after submit from draft with precondition defined

## Exceptions and Recovery
- validation failure keeps draft state and shows the field error
""" if production else """
## Permissions
- UNSPECIFIED role may interact with the feature

## States
- default: precondition defined by PRD
"""
        prd.write_text(f"# PRD_DELIVERY\n\n## Requirement Summary\nExpense flow\n\n## Functional Requirements\n{fr}\n\n## Acceptance Criteria\n{ac}\n{sections}\n## Non-Goals\n- No approval workflow\n", encoding="utf-8")
        source_hash = hashlib.sha256(prd.read_bytes()).hexdigest()
        prototype = root / "Prototype.html"
        if production:
            prototype.write_text(f'<!doctype html><html><body><form data-ai-id="expense-form" data-ai-fr="FR-001" data-ai-ac="AC-001" data-ai-state="draft,submitted" data-ai-permission-edge="P-1"><label>Expense amount</label><button>Submit expense</button></form></body></html>', encoding="utf-8")
        else:
            prototype.write_text(f'<!doctype html><html><body><button data-ai-id="UI-FR-001" data-ai-fr="FR-001" data-ai-ac="AC-001">FR-001 interaction</button></body></html>', encoding="utf-8")
        manifest = root / "prototype-manifest.json"
        manifest.write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-Q", "prototypeRevision": "r1", "elements": [{"uiElementId": "expense-form" if production else "UI-FR-001", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Submit expense" if production else "FR-001 interaction", "states": ["draft", "submitted"] if production else ["default"], "permissions": ["submitter allowed"] if production else ["as defined by PRD"]}]}), encoding="utf-8")
        overview = root / "Overview.html"
        tabs = "".join(f"<section><h2>{tab}</h2><p>{fr} {ac}</p></section>" for tab in ["方案摘要", "背景与现状", "目标与范围", "功能与规则", "流程与状态", "验收与风险"])
        overview.write_text(f'<!doctype html><html><head><meta name="source-prd-sha256" content="{source_hash}"></head><body>{tabs}</body></html>', encoding="utf-8")
        jira = root / "Jira_Description.md"
        jira.write_text(f"<!-- source-prd-sha256: {source_hash} -->\n## 1. 背景\nExpense\n## 2. 现状\nManual\n## 3. 目标\nOnline\n## 4. 功能点\n{fr}\n", encoding="utf-8")
        return prd, prototype, manifest, overview, jira

    def run_tool(self, root, mode, expect=0, profile="PRD_PLUS_PROTOTYPE"):
        prd, prototype, manifest, overview, jira = self.fixtures(root, production=mode != "deterministic")
        out = root / "quality.json"
        proc = subprocess.run([
            sys.executable, str(TOOL), "--prd", str(prd), "--artifact-profile", profile,
            "--producer-mode", mode, "--prototype", str(prototype), "--manifest", str(manifest),
            "--overview", str(overview), "--jira", str(jira), "--out", str(out),
        ], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        result = json.loads(out.read_text())
        self.assertIn("prdProducerMode", result)
        self.assertIn("downstreamProducerMode", result)
        return result

    def test_deterministic_artifacts_are_structurally_valid_but_baseline_only(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_tool(Path(td), "deterministic")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["qualityLevel"], "BASELINE_ONLY")
            self.assertFalse(result["productionCandidate"])
            self.assertTrue(result["qualityDefects"])

    def test_provided_semantic_artifacts_can_be_production_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_tool(Path(td), "provided")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["qualityLevel"], "PRODUCTION_CANDIDATE")
            self.assertTrue(result["productionCandidate"])
            self.assertEqual(result["qualityDefects"], [])

    def test_missing_prototype_is_structural_blocker_for_pair_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, _, _, overview, jira = self.fixtures(root, production=True)
            out = root / "quality.json"
            proc = subprocess.run([sys.executable, str(TOOL), "--prd", str(prd), "--artifact-profile", "PRD_PLUS_PROTOTYPE", "--producer-mode", "provided", "--overview", str(overview), "--jira", str(jira), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "BLOCKED")
            self.assertFalse(result["productionCandidate"])


if __name__ == "__main__":
    unittest.main()
