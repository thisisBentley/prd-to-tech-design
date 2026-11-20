import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
COMPILE = TOOLS / "compile_change_sets.py"
VALIDATE = TOOLS / "validate_change_sets.py"
PLAN = TOOLS / "plan_repairs.py"
POLICY = ROOT / "config" / "trust-kernel" / "change-set-policy-v1.json"


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


def finding(fid, root, cls, *, severity="BLOCKING", artifact="PRD_DELIVERY.md"):
    data = {
        "findingId": fid,
        "rootCauseId": root,
        "classification": cls,
        "severity": severity,
        "title": f"{cls} finding",
        "summary": f"{cls} summary",
        "evidenceRefs": [f"evidence/{fid}.json"],
        "closeCondition": f"Close {fid}",
        "expectedInvariant": f"invariant for {fid}",
        "owner": "producer",
    }
    if artifact:
        data["affectedArtifacts"] = [{"path": artifact, "artifactType": "PRD", "reason": "affected by finding"}]
    return data


class ChangeSetTests(unittest.TestCase):
    def review(self, root, findings, revision="r1"):
        path = root / f"review-{revision}.json"
        path.write_text(json.dumps({
            "schemaVersion": 1,
            "workflowId": "WF-CHANGE-1",
            "targetRevision": revision,
            "findings": findings,
        }), encoding="utf-8")
        return path

    def compile(self, root, review, expect=0):
        out = root / "change-sets.json"
        result = run([COMPILE, "--review", review, "--policy", POLICY, "--out", out], expect=expect)
        return result, out

    def test_groups_same_root_cause_into_one_change_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [
                finding("F-1", "ROOT-1", "SPEC_MISSING"),
                finding("F-2", "ROOT-1", "SPEC_MISSING"),
            ])
            result, out = self.compile(root, review)
            self.assertEqual(result["status"], "READY_FOR_REPAIR")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(len(batch["changeSets"]), 1)
            self.assertEqual(batch["changeSets"][0]["findingIds"], ["F-1", "F-2"])
            self.assertEqual(batch["changeSets"][0]["classification"], "SPEC_MISSING")
            self.assertEqual(batch["changeSets"][0]["repairTrack"], "BUSINESS_REVISION")
            self.assertTrue(batch["changeSets"][0]["businessRevisionRequired"])
            self.assertEqual(len(batch["changeSets"][0]["affectedArtifacts"]), 1)
            self.assertGreaterEqual(len(batch["changeSets"][0]["verificationPlan"]), 2)

    def test_all_classifications_route_to_expected_tracks(self):
        cases = {
            "DECISION_GAP": ("BUSINESS_REVISION", True),
            "SOURCE_CONFLICT": ("BUSINESS_REVISION", True),
            "SPEC_MISSING": ("BUSINESS_REVISION", True),
            "ARTIFACT_DRIFT": ("ARTIFACT_SYNC", False),
            "IMPLEMENTATION_RISK": ("TECH_SOLUTION", False),
            "TEST_GAP": ("TEST_PLAN", False),
            "EDITORIAL": ("MECHANICAL_REPAIR", False),
            "MECHANICAL": ("MECHANICAL_REPAIR", False),
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [finding(f"F-{index}", f"ROOT-{index}", cls) for index, cls in enumerate(cases)])
            result, out = self.compile(root, review)
            self.assertEqual(result["status"], "READY_FOR_REPAIR")
            batch = json.loads(out.read_text(encoding="utf-8"))
            actual = {item["classification"]: (item["repairTrack"], item["businessRevisionRequired"]) for item in batch["changeSets"]}
            self.assertEqual(actual, cases)
            run([VALIDATE, "--batch", out, "--policy", POLICY, "--review", review, "--out", root / "validation.json"])

    def test_missing_root_cause_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            item = finding("F-1", "ROOT-1", "SPEC_MISSING")
            item.pop("rootCauseId")
            review = self.review(root, [item])
            result, out = self.compile(root, review, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "ROOT_CAUSE_MISSING" for item in batch["findings"]))
            self.assertEqual(batch["changeSets"], [])

    def test_missing_affected_artifact_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [finding("F-1", "ROOT-1", "ARTIFACT_DRIFT", artifact=None)])
            result, out = self.compile(root, review, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "AFFECTED_ARTIFACT_MISSING" for item in batch["findings"]))

    def test_conflicting_classes_under_same_root_cause_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [
                finding("F-1", "ROOT-1", "SPEC_MISSING"),
                finding("F-2", "ROOT-1", "MECHANICAL"),
            ])
            result, out = self.compile(root, review, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "ROOT_CAUSE_CLASSIFICATION_CONFLICT" for item in batch["findings"]))

    def test_budget_exceeded_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [
                finding(f"F-{index}", "ROOT-1", "MECHANICAL", artifact=f"artifact-{index}.json")
                for index in range(7)
            ])
            result, out = self.compile(root, review, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "BUDGET_AFFECTED_ARTIFACTS_EXCEEDED" for item in batch["findings"]))

    def test_no_blocking_findings_means_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [finding("F-1", "ROOT-1", "MECHANICAL", severity="NON_BLOCKING")])
            result, out = self.compile(root, review)
            self.assertEqual(result["status"], "NO_CHANGES")
            batch = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(batch["changeSets"], [])
            validation = run([VALIDATE, "--batch", out, "--policy", POLICY, "--review", review, "--out", root / "validation.json"])
            self.assertEqual(validation["status"], "PASS")

    def test_plan_repairs_requires_change_set_batch(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            legacy = root / "legacy.json"
            legacy.write_text(json.dumps({
                "status": "READY_FOR_REPAIR", "workflowId": "WF-1", "targetRevision": "r1",
                "groups": [{"rootCauseId": "R-1", "repairClass": "SEMANTIC", "closeConditions": ["fix"]}],
            }), encoding="utf-8")
            result = run([PLAN, "--change-set-batch", legacy, "--out", root / "plan.json"], expect=1)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertTrue(any("legacy repair batches" in item for item in result["errors"]))

    def test_plan_repairs_preserves_change_set_budget_and_verification(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [finding("F-1", "ROOT-1", "ARTIFACT_DRIFT")])
            _, batch_path = self.compile(root, review)
            result = run([PLAN, "--change-set-batch", batch_path, "--out", root / "plan.json"])
            self.assertEqual(result["status"], "READY")
            plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
            task = plan["tasks"][0]
            self.assertEqual(task["classification"], "ARTIFACT_DRIFT")
            self.assertFalse(task["businessRevisionRequired"])
            self.assertEqual(task["role"], "projection-repair-agent")
            self.assertTrue(task["verificationPlan"])
            self.assertIn("maxAffectedArtifacts", task["budget"])

    def test_validator_detects_omitted_blocking_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            review = self.review(root, [finding("F-1", "ROOT-1", "SPEC_MISSING"), finding("F-2", "ROOT-2", "MECHANICAL")])
            _, batch_path = self.compile(root, review)
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            batch["changeSets"] = batch["changeSets"][:1]
            batch_path.write_text(json.dumps(batch), encoding="utf-8")
            result = run([VALIDATE, "--batch", batch_path, "--policy", POLICY, "--review", review, "--out", root / "validation.json"], expect=1)
            self.assertTrue(any("not covered" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
