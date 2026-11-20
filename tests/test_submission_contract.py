import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
TARGET = TOOLS / "validate_target_binding.py"
EXTERNAL = TOOLS / "normalize_external_gate.py"
ADAPTER = TOOLS / "adapt_qa_g1_gate.py"
RUN_KERNEL = TOOLS / "run_trust_kernel.py"
CACHE = TOOLS / "cache_external_gate.py"
COMPILE = TOOLS / "compile_submission_contract.py"
VALIDATE = TOOLS / "validate_submission_contract.py"
FINAL_GATE = TOOLS / "final_gatekeeper.py"
MODE_POLICY = ROOT / "config" / "trust-kernel" / "execution-mode-policy-v1.json"
TOOL_POLICY = ROOT / "config" / "trust-kernel" / "specialist-tool-routes-v1.json"
SUBMISSION_POLICY = ROOT / "config" / "trust-kernel" / "submission-policy-v1.json"


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class SubmissionContractTests(unittest.TestCase):
    def fixture(self, root):
        prd = root / "PRD_DELIVERY.md"
        overview = root / "Overview.html"
        prd.write_text(
            "# PRD\n\n"
            "- Requirement ID: `BOT-41040`\n"
            "- Issue Key: `BOT-41040`\n"
            "- Issue URL: https://jira.example/browse/BOT-41040\n"
            "- Owner: 李彧烨\n"
            "- 当前 PRD 版本: `v1.1`\n"
            "- Source baseline: Jira `BOT-41040`\n\n"
            "## FR-001\n审计留痕矩阵。\n",
            encoding="utf-8",
        )
        overview.write_text(
            '<!doctype html><html><head>'
            '<meta name="issue-key" content="BOT-41040">'
            '<meta name="issue-url" content="https://jira.example/browse/BOT-41040">'
            '<meta name="owner" content="李彧烨">'
            '<meta name="source-prd-version" content="v1.1">'
            '</head><body>Overview</body></html>',
            encoding="utf-8",
        )
        binding_request = {
            "schemaVersion": 1,
            "workflowId": "WF-SUB-1",
            "target": {"jiraKey": "BOT-41040", "jiraUrl": "https://jira.example/browse/BOT-41040", "owner": "李彧烨"},
            "artifacts": [
                {"type": "PRD", "path": str(prd), "expectedVersion": "v1.1"},
                {"type": "OVERVIEW", "path": str(overview), "expectedVersion": "v1.1"},
            ],
            "allowedLineageIssueKeys": ["ZY20260067-1017"],
        }
        binding_request_path = root / "binding-request.json"
        binding_request_path.write_text(json.dumps(binding_request), encoding="utf-8")
        binding_report_path = root / "target-binding.json"
        run([TARGET, "--request", binding_request_path, "--out", binding_report_path])

        task = {
            "schemaVersion": 1,
            "workflowId": "WF-SUB-1",
            "taskId": "TASK-SUB-1",
            "title": "Local revision",
            "objective": "Fix external findings",
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
        task_path = root / "task.json"
        task_path.write_text(json.dumps(task), encoding="utf-8")
        kernel_path = root / "trust-kernel.json"
        run([
            RUN_KERNEL,
            "--task-request", task_path,
            "--execution-mode-policy", MODE_POLICY,
            "--tool-policy", TOOL_POLICY,
            "--intent", "PRD_LOCAL_REVISION",
            "--target-binding-request", binding_request_path,
            "--out", kernel_path,
        ])
        binding_report = json.loads(binding_report_path.read_text(encoding="utf-8"))
        candidate_artifacts = [
            {"path": str(prd), "sha256": hashlib.sha256(prd.read_bytes()).hexdigest()},
            {"path": str(overview), "sha256": hashlib.sha256(overview.read_bytes()).hexdigest()},
        ]
        return {
            "root": root,
            "prd": prd,
            "overview": overview,
            "binding_request": binding_request_path,
            "binding_report": binding_report_path,
            "binding_report_data": binding_report,
            "kernel": kernel_path,
            "candidate_artifacts": candidate_artifacts,
            "tool": {"toolId": "gitlab-prd-tool", "version": "V2.3.0", "sourceCommit": "e4f0118"},
        }

    def external_verdict(self, fx, gate_type, raw_result="PASS", findings=None, tool=None):
        data = {
            "schemaVersion": 1,
            "workflowId": "WF-SUB-1",
            "candidateRevision": "r1",
            "jiraKey": "BOT-41040",
            "gateType": gate_type,
            "rawResult": raw_result,
            "findings": findings or [],
            "tool": tool or fx["tool"],
            "candidateArtifacts": fx["candidate_artifacts"],
            "evidenceRefs": [f"jira-{gate_type.lower()}-comment.json"],
            "checkedAt": "2026-11-20T10:00:00+08:00",
        }
        input_path = fx["root"] / f"external-{gate_type.lower()}.json"
        input_path.write_text(json.dumps(data), encoding="utf-8")
        verdict_path = fx["root"] / f"verdict-{gate_type.lower()}.json"
        expected = 0 if raw_result == "PASS" and not any(item.get("severity") == "BLOCKING" for item in (findings or [])) else 1
        run([EXTERNAL, "--input", input_path, "--target-binding", fx["binding_report"], "--out", verdict_path], expect=expected)
        return verdict_path

    def request(self, fx, cache_dir, required_gates=None, tool=None):
        data = {
            "schemaVersion": 1,
            "workflowId": "WF-SUB-1",
            "candidateRevision": "r1",
            "target": {"jiraKey": "BOT-41040", "jiraUrl": "https://jira.example/browse/BOT-41040", "owner": "李彧烨"},
            "tool": tool or fx["tool"],
            "candidateArtifacts": [
                {"type": "PRD", "path": str(fx["prd"])},
                {"type": "OVERVIEW", "path": str(fx["overview"])},
            ],
            "trustKernelRunPath": str(fx["kernel"]),
            "targetBindingReportPath": str(fx["binding_report"]),
            "verdictCacheDir": str(cache_dir),
            "submissionPolicyPath": str(SUBMISSION_POLICY),
            "requiredGates": required_gates or ["QA", "G1"],
        }
        path = fx["root"] / "submission-request.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_qa_g1_pass_closes_and_replays_deterministically(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            qa = self.external_verdict(fx, "QA")
            g1 = self.external_verdict(fx, "G1")
            first = run([CACHE, "--verdict", qa, "--cache-dir", cache_dir])
            second = run([CACHE, "--verdict", qa, "--cache-dir", cache_dir])
            self.assertEqual(first["status"], "WRITTEN")
            self.assertEqual(second["status"], "CACHED")
            self.assertEqual(first["cacheKey"], second["cacheKey"])
            run([CACHE, "--verdict", g1, "--cache-dir", cache_dir])
            request = self.request(fx, cache_dir)
            contract_path = root / "submission-contract.json"
            manifest_path = root / "submission-manifest.json"
            closed = run([COMPILE, "--request", request, "--out", contract_path, "--manifest-out", manifest_path])
            self.assertEqual(closed["status"], "CLOSED")
            self.assertTrue(closed["closureEligible"])
            first_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            replay = run([COMPILE, "--request", request, "--out", contract_path, "--manifest-out", manifest_path])
            second_contract = json.loads(contract_path.read_text(encoding="utf-8"))
            second_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(replay["status"], "CLOSED")
            self.assertEqual(first_contract["contractId"], second_contract["contractId"])
            self.assertEqual(first_manifest["manifestId"], second_manifest["manifestId"])
            self.assertEqual(first_manifest["contentSha256"], second_manifest["contentSha256"])
            validated = run([VALIDATE, "--contract", contract_path, "--manifest", manifest_path, "--out", root / "readiness.json"])
            self.assertEqual(validated["status"], "PASS")

    def test_qa_adapter_preserves_source_provenance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            report = {
                "schemaVersion": 1,
                "workflowId": "WF-SUB-1",
                "candidateRevision": "r1",
                "jiraKey": "BOT-41040",
                "gateType": "QA",
                "report": {
                    "reportId": "jira-comment-35918",
                    "statusText": "PASS",
                    "checkedAt": "2026-11-20T10:00:00+08:00",
                    "evidenceRefs": ["jira-comment-35918.json"],
                },
                "findings": [],
                "tool": fx["tool"],
                "candidateArtifacts": fx["candidate_artifacts"],
            }
            report_path = root / "qa-report.json"
            report_path.write_text(json.dumps(report), encoding="utf-8")
            verdict_path = root / "qa-verdict.json"
            result = run([ADAPTER, "--report", report_path, "--target-binding", fx["binding_report"], "--out", verdict_path])
            self.assertEqual(result["verdict"], "PASS")
            self.assertEqual(result["releaseState"], "CLOSED")
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            self.assertIn("jira-comment-35918", verdict["evidenceRefs"])

    def test_final_gatekeeper_binds_closed_submission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            for gate in ("QA", "G1"):
                run([CACHE, "--verdict", self.external_verdict(fx, gate), "--cache-dir", cache_dir])
            request = self.request(fx, cache_dir)
            contract_path = root / "contract.json"
            manifest_path = root / "manifest.json"
            run([COMPILE, "--request", request, "--out", contract_path, "--manifest-out", manifest_path])
            gate_root = root / "gate-run"
            gate_root.mkdir()
            result = subprocess.run([
                sys.executable, str(FINAL_GATE),
                "--run-root", str(gate_root), "--requirement-name", "Demo",
                "--skip-delivery", "--skip-tech",
                "--trust-kernel-run", str(fx["kernel"]),
                "--submission-contract", str(contract_path),
                "--submission-manifest", str(manifest_path),
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            trust_check = next(item for item in payload["checks"] if item["checkId"] == "FINAL.TRUST_KERNEL.BINDING")
            submission_check = next(item for item in payload["checks"] if item["checkId"] == "FINAL.SUBMISSION.CONTRACT")
            self.assertEqual(trust_check["status"], "passed")
            self.assertEqual(submission_check["status"], "passed")

    def test_internal_ready_without_external_verdict_is_pending(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            qa = self.external_verdict(fx, "QA")
            run([CACHE, "--verdict", qa, "--cache-dir", cache_dir])
            request = self.request(fx, cache_dir)
            contract_path = root / "submission-contract.json"
            manifest_path = root / "submission-manifest.json"
            result = run([COMPILE, "--request", request, "--out", contract_path, "--manifest-out", manifest_path], expect=1)
            self.assertEqual(result["status"], "EXTERNAL_GATE_PENDING")
            self.assertFalse(result["closureEligible"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "REQUIRED_GATE_VERDICT_MISSING" for item in contract["findings"]))
            run([VALIDATE, "--contract", contract_path, "--manifest", manifest_path, "--out", root / "readiness.json"], expect=1)

    def test_gate_policy_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            for gate in ("QA", "G1"):
                run([CACHE, "--verdict", self.external_verdict(fx, gate), "--cache-dir", cache_dir])
            request = self.request(fx, cache_dir, required_gates=["QA"])
            result = run([COMPILE, "--request", request, "--out", root / "contract.json", "--manifest-out", root / "manifest.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            contract = json.loads((root / "contract.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "SUBMISSION_POLICY_GATE_MISMATCH" for item in contract["findings"]))

    def test_candidate_drift_blocks_closed_submission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            for gate in ("QA", "G1"):
                run([CACHE, "--verdict", self.external_verdict(fx, gate), "--cache-dir", cache_dir])
            fx["overview"].write_text(fx["overview"].read_text(encoding="utf-8") + "\n<!-- changed -->\n", encoding="utf-8")
            request = self.request(fx, cache_dir)
            result = run([COMPILE, "--request", request, "--out", root / "contract.json", "--manifest-out", root / "manifest.json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            contract = json.loads((root / "contract.json").read_text(encoding="utf-8"))
            self.assertTrue(any(item["code"] == "TARGET_BINDING_ARTIFACT_HASH_MISMATCH" for item in contract["findings"]))

    def test_environment_blocked_never_degrades(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            qa = self.external_verdict(fx, "QA", raw_result="ENVIRONMENT_BLOCKED")
            g1 = self.external_verdict(fx, "G1")
            run([CACHE, "--verdict", qa, "--cache-dir", cache_dir])
            run([CACHE, "--verdict", g1, "--cache-dir", cache_dir])
            request = self.request(fx, cache_dir)
            result = run([COMPILE, "--request", request, "--out", root / "contract.json", "--manifest-out", root / "manifest.json"], expect=1)
            self.assertEqual(result["status"], "ENVIRONMENT_BLOCKED")
            self.assertFalse(result["closureEligible"])

    def test_conflicting_repeated_gate_verdict_blocks_cache(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            passed = self.external_verdict(fx, "QA")
            run([CACHE, "--verdict", passed, "--cache-dir", cache_dir])
            rejected = self.external_verdict(fx, "QA", raw_result="REJECTED", findings=[{"findingId": "F-1", "severity": "BLOCKING", "summary": "broken"}])
            result = run([CACHE, "--verdict", rejected, "--cache-dir", cache_dir], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertIn("conflicting external verdicts", result["errors"][0])

    def test_tool_version_mismatch_cannot_use_existing_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fx = self.fixture(root)
            cache_dir = root / "gate-cache"
            for gate in ("QA", "G1"):
                run([CACHE, "--verdict", self.external_verdict(fx, gate), "--cache-dir", cache_dir])
            other_tool = {"toolId": "gitlab-prd-tool", "version": "V2.4.0", "sourceCommit": "f" * 8}
            request = self.request(fx, cache_dir, tool=other_tool)
            result = run([COMPILE, "--request", request, "--out", root / "contract.json", "--manifest-out", root / "manifest.json"], expect=1)
            self.assertEqual(result["status"], "EXTERNAL_GATE_PENDING")
            contract = json.loads((root / "contract.json").read_text(encoding="utf-8"))
            self.assertTrue(all(item["present"] is False for item in contract["gateResults"]))


if __name__ == "__main__":
    unittest.main()
