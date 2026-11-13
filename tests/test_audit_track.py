import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
DATA = ROOT / ("references" if ROOT.name == "ai-native-delivery" else "")
POLICY_LOCK = SCRIPTS / "build_policy_lock.py"
BUILD_AUDIT = SCRIPTS / "build_audit_plan.py"
VALIDATE_AUDIT = SCRIPTS / "validate_audit_results.py"
PROFILE = ROOT / "config" / "audit-profiles" / "prd-prototype.json"
AI_PROFILE = ROOT / "config" / "audit-profiles" / "ai-llm.json"
HIGH_RISK_PROFILE = ROOT / "config" / "audit-profiles" / "high-risk.json"
CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"
POLICY_PACK = (ROOT / "core" / "gate-policy-current.json") if (ROOT / "core").exists() else (ROOT / "references" / "gate-policy-current.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuditTrackTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_plan(self, root: Path, profile=PROFILE, crosswalk=CROSSWALK, expect=0):
        lock = root / "policy-lock.json"
        self.run_tool(
            POLICY_LOCK,
            "--policy-pack", POLICY_PACK,
            "--artifact-profile", "PRD_PLUS_PROTOTYPE",
            "--requirement-types", "CRUD,UI_INTERACTION",
            "--prototype-status", "TRIGGERED",
            "--ui-ownership", "LOCAL",
            "--out", lock,
        )
        plan_path = root / "audit-plan.json"
        result = self.run_tool(
            BUILD_AUDIT,
            "--policy-lock", lock,
            "--profile", profile,
            "--crosswalk", crosswalk,
            "--workflow-id", "WF-AUDIT",
            "--revision", "r1",
            "--out", plan_path,
            expect=expect,
        )
        return result, plan_path, json.loads(plan_path.read_text())

    def make_results(self, root: Path, plan_path: Path, plan, mutate=None):
        results = root / "audit-results"
        results.mkdir()
        plan_hash = sha(plan_path)
        for job in plan["jobs"]:
            bound_rules = list(job["sourcePolicyRuleIds"])
            checks = [
                {
                    "checkId": f"{job['jobId']}-{rule_id}",
                    "status": "passed",
                    "evidenceRefs": [f"evidence://{rule_id}"],
                    "observed": "independently checked",
                    "expected": "rule passes",
                    "policyRuleIds": [rule_id],
                }
                for rule_id in bound_rules
            ]
            if not checks:
                checks = [{
                    "checkId": job["jobId"],
                    "status": "passed",
                    "evidenceRefs": ["evidence://global-review"],
                    "observed": "cross-rule result is coherent",
                    "expected": "global review passes",
                    "policyRuleIds": [],
                }]
            result = {
                "schemaVersion": 1,
                "auditRunId": f"run-{job['jobId']}",
                "jobId": job["jobId"],
                "auditPlanSha256": plan_hash,
                "workflowId": "WF-AUDIT",
                "revision": "r1",
                "policyLockSha256": plan["policyLockSha256"],
                "executorType": job["executorType"],
                "executorId": "fixture-auditor",
                "executorContextId": f"ctx-{job['jobId']}",
                "independentContext": True,
                "status": "PASS",
                "checks": checks,
                "findings": [],
                "checkedAt": "2026-11-13T00:00:00Z",
                "executorTranscript": "independent fixture transcript",
            }
            if mutate:
                mutate(job, result)
            (results / f"{job['jobId']}.result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return results

    def test_plan_covers_every_applicable_rule_and_global_review(self):
        with tempfile.TemporaryDirectory() as td:
            result, _, plan = self.make_plan(Path(td))
            self.assertEqual(result["status"], "READY")
            self.assertEqual(plan["coverage"]["uncoveredRules"], [])
            self.assertEqual(plan["coverage"]["mappedRules"], plan["coverage"]["expectedRules"])
            self.assertIn("EDGE_REVIEW", {job["jobType"] for job in plan["jobs"]})
            self.assertIn("GLOBAL_INTEGRATION_REVIEW", {job["jobType"] for job in plan["jobs"]})

    def test_unmapped_rule_blocks_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = json.loads(CROSSWALK.read_text())
            data["mappings"] = [item for item in data["mappings"] if item["mappingId"] != "R0-ARTIFACT-CLOSURE"]
            crosswalk = root / "crosswalk.json"
            crosswalk.write_text(json.dumps(data), encoding="utf-8")
            result, _, plan = self.make_plan(root, crosswalk=crosswalk, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("R0.ARTIFACT_SET", plan["coverage"]["uncoveredRules"])

    def test_focused_profile_rejects_a_lock_without_its_conditional_rule(self):
        with tempfile.TemporaryDirectory() as td:
            result, _, plan = self.make_plan(Path(td), profile=AI_PROFILE, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("G1.COND.AI_LLM" in error for error in plan["errors"]))

    def test_high_risk_profile_blocks_single_executor_crosswalk(self):
        with tempfile.TemporaryDirectory() as td:
            result, _, plan = self.make_plan(Path(td), profile=HIGH_RISK_PROFILE, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(plan["coverage"]["underCoveredRules"])
            self.assertTrue(any("below minimum executor coverage" in error for error in plan["errors"]))

    def test_complete_independent_results_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            results = self.make_results(root, plan_path, plan)
            out = root / "audit-summary.json"
            result = self.run_tool(VALIDATE_AUDIT, "--plan", plan_path, "--results-dir", results, "--out", out)
            self.assertEqual(result["status"], "AUDIT_PASS")
            summary = json.loads(out.read_text())
            self.assertEqual(summary["coveredRules"], summary["expectedRules"])
            self.assertEqual(summary["blockingFindingCount"], 0)

    def test_missing_result_blocks_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            results = self.make_results(root, plan_path, plan)
            next(results.glob("*.json")).unlink()
            out = root / "audit-summary.json"
            self.run_tool(VALIDATE_AUDIT, "--plan", plan_path, "--results-dir", results, "--out", out, expect=1)
            summary = json.loads(out.read_text())
            self.assertEqual(summary["status"], "AUDIT_BLOCKED")
            self.assertTrue(summary["missingJobs"])

    def test_rule_omitted_from_job_checks_blocks_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            target = next(job for job in plan["jobs"] if len(job["sourcePolicyRuleIds"]) > 1)
            def mutate(job, result):
                if job["jobId"] == target["jobId"]:
                    result["checks"] = result["checks"][:-1]
            results = self.make_results(root, plan_path, plan, mutate=mutate)
            out = root / "audit-summary.json"
            self.run_tool(VALIDATE_AUDIT, "--plan", plan_path, "--results-dir", results, "--out", out, expect=1)
            summary = json.loads(out.read_text())
            self.assertIn(target["jobId"], summary["failedJobs"])
            self.assertTrue(summary["missingRules"])

    def test_plan_hash_mismatch_blocks_audit(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            target = plan["jobs"][0]["jobId"]
            def mutate(job, result):
                if job["jobId"] == target:
                    result["auditPlanSha256"] = "f" * 64
            results = self.make_results(root, plan_path, plan, mutate=mutate)
            out = root / "audit-summary.json"
            self.run_tool(VALIDATE_AUDIT, "--plan", plan_path, "--results-dir", results, "--out", out, expect=1)
            summary = json.loads(out.read_text())
            self.assertTrue(any("auditPlanSha256" in error for error in summary["errors"]))

    def test_blocking_finding_blocks_otherwise_complete_job(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            target = next(job for job in plan["jobs"] if job["sourcePolicyRuleIds"])
            def mutate(job, result):
                if job["jobId"] == target["jobId"]:
                    result["findings"] = [{
                        "findingId": "F-BLOCK",
                        "severity": "BLOCKING",
                        "title": "Rule is not semantically closed",
                        "policyRuleIds": [target["sourcePolicyRuleIds"][0]],
                        "evidenceRefs": ["evidence://finding"],
                        "impact": "Downstream design would invent behavior.",
                        "closeCondition": "Update the PRD and rerun the full audit.",
                        "owner": "prd-producer",
                    }]
            results = self.make_results(root, plan_path, plan, mutate=mutate)
            out = root / "audit-summary.json"
            self.run_tool(VALIDATE_AUDIT, "--plan", plan_path, "--results-dir", results, "--out", out, expect=1)
            summary = json.loads(out.read_text())
            self.assertEqual(summary["blockingFindingCount"], 1)
            self.assertIn(target["jobId"], summary["failedJobs"])


if __name__ == "__main__":
    unittest.main()
