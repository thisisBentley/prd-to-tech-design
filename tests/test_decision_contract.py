import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
COMPILE = TOOLS / "compile_decision_contract.py"
VALIDATE = TOOLS / "validate_decision_readiness.py"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class DecisionContractTests(unittest.TestCase):
    def fixture(self, root):
        prd = root / "PRD_DELIVERY.md"
        prd.write_text("# Demo\n\n## FR-001: Save\n\n- 业务规则：保存前必须校验权限。\n\n## AC-001: No permission\n\n- 关联功能：FR-001\n- WHEN: 无权限\n- THEN: 拒绝保存\n", encoding="utf-8")
        context = root / "decision-context.json"
        context.write_text(json.dumps({
            "schemaVersion": 1,
            "requirementName": "Demo",
            "issueKey": "BOT-1",
            "generatedAt": "2026-11-20T00:00:00+08:00",
            "sourceStage": "delivery",
            "decisionReadiness": "READY",
            "openBlockingCount": 0,
            "decisions": [{
                "decisionId": "CD-1",
                "title": "Permission behavior",
                "category": "product_decision",
                "businessScenario": "save",
                "currentFacts": [{"claim": "permission exists", "evidenceRef": "PRD.md", "confidence": "high"}],
                "whyDecisionIsNeeded": "Must decide save behavior",
                "options": [
                    {"optionId": "A", "label": "Reject", "userOrBusinessResult": "Reject", "impact": "safe", "reversibility": "reversible"},
                    {"optionId": "B", "label": "Allow", "userOrBusinessResult": "Allow", "impact": "risky", "reversibility": "reversible"}
                ],
                "recommendation": {"optionId": "A", "reason": "safe", "confidence": "high"},
                "owner": "李彧烨",
                "blocking": True,
                "decisionNature": "reversible",
                "status": "confirmed",
                "affectedRequirements": ["FR-001", "AC-001"],
                "researchRecordRefs": [str(prd)],
                "researchVerdict": "FACT_RESOLVED",
                "confirmation": {"confirmedBy": "李彧烨", "confirmedAt": "2026-11-20T00:00:00+08:00", "selectedOptionId": "A", "basis": "explicit"},
                "decisionImpact": {
                    "affectedObjects": [{"objectId": "FR-001", "objectType": "FR", "artifact": str(prd), "evidenceRefs": [str(prd)]}],
                    "expectedInvariant": "No permission means no save.",
                    "conflictingObjects": [],
                    "verificationObjects": [{"objectId": "AC-001", "objectType": "AC", "artifact": str(prd), "evidenceRefs": [str(prd)]}],
                    "evidenceRefs": [str(prd)]
                }
            }]
        }), encoding="utf-8")
        semantic = root / "semantic-model.json"
        semantic.write_text(json.dumps({
            "schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "artifactProfile": "PRD_ONLY",
            "source": {"prdPath": str(prd), "prdSha256": "a" * 64},
            "globalContracts": [], "edges": [], "findings": [], "generatedAt": "2026-11-20T00:00:00+08:00",
            "units": [
                {"unitId": "FR-001", "kind": "FEATURE_SLICE", "title": "Save", "statement": "save", "sourceRef": str(prd), "authority": "PRD", "frIds": ["FR-001"], "acIds": ["AC-001"], "dependencies": [], "sections": {}, "fields": {"priority": "P0"}, "content": "save"},
                {"unitId": "AC-001", "kind": "ACCEPTANCE_CRITERION", "title": "No permission", "statement": "reject", "sourceRef": str(prd), "authority": "PRD", "frIds": ["FR-001"], "acIds": ["AC-001"], "dependencies": ["FR-001"], "sections": {}, "fields": {"WHEN": "no permission", "THEN": "reject"}, "content": "reject"}
            ],
            "metrics": {"globalContracts": 0, "featureSlices": 1, "acceptanceCriteria": 1, "interactionContracts": 0, "journeys": 0, "edges": 0}
        }), encoding="utf-8")
        return prd, context, semantic

    def test_complete_decision_contract_is_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, semantic = self.fixture(root)
            out = root / "contract.json"
            result = run([COMPILE, "--prd", prd, "--decision-context", context, "--semantic-model", semantic, "--workflow-id", "WF-1", "--revision", "r1", "--out", out])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["readiness"], "READY")
            validated = run([VALIDATE, "--contract", out, "--prd", prd, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "readiness.json"])
            self.assertEqual(validated["status"], "PASS")

    def test_open_blocking_decision_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, semantic = self.fixture(root)
            data = json.loads(context.read_text()); data["decisions"][0]["status"] = "open"
            context.write_text(json.dumps(data), encoding="utf-8")
            result = run([COMPILE, "--prd", prd, "--decision-context", context, "--semantic-model", semantic, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "contract.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["readiness"], "BLOCKED")

    def test_closed_decision_without_verification_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, semantic = self.fixture(root)
            data = json.loads(context.read_text()); data["decisions"][0]["decisionImpact"]["verificationObjects"] = []
            context.write_text(json.dumps(data), encoding="utf-8")
            result = run([COMPILE, "--prd", prd, "--decision-context", context, "--semantic-model", semantic, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "contract.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any(item["code"] == "CLOSED_DECISION_HAS_NO_VERIFICATION_OBJECT" for item in json.loads((root / "contract.json").read_text())["findings"]))

    def test_uncovered_semantic_object_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, semantic = self.fixture(root)
            data = json.loads(semantic.read_text())
            data["units"].append({
                "unitId": "FR-002", "kind": "FEATURE_SLICE", "title": "Export", "statement": "export",
                "sourceRef": str(prd), "authority": "PRD", "frIds": ["FR-002"], "acIds": [],
                "dependencies": [], "sections": {}, "fields": {}, "content": "export"
            })
            semantic.write_text(json.dumps(data), encoding="utf-8")
            out = root / "contract.json"
            result = run([COMPILE, "--prd", prd, "--decision-context", context, "--semantic-model", semantic, "--workflow-id", "WF-1", "--revision", "r1", "--out", out], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["readiness"], "BLOCKED")
            contract = json.loads(out.read_text())
            self.assertIn("FR-002", contract["traceability"]["uncoveredP0P1ObjectIds"])
            self.assertTrue(any(item["code"] == "UNDECIDED_P0_P1_OBJECT" for item in contract["findings"]))
            validated = run([VALIDATE, "--contract", out, "--prd", prd, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "readiness.json"], expect=1)
            self.assertTrue(any("FR-002" in item for item in validated["errors"]))

    def test_missing_semantic_model_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, _ = self.fixture(root)
            out = root / "contract.json"
            result = run([COMPILE, "--prd", prd, "--decision-context", context, "--workflow-id", "WF-1", "--revision", "r1", "--out", out], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["readiness"], "BLOCKED")
            contract = json.loads(out.read_text())
            self.assertTrue(any(item["code"] == "SEMANTIC_MODEL_MISSING" for item in contract["findings"]))
            validated = run([VALIDATE, "--contract", out, "--prd", prd, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "readiness.json"], expect=1)
            self.assertIn("semantic model is not bound", validated["errors"])

    def test_prd_hash_drift_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prd, context, semantic = self.fixture(root)
            out = root / "contract.json"
            run([COMPILE, "--prd", prd, "--decision-context", context, "--semantic-model", semantic, "--workflow-id", "WF-1", "--revision", "r1", "--out", out])
            prd.write_text(prd.read_text() + "\nchanged\n", encoding="utf-8")
            result = run([VALIDATE, "--contract", out, "--prd", prd, "--workflow-id", "WF-1", "--revision", "r1", "--out", root / "readiness.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("PRD hash drift", result["errors"])


if __name__ == "__main__":
    unittest.main()
