import hashlib
import json
import os
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
RUN_AUDIT = SCRIPTS / "run_audit_jobs.py"
AUDIT_WORKER = SCRIPTS / "audit_worker.py"
FAKE_AUDIT_WORKER = ROOT / "tests" / "fixtures" / "audit" / "fake_audit_worker.py"
PROFILE = ROOT / "config" / "audit-profiles" / "prd-prototype.json"
AI_PROFILE = ROOT / "config" / "audit-profiles" / "ai-llm.json"
HIGH_RISK_PROFILE = ROOT / "config" / "audit-profiles" / "high-risk.json"
CROSSWALK = ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json"
POLICY_PACK = (ROOT / "core" / "gate-policy-current.json") if (ROOT / "core").exists() else (ROOT / "references" / "gate-policy-current.json")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AuditTrackTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0, env=None):
        process = subprocess.run(
            [sys.executable, str(executable), *map(str, args)],
            text=True, capture_output=True, env={**os.environ, **(env or {})},
        )
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_plan(self, root: Path, profile=PROFILE, crosswalk=CROSSWALK, expect=0, extra_files=None):
        artifact_root = root / "frozen"
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / "artifact.txt").write_text("frozen delivery artifact\n", encoding="utf-8")
        for name, text in (extra_files or {}).items():
            path = artifact_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
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
            "--artifact-root", artifact_root,
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
            data["mappings"] = [item for item in data["mappings"] if item["mappingId"] not in {"R0-ARTIFACT-CLOSURE", "R0-SEMANTIC-CLOSURE"}]
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

    def test_high_risk_profile_passes_dual_executor_crosswalk(self):
        with tempfile.TemporaryDirectory() as td:
            result, _, plan = self.make_plan(Path(td), profile=HIGH_RISK_PROFILE)
            self.assertEqual(result["status"], "READY")
            self.assertEqual(plan["coverage"]["underCoveredRules"], [])
            self.assertEqual(plan["coverage"]["minimumExecutorsPerRule"], 2)

    def test_high_risk_profile_blocks_single_executor_crosswalk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = json.loads(CROSSWALK.read_text())
            data["mappings"] = [item for item in data["mappings"] if not item["mappingId"].endswith("-SEMANTIC") and item["mappingId"] != "U1-INTERACTION-SEMANTIC-DETERMINISTIC"]
            crosswalk = root / "single-executor-crosswalk.json"
            crosswalk.write_text(json.dumps(data), encoding="utf-8")
            result, _, plan = self.make_plan(root, profile=HIGH_RISK_PROFILE, crosswalk=crosswalk, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(plan["coverage"]["underCoveredRules"])
            self.assertTrue(any("below minimum executor coverage" in error for error in plan["errors"]))

    def test_runner_executes_each_job_in_a_unique_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            out_dir = root / ".agents" / "audit" / "results"
            summary = root / ".agents" / "audit" / "audit-summary.json"
            report = root / ".agents" / "audit" / "audit-runner-report.json"
            context_log = root / "contexts.txt"
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", out_dir, "--summary", summary, "--report", report,
                env={"FAKE_AUDIT_CONTEXT_LOG": str(context_log)},
            )
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["auditStatus"], "AUDIT_PASS")
            contexts = context_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(contexts), len(plan["jobs"]))
            self.assertEqual(len(set(contexts)), len(contexts))
            self.assertEqual(json.loads(report.read_text())["status"], "COMPLETE")

    def test_runner_creates_per_job_input_views_from_plan_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root, extra_files={
                "PRD_DELIVERY.md": "# PRD\n\n- FR-001: user configures fields\n- AC-001: fields are saved\n\n## Permissions\n- owner may view\n",
                "prototype-manifest.json": '{"elements":[]}',
                "unrelated-secret.txt": "not needed by semantic jobs",
            })
            out_dir = root / ".agents" / "audit" / "results"
            self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", out_dir, "--summary", root / ".agents" / "audit" / "audit-summary.json",
                "--report", root / ".agents" / "audit" / "audit-runner-report.json",
            )
            jobs_dir = out_dir.parent / "job-inputs"
            for job in plan["jobs"]:
                self.assertIn("inputFiles", job)
                view = jobs_dir / job["jobId"] / "artifacts"
                actual = sorted(path.relative_to(view).as_posix() for path in view.rglob("*") if path.is_file())
                self.assertEqual(actual, sorted(job["inputFiles"]))
                manifest = json.loads((jobs_dir / job["jobId"] / ".audit-context" / "input-manifest.json").read_text())
                self.assertEqual(len(manifest["files"]), len(job["inputFiles"]))
            report = json.loads((root / ".agents" / "audit" / "audit-runner-report.json").read_text())
            self.assertTrue(all(item.get("inputFileCount", 0) >= 1 for item in report["jobs"]))
            self.assertTrue(all(item.get("inputManifestSha256") for item in report["jobs"]))

    def test_runner_blocks_when_context_file_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, _ = self.make_plan(root, extra_files={
                "PRD_DELIVERY.md": "# PRD\n\n- FR-001: user configures fields\n- AC-001: fields are saved\n\n## Permissions\n- owner may view\n",
                "prototype-manifest.json": '{"elements":[]}',
                "extra-a.json": "{}",
                "extra-b.json": "{}",
            })
            audit_dir = root / ".agents" / "audit"
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", audit_dir / "results", "--summary", audit_dir / "audit-summary.json",
                "--report", audit_dir / "audit-runner-report.json",
                "--max-context-files", "1", "--telemetry", audit_dir / "telemetry.json",
                "--escalation-out", audit_dir / "escalation.json", expect=1,
            )
            self.assertEqual(result["status"], "BLOCKED")
            telemetry = json.loads((audit_dir / "telemetry.json").read_text())
            escalation = json.loads((audit_dir / "escalation.json").read_text())
            self.assertEqual(telemetry["status"], "BLOCKED")
            self.assertEqual(escalation["metric"], "maxContextFiles")
            self.assertEqual(escalation["code"], "BUDGET_EXCEEDED")

    def test_runner_stops_after_transcript_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, _ = self.make_plan(root)
            audit_dir = root / ".agents" / "audit"
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", audit_dir / "results", "--summary", audit_dir / "audit-summary.json",
                "--report", audit_dir / "audit-runner-report.json",
                "--max-transcript-bytes", "1", "--telemetry", audit_dir / "telemetry.json",
                "--escalation-out", audit_dir / "escalation.json", expect=1,
            )
            self.assertEqual(result["status"], "BLOCKED")
            telemetry = json.loads((audit_dir / "telemetry.json").read_text())
            escalation = json.loads((audit_dir / "escalation.json").read_text())
            self.assertEqual(escalation["metric"], "maxTranscriptBytes")
            self.assertEqual(len(telemetry["jobs"]), 1)
            self.assertGreater(telemetry["metrics"]["estimatedTokens"], 0)

    def test_runner_blocks_when_worker_mutates_frozen_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, _ = self.make_plan(root)
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", root / ".agents" / "audit" / "results",
                "--summary", root / ".agents" / "audit" / "audit-summary.json",
                "--report", root / ".agents" / "audit" / "audit-runner-report.json",
                expect=1, env={"FAKE_AUDIT_MUTATE": "1"},
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["auditStatus"], "AUDIT_BLOCKED")
            report = json.loads((root / ".agents" / "audit" / "audit-runner-report.json").read_text())
            self.assertTrue(any(item["artifactStable"] is False for item in report["jobs"]))
            self.assertFalse(list((root / ".agents" / "audit" / "results").glob("*.result.json")))

    def test_runner_blocks_on_worker_failure(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, _ = self.make_plan(root)
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", root / ".agents" / "audit" / "results",
                "--report", root / ".agents" / "audit" / "audit-runner-report.json",
                expect=1, env={"FAKE_AUDIT_FAIL": "1"},
            )
            self.assertEqual(result["status"], "BLOCKED")
            report = json.loads((root / ".agents" / "audit" / "audit-runner-report.json").read_text())
            self.assertTrue(any("worker exited with code 7" in (item.get("error") or "") for item in report["jobs"]))

    def test_runner_blocks_if_artifact_changed_after_plan_freeze(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            (Path(plan["artifactRoot"]) / "artifact.txt").write_text("changed after freeze\n", encoding="utf-8")
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", root / ".agents" / "audit" / "results",
                "--report", root / ".agents" / "audit" / "audit-runner-report.json",
                expect=1,
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("artifact snapshot changed" in (item.get("error") or "") for item in json.loads((root / ".agents" / "audit" / "audit-runner-report.json").read_text())["jobs"]))

    def test_runner_blocks_when_a_job_returns_a_blocking_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, _ = self.make_plan(root)
            result = self.run_tool(
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", root / ".agents" / "audit" / "results",
                "--summary", root / ".agents" / "audit" / "audit-summary.json",
                "--report", root / ".agents" / "audit" / "audit-runner-report.json",
                expect=1, env={"FAKE_AUDIT_BLOCKING": "1"},
            )
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["auditStatus"], "AUDIT_BLOCKED")
            summary = json.loads((root / ".agents" / "audit" / "audit-summary.json").read_text())
            self.assertGreater(summary["blockingFindingCount"], 0)

    def test_runner_resume_reuses_results_bound_to_the_same_plan(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, plan_path, plan = self.make_plan(root)
            out_dir = root / ".agents" / "audit" / "results"
            summary = root / ".agents" / "audit" / "audit-summary.json"
            report = root / ".agents" / "audit" / "audit-runner-report.json"
            context_log = root / "contexts.txt"
            common = [
                RUN_AUDIT, "--run-root", root, "--plan", plan_path,
                "--worker", sys.executable, FAKE_AUDIT_WORKER,
                "--out-dir", out_dir, "--summary", summary, "--report", report,
            ]
            self.run_tool(*common, env={"FAKE_AUDIT_CONTEXT_LOG": str(context_log)})
            first_contexts = context_log.read_text(encoding="utf-8").splitlines()
            resumed = self.run_tool(*common, "--resume", env={"FAKE_AUDIT_CONTEXT_LOG": str(context_log)})
            self.assertEqual(resumed["auditStatus"], "AUDIT_PASS")
            self.assertEqual(context_log.read_text(encoding="utf-8").splitlines(), first_contexts)
            self.assertEqual(len(first_contexts), len(plan["jobs"]))

    def test_codex_audit_worker_refuses_to_simulate_a_human_job(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job_path = root / "job.json"
            job_path.write_text(json.dumps({
                "schemaVersion": 1,
                "auditRunId": "run-human",
                "executorContextId": "ctx-human",
                "workflowId": "WF-AUDIT",
                "revision": "r1",
                "auditPlanPath": str(root / "plan.json"),
                "auditPlanSha256": "a" * 64,
                "artifactRoot": str(root),
                "policyLockPath": str(root / "policy-lock.json"),
                "policyLockSha256": "b" * 64,
                "job": {
                    "jobId": "AUD-HUMAN", "jobType": "RULE_AUDIT", "sourcePolicyRuleIds": ["G1.DECISION_READINESS"],
                    "sourceSkillId": "delivery-core", "sourceSkillCheckIds": ["G1.DECISION_CONTEXT"],
                    "executorType": "HUMAN", "owner": "product-owner", "requiredEvidence": ["decision"],
                    "passCondition": "product owner confirms the decision",
                },
            }), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(AUDIT_WORKER), "--job", str(job_path), "--out", str(root / "result.json")],
                text=True, capture_output=True, env={**os.environ, "AI_NATIVE_RUN_ROOT": str(root)},
            )
            self.assertEqual(process.returncode, 6, process.stdout + process.stderr)
            self.assertIn("HUMAN audit jobs require a real human result", process.stderr)

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
