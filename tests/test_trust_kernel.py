import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
CLASSIFY = TOOLS / "classify_execution_mode.py"
TARGET = TOOLS / "validate_target_binding.py"
EXTERNAL = TOOLS / "normalize_external_gate.py"
ROUTE = TOOLS / "route_specialist_tool.py"
RUN_KERNEL = TOOLS / "run_trust_kernel.py"
CASE_FAMILY = TOOLS / "build_real_case_family.py"
MODE_POLICY = ROOT / "config" / "trust-kernel" / "execution-mode-policy-v1.json"
TOOL_POLICY = ROOT / "config" / "trust-kernel" / "specialist-tool-routes-v1.json"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class TrustKernelTests(unittest.TestCase):
    def task_request(self, root, **overrides):
        data = {
            "schemaVersion": 1,
            "workflowId": "WF-1",
            "taskId": "TASK-1",
            "title": "Local revision",
            "objective": "Fix external gate findings",
            "changeRequested": True,
            "existingArtifactAvailable": True,
            "externalFindings": ["F-1"],
            "localChangeScopes": ["METADATA", "AUDIT_CONTRACT"],
            "structuralChanges": {
                "newPage": False,
                "newRole": False,
                "newStateMachine": False,
                "newExternalBoundary": False,
                "newCoreEntity": False,
            },
            "openBlockingDecisions": 0,
            "unknownSignals": [],
            "evidenceRefs": ["review.json"],
        }
        data.update(overrides)
        path = root / "task.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def artifacts(self, root, issue_key="BOT-41040", owner="李彧烨", url="https://jira.example/browse/BOT-41040"):
        prd = root / "PRD_DELIVERY.md"
        overview = root / "Overview.html"
        prd.write_text(
            "# PRD\n\n"
            f"- Requirement ID: `{issue_key}`\n"
            f"- Issue Key: `{issue_key}`\n"
            f"- Issue URL: {url}\n"
            f"- Owner: {owner}\n"
            "- 当前 PRD 版本: `v1.1`\n"
            f"- Source baseline: Jira `{issue_key}`\n",
            encoding="utf-8",
        )
        overview.write_text(
            "<html><head>"
            f'<meta name="issue-key" content="{issue_key}">'
            f'<meta name="issue-url" content="{url}">'
            f'<meta name="owner" content="{owner}">'
            '<meta name="source-prd-version" content="v1.1">'
            "</head><body>Overview</body></html>",
            encoding="utf-8",
        )
        return prd, overview

    def binding_request(self, root, prd, overview, **target_overrides):
        target = {"jiraKey": "BOT-41040", "jiraUrl": "https://jira.example/browse/BOT-41040", "owner": "李彧烨"}
        target.update(target_overrides)
        data = {
            "schemaVersion": 1,
            "workflowId": "WF-1",
            "target": target,
            "artifacts": [
                {"type": "PRD", "path": str(prd), "expectedVersion": "v1.1"},
                {"type": "OVERVIEW", "path": str(overview), "expectedVersion": "v1.1"},
            ],
            "allowedLineageIssueKeys": ["ZY20260067-1017"],
        }
        path = root / "binding.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_classification_selects_targeted_revision_and_gitlab_tool(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.task_request(root)
            result = run([CLASSIFY, "--request", task, "--policy", MODE_POLICY, "--out", root / "decision.json"])
            self.assertEqual(result["mode"], "TARGETED_REVISION")
            self.assertEqual(result["status"], "CLASSIFIED")
            route = run([ROUTE, "--workflow-id", "WF-1", "--execution-mode", "TARGETED_REVISION", "--intent", "PRD_LOCAL_REVISION", "--policy", TOOL_POLICY, "--out", root / "route.json"])
            self.assertEqual(route["status"], "ROUTED")
            self.assertEqual(route["selectedTool"]["toolId"], "gitlab-prd-tool")

    def test_structural_change_forces_full_delivery_and_not_gitlab_local_tool(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.task_request(root, structuralChanges={"newPage": True, "newRole": False, "newStateMachine": False, "newExternalBoundary": False, "newCoreEntity": False})
            result = run([CLASSIFY, "--request", task, "--policy", MODE_POLICY, "--out", root / "decision.json"])
            self.assertEqual(result["mode"], "FULL_DELIVERY")
            run([ROUTE, "--workflow-id", "WF-1", "--execution-mode", "FULL_DELIVERY", "--intent", "PRD_LOCAL_REVISION", "--policy", TOOL_POLICY, "--out", root / "route.json"], expect=1)

    def test_open_decision_escalates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.task_request(root, openBlockingDecisions=1)
            result = run([CLASSIFY, "--request", task, "--policy", MODE_POLICY, "--out", root / "decision.json"], expect=1)
            self.assertEqual(result["mode"], "ESCALATE")

    def test_target_binding_passes_for_current_jira_identity(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            request = self.binding_request(root, prd, overview)
            result = run([TARGET, "--request", request, "--out", root / "target.json"])
            self.assertEqual(result["status"], "PASS")

    def test_target_binding_blocks_stale_old_issue_even_if_declared_as_lineage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root, issue_key="ZY20260067-1017", owner="产品负责人（角色）", url="https://jira.example/browse/ZY20260067-1017")
            request = self.binding_request(root, prd, overview)
            result = run([TARGET, "--request", request, "--out", root / "target.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any(item["checkId"] == "TARGET.PRD.ISSUE_KEY" for item in result["failedChecks"]))

    def external_input(self, root, prd, overview, raw_result="PASS", findings=None):
        data = {
            "schemaVersion": 1,
            "workflowId": "WF-1",
            "candidateRevision": "r1",
            "jiraKey": "BOT-41040",
            "gateType": "COMPOSITE",
            "rawResult": raw_result,
            "findings": findings or [],
            "tool": {"toolId": "gitlab-prd-tool", "version": "V2.3.0", "sourceCommit": "e4f0118"},
            "candidateArtifacts": [
                {"path": str(prd), "sha256": hashlib.sha256(prd.read_bytes()).hexdigest()},
                {"path": str(overview), "sha256": hashlib.sha256(overview.read_bytes()).hexdigest()},
            ],
            "evidenceRefs": ["gate.log"],
            "checkedAt": "2026-11-20T00:00:00+08:00",
        }
        path = root / "external.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_external_pass_closes_only_with_valid_target_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            target = run([TARGET, "--request", self.binding_request(root, prd, overview), "--out", root / "target.json"])
            external = self.external_input(root, prd, overview)
            result = run([EXTERNAL, "--input", external, "--target-binding", root / "target.json", "--out", root / "verdict.json"])
            self.assertEqual(result["verdict"], "PASS")
            self.assertEqual(result["releaseState"], "CLOSED")
            self.assertTrue(result["closureEligible"])

    def test_internal_pass_with_blocking_finding_is_not_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            run([TARGET, "--request", self.binding_request(root, prd, overview), "--out", root / "target.json"])
            external = self.external_input(root, prd, overview, raw_result="PASS", findings=[{"findingId": "F-1", "severity": "BLOCKING", "summary": "missing audit matrix"}])
            result = run([EXTERNAL, "--input", external, "--target-binding", root / "target.json", "--out", root / "verdict.json"], expect=1)
            self.assertEqual(result["verdict"], "NEEDS_FIX")
            self.assertEqual(result["releaseState"], "EXTERNAL_GATE_FAILED")
            self.assertFalse(result["closureEligible"])

    def test_external_environment_failure_never_degrades_to_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            run([TARGET, "--request", self.binding_request(root, prd, overview), "--out", root / "target.json"])
            external = self.external_input(root, prd, overview, raw_result="ENVIRONMENT_BLOCKED")
            result = run([EXTERNAL, "--input", external, "--target-binding", root / "target.json", "--out", root / "verdict.json"], expect=1)
            self.assertEqual(result["verdict"], "ENVIRONMENT_BLOCKED")
            self.assertEqual(result["releaseState"], "ENVIRONMENT_BLOCKED")

    def test_trust_kernel_runs_targeted_revision_end_to_end(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            task = self.task_request(root)
            binding = self.binding_request(root, prd, overview)
            result = run([
                RUN_KERNEL,
                "--task-request", task,
                "--execution-mode-policy", MODE_POLICY,
                "--tool-policy", TOOL_POLICY,
                "--intent", "PRD_LOCAL_REVISION",
                "--target-binding-request", binding,
                "--out", root / "run.json",
            ])
            self.assertEqual(result["status"], "READY")
            self.assertEqual(result["mode"], "TARGETED_REVISION")
            self.assertEqual(result["toolId"], "gitlab-prd-tool")
            self.assertEqual(result["targetBinding"], "PASS")

    def test_trust_kernel_blocks_targeted_revision_with_stale_target(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root, issue_key="ZY20260067-1017", owner="产品负责人（角色）", url="https://jira.example/browse/ZY20260067-1017")
            task = self.task_request(root)
            binding = self.binding_request(root, prd, overview)
            result = run([
                RUN_KERNEL,
                "--task-request", task,
                "--execution-mode-policy", MODE_POLICY,
                "--tool-policy", TOOL_POLICY,
                "--intent", "PRD_LOCAL_REVISION",
                "--target-binding-request", binding,
                "--out", root / "run.json",
            ], expect=1)
            self.assertEqual(result["status"], "BLOCKED")

    def test_real_case_family_requires_failure_and_external_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd, overview = self.artifacts(root)
            task = self.task_request(root)
            binding = self.binding_request(root, prd, overview)
            run_kernel = run([
                RUN_KERNEL,
                "--task-request", task,
                "--execution-mode-policy", MODE_POLICY,
                "--tool-policy", TOOL_POLICY,
                "--intent", "PRD_LOCAL_REVISION",
                "--target-binding-request", binding,
                "--out", root / "run.json",
            ])
            self.assertEqual(run_kernel["status"], "READY")
            target = run([TARGET, "--request", binding, "--out", root / "target.json"])
            external = self.external_input(root, prd, overview)
            run([EXTERNAL, "--input", external, "--target-binding", root / "target.json", "--out", root / "verdict.json"])
            input_data = {
                "caseId": "CASE-1",
                "workflowId": "WF-1",
                "businessCase": "AB case",
                "attempts": [
                    {"attemptId": "A", "submissionId": "OLD", "role": "FAILURE_BASELINE", "trustKernelRunPath": "run.json", "externalGateVerdictPath": "verdict.json", "outcome": "EXPECTED_BLOCK"},
                    {"attemptId": "B", "submissionId": "NEW", "role": "SUCCESS_REFERENCE", "trustKernelRunPath": "run.json", "externalGateVerdictPath": "verdict.json", "outcome": "EXTERNAL_PASS"},
                ],
                "comparison": {"successAttemptId": "B", "failureAttemptId": "A", "observations": []},
                "boundaries": [],
                "evidenceRefs": ["run.json", "verdict.json"],
            }
            (root / "input.json").write_text(json.dumps(input_data), encoding="utf-8")
            # Both fixtures point to the same successful artifacts here; the failure role is
            # intentionally invalid so the builder must fail closed.
            result = run([CASE_FAMILY, "--input", root / "input.json", "--out", root / "family.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
