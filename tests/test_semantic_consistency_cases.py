import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "semantic_consistency_review.py"
VALIDATOR = ROOT / SCRIPTS / "validate_agent_contracts.py"
COVERAGE = ROOT / SCRIPTS / "build_semantic_coverage.py"
BASE = ROOT / "examples" / "semantic-review" / "accepted.json"


class SemanticConsistencyCases(unittest.TestCase):
    def run_review(self, manifest, root, expect=1):
        path = root / "input.json"
        out = root / "review.json"
        log = root / "review.log"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(TOOL), "--input", str(path), "--out", str(out), "--transcript", str(log)],
            text=True,
            capture_output=True,
        )
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        data = json.loads(out.read_text(encoding="utf-8"))
        validation = subprocess.run(
            [sys.executable, str(VALIDATOR), str(out), "--json"],
            text=True,
            capture_output=True,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        return data

    def base(self):
        data = json.loads(BASE.read_text(encoding="utf-8"))
        for artifact in data["artifacts"]:
            path = (BASE.parent / artifact["path"]).resolve()
            artifact["path"] = str(path)
            artifact["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return data

    def test_all_six_semantic_axes_accept_grounded_case(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.run_review(self.base(), Path(td), expect=0)
            self.assertEqual(data["verdict"], "ACCEPTED")
            self.assertEqual({c["checkId"] for c in data["checks"]}, {
                "SEMANTIC.TERMINOLOGY", "SEMANTIC.CAPABILITY", "SEMANTIC.STATE",
                "SEMANTIC.PERMISSION", "SEMANTIC.AUTHORITY_SYNC", "SEMANTIC.PROVENANCE",
            })

    def test_terminology_conflict_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["terminologyClaims"][0]["grounding"] = "CONFLICT"
            review = self.run_review(data, Path(td))
            self.assertIn("SEM-TERM-01", {f["findingId"] for f in review["findings"]})
            self.assertEqual(review["checks"][0]["status"], "failed")

    def test_existing_capability_misclassification_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["capabilityClaims"][0]["verificationStatus"] = "VERIFIED_NEW"
            review = self.run_review(data, Path(td))
            self.assertIn("SEM-CAP-01", {f["findingId"] for f in review["findings"]})

    def test_state_hidden_precondition_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["stateAssumptions"][0]["preconditionDefined"] = False
            review = self.run_review(data, Path(td))
            self.assertIn("SEM-STATE-01", {f["findingId"] for f in review["findings"]})

    def test_permission_boundary_conflict_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["permissionEdges"].append({
                "edgeId": "P-3", "role": "task-owner", "action": "enable",
                "resource": "scene-intent", "decision": "DENIED", "evidenceRefs": ["prd.md#FR-002"],
            })
            review = self.run_review(data, Path(td))
            self.assertIn("SEM-PERM-CONFLICT-01", {f["findingId"] for f in review["findings"]})

    def test_prd_prototype_authority_conflict_requires_resync(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["crossArtifactClaims"][0]["status"] = "CONFLICT"
            data["crossArtifactClaims"][0]["interactionValue"] = "button visible to everyone"
            review = self.run_review(data, Path(td))
            finding = next(f for f in review["findings"] if f["findingId"] == "SEM-AUTH-01")
            self.assertEqual(finding["rootCauseId"], "SEMANTIC.AUTHORITY.RESYNC_REQUIRED")

    def test_unsourced_business_assertion_is_blocking(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["businessAssertions"][0]["sourceType"] = "INFERENCE"
            data["businessAssertions"][0]["evidenceRefs"] = []
            review = self.run_review(data, Path(td))
            self.assertIn("SEM-SOURCE-01", {f["findingId"] for f in review["findings"]})

    def test_missing_axis_is_incomplete_not_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["permissionEdges"] = []
            review = self.run_review(data, Path(td))
            self.assertEqual(review["verdict"], "INCOMPLETE")
            permission = next(c for c in review["checks"] if c["checkId"] == "SEMANTIC.PERMISSION")
            self.assertEqual(permission["status"], "not_executed")
            self.assertIn("SEM-MISSING-PERMISSION", {f["findingId"] for f in review["findings"]})


class SemanticCoverageTests(unittest.TestCase):
    def coverage(self, data, root):
        source = root / "input.json"
        out = root / "coverage.json"
        source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([
            sys.executable, str(COVERAGE), "--semantic-input", str(source),
            "--prd", str(ROOT / "examples" / "semantic-review" / "prd.md"),
            "--prototype", str(ROOT / "examples" / "semantic-review" / "prototype.html"),
            "--out", str(out),
        ], text=True, capture_output=True)
        return proc, json.loads(out.read_text()) if out.exists() else {}

    def test_uncovered_prd_identifier_blocks_semantic_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = json.loads(BASE.read_text())
            data["businessAssertions"][0]["coveredIds"] = ["FR-001"]
            proc, coverage = self.coverage(data, root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("AC:AC-001", coverage["missing"])

    def test_unrepresented_ui_element_blocks_semantic_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = json.loads(BASE.read_text())
            data["interactionElements"] = []
            proc, coverage = self.coverage(data, root)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("UI:scene-intent-button", coverage["missing"])


class SemanticEvidenceBuilderTests(unittest.TestCase):
    def test_space_separated_bindings_and_manifest_states_are_preserved(self):
        import importlib.util
        tool = ROOT / SCRIPTS / "build_semantic_evidence.py"
        spec = importlib.util.spec_from_file_location("build_semantic_evidence", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "prd.md"
            proto = root / "prototype.html"
            manifest = root / "manifest.json"
            out = root / "semantic.json"
            prd.write_text("# PRD\n\n- FR-001: Submit\n- AC-001: Accepted\n- AC-002: Rejected\n- 筛选后展示筛选结果\n- 无数据时显示当前数据为空\n", encoding="utf-8")
            proto.write_text('<div data-ai-id="UI-1" data-ai-fr="FR-001" data-ai-ac="AC-001 AC-002">Submit</div>', encoding="utf-8")
            manifest.write_text(json.dumps({"elements": [{"uiElementId": "UI-1", "frIds": ["FR-001"], "acIds": ["AC-001", "AC-002"], "states": ["default", "empty", "filtered"], "permissions": []}]}), encoding="utf-8")
            result = mod.build(prd, proto, manifest, None, "WF", "r1", "prd-producer")
            out.write_text(json.dumps(result), encoding="utf-8")
            self.assertEqual(result["interactionElements"][0]["acIds"], ["AC-001", "AC-002"])
            self.assertEqual({item["stateId"] for item in result["stateAssumptions"]}, {"default", "empty", "filtered"})
            state_map = {item["stateId"]: item for item in result["stateAssumptions"]}
            self.assertTrue(state_map["empty"]["preconditionDefined"])
            self.assertTrue(state_map["filtered"]["preconditionDefined"])


class QualityExitSemanticGateTests(unittest.TestCase):
    def test_capability_context_without_semantic_review_blocks_quality_exit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            context = root / ".agents" / "context"
            context.mkdir(parents=True)
            (context / "capability-context.json").write_text(json.dumps({
                "schemaVersion": 1, "capabilityId": "scene-intent", "canonicalName": "场景意图",
                "status": "EXISTING", "sourceRefs": ["history://scene-intent"], "confidence": "HIGH",
                "decisionStatus": "CONFIRMED", "verificationStatus": "VERIFIED_EXISTING",
                "verificationEvidenceRefs": ["git://demo"], "verificationMethod": "GIT_HISTORY",
            }), encoding="utf-8")
            decision = root / "decision-result.json"
            decision.write_text(json.dumps({"readiness": "READY", "decision": "PROCEED"}), encoding="utf-8")
            review = root / "delivery-review.json"
            review.write_text(json.dumps({"verdict": "ACCEPTED", "blockingCount": 0, "checks": [], "findings": []}), encoding="utf-8")
            plan = root / "plan.json"
            plan.write_text(json.dumps({"tasks": [
                {"taskId": "DECISION-READINESS", "status": "SUCCEEDED", "resultPath": str(decision)},
                {"taskId": "DELIVERY-REVIEW", "kind": "reviewer", "role": "delivery-reviewer", "status": "SUCCEEDED", "resultPath": str(review)},
            ]}), encoding="utf-8")
            out = root / "quality.json"
            quality_exit = ROOT / SCRIPTS / "delivery_quality_exit.py"
            proc = subprocess.run([sys.executable, str(quality_exit), "--run-root", str(root), "--plan", str(plan), "--out", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            gate = next(c for c in data["checks"] if c["checkId"] == "QUALITY.SEMANTIC_REVIEW")
            self.assertEqual(gate["status"], "failed")


if __name__ == "__main__":
    unittest.main()
