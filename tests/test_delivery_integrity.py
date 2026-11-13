import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
BINDING = SCRIPTS / "validate_prototype_binding.py"
INTEGRITY = SCRIPTS / "verify_delivery_bundle_integrity.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeliveryIntegrityTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def make_bundle(self, tmp: Path):
        delivery = tmp / "01-delivery"
        dd = delivery / ".delivery"
        cr = dd / "candidate-revisions" / "r1"
        cr.mkdir(parents=True)
        dd.mkdir(parents=True, exist_ok=True)
        prd = delivery / "Demo_PRD_DELIVERY.md"
        proto = delivery / "Demo_Prototype.html"
        manifest = delivery / "prototype-manifest.json"
        overview = delivery / "Demo_Overview.html"
        jira = delivery / "Demo_Jira_Description.md"
        gates = delivery / "Demo_Gates.md"
        workflow = delivery / "Demo_Workflow.md"
        proto_text = '<!doctype html><html><body><button data-ai-id="UI-EXPORT" data-ai-fr="FR-001" data-ai-ac="AC-001">导出</button></body></html>\n'
        proto.write_text(proto_text, encoding="utf-8")
        prd.write_text("# Demo\n\n### FR-001：导出\n- 规则\n\n### AC-001 导出成功\n- THEN：生成文件\n", encoding="utf-8")
        manifest.write_text(json.dumps({
            "schemaVersion": 1, "manifestId": "M-1", "workflowId": "WF-1", "prototypeRevision": "r1",
            "prototypePath": str(proto), "prototypeHash": sha(proto),
            "elements": [{"uiElementId": "UI-EXPORT", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "导出", "states": ["default", "empty"], "action": "click"}],
            "createdAt": "2026-11-11T00:00:00Z",
        }), encoding="utf-8")
        for p in [overview, jira, gates, workflow]:
            p.write_text(p.name, encoding="utf-8")
        (delivery / "requirements.json").write_text(json.dumps({"jiraKey": "DEMO"}), encoding="utf-8")
        (dd / "decision-context.json").write_text(json.dumps({"decisionReadiness": "READY"}), encoding="utf-8")
        (dd / "semantic-consistency-review.json").write_text(json.dumps({"verdict": "ACCEPTED", "blockingCount": 0}), encoding="utf-8")
        policy_lock = dd / "policy-lock.json"
        policy_lock.write_text(json.dumps({"schemaVersion": 1, "policyPackId": "test", "policyPackVersion": "1.0.0", "ruleSetVersion": "delivery-final-v1", "policyPackSha256": "a" * 64, "generatedAt": "2026-11-11T00:00:00Z", "scope": {"artifactProfile": "PRD_PLUS_PROTOTYPE", "requirementTypes": [], "prototypeStatus": "TRIGGERED", "uiOwnership": "LOCAL"}, "applicableRules": {g: [] for g in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]}, "excludedRules": []}), encoding="utf-8")
        policy_hash = sha(policy_lock)
        (dd / "generation-obligations.json").write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "policyLockPath": str(policy_lock), "policyLockSha256": policy_hash, "generatedAt": "2026-11-11T00:00:00Z", "obligations": [], "metrics": {"total": 0, "open": 0}}), encoding="utf-8")
        (dd / "obligation-declarations.json").write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "policyLockSha256": policy_hash, "declarations": [], "generatedAt": "2026-11-11T00:00:00Z"}), encoding="utf-8")
        artifacts = [prd, proto, manifest, overview, jira, gates, workflow]
        for p in artifacts:
            (cr / p.name).write_bytes(p.read_bytes())
        (cr / "requirements.json").write_bytes((delivery / "requirements.json").read_bytes())
        hashes = {p.name: sha(p) for p in artifacts}
        hashes["requirements.json"] = sha(delivery / "requirements.json")
        (dd / "candidate-seal.json").write_text(json.dumps({"bundleId": "DEMO", "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1", "artifactHashes": hashes}), encoding="utf-8")
        final = {"bundleId": "DEMO", "revision": "r1", "status": "DESIGN_READY", "reviewRunId": "rev", "artifactHashes": hashes, "gateResults": {g: "PASS" for g in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]}, "independentExecution": True, "artifactsUnchangedDuringReview": True, "openBlockingFindings": 0}
        (dd / "final-seal.json").write_text(json.dumps(final), encoding="utf-8")
        gr = dd / "gate-results" / "r1"
        gr.mkdir(parents=True)
        for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
            observed = {}
            if gate == "Q1":
                observed = {"Demo_Overview.html": hashes["Demo_Overview.html"]}
            (gr / f"{gate}.json").write_text(json.dumps({
                "schemaVersion": 2, "gate": gate, "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1", "independentContext": True,
                "reviewRunId": "rev", "result": "PASS", "ruleSetVersion": "delivery-final-v1", "policyLockSha256": policy_hash, "objectHashes": hashes,
                "checks": [{"checkId": "HASH_STABILITY" if gate == "Q1" else "CHECK", "status": "passed", "evidenceRefs": ["e"], "observed": observed, "expected": "stable"}],
                "findings": [], "blockingCount": 0, "completionStatus": "complete", "tool": "test-worker", "checkedAt": "2026-11-11T00:00:00Z",
            }), encoding="utf-8")
        return delivery, hashes, gr

    def write_audit_track(self, delivery: Path):
        dd = delivery / ".delivery"
        policy_hash = sha(dd / "policy-lock.json")
        plan = {
            "schemaVersion": 1,
            "auditPlanId": "audit-WF-1-r1",
            "workflowId": "WF-1",
            "revision": "r1",
            "policyLockPath": str(dd / "policy-lock.json"),
            "policyLockSha256": policy_hash,
            "profileId": "PRD_PROTOTYPE_AUDIT",
            "profileVersion": "1.0.0",
            "crosswalkId": "delivery-toolbox-v2",
            "crosswalkVersion": "1.0.0",
            "crosswalkSha256": "b" * 64,
            "blockingFindingPolicy": "BLOCK_BLOCKING",
            "jobs": [{
                "jobId": "AUD-R0", "jobType": "RULE_AUDIT", "sourcePolicyRuleIds": ["R0.ARTIFACT_SET"],
                "sourceSkillId": "prd-review", "sourceSkillCheckIds": ["REVIEW.ARTIFACT_SET"],
                "executorType": "DETERMINISTIC", "owner": "delivery-reviewer",
                "requiredEvidence": ["artifact set"], "passCondition": "all required artifacts exist",
            }],
            "coverage": {
                "expectedRules": 1, "mappedRules": 1, "minimumExecutorsPerRule": 1,
                "uncoveredRules": [], "underCoveredRules": [], "requiredGlobalAudits": [],
            },
            "status": "READY",
            "errors": [],
            "createdAt": "2026-11-13T00:00:00Z",
        }
        plan_path = dd / "audit-plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        summary = {
            "schemaVersion": 1,
            "auditSummaryId": "audit-summary-WF-1-r1",
            "auditPlanSha256": sha(plan_path),
            "workflowId": "WF-1",
            "revision": "r1",
            "policyLockSha256": policy_hash,
            "profileId": "PRD_PROTOTYPE_AUDIT",
            "status": "AUDIT_PASS",
            "expectedJobs": 1,
            "completedJobs": 1,
            "expectedRules": 1,
            "coveredRules": 1,
            "missingJobs": [],
            "missingRules": [],
            "failedJobs": [],
            "blockingFindingCount": 0,
            "jobs": [{"jobId": "AUD-R0", "status": "PASS", "resultPath": "AUD-R0.result.json", "coveredRules": ["R0.ARTIFACT_SET"]}],
            "ruleCoverage": [{"ruleId": "R0.ARTIFACT_SET", "executorTypes": ["DETERMINISTIC"], "jobIds": ["AUD-R0"], "status": "COVERED"}],
            "errors": [],
            "checkedAt": "2026-11-13T00:00:00Z",
        }
        (dd / "audit-summary.json").write_text(json.dumps(summary), encoding="utf-8")

    def test_binding_requires_data_ai_contract(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, hashes, _ = self.make_bundle(tmp)
            result = self.run_tool(BINDING, "--prototype", delivery / "Demo_Prototype.html", "--manifest", delivery / "prototype-manifest.json", "--prd", delivery / "Demo_PRD_DELIVERY.md", "--json")
            self.assertEqual(result["status"], "PASS")

    def test_binding_detects_html_drift(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, hashes, _ = self.make_bundle(tmp)
            proto = delivery / "Demo_Prototype.html"
            proto.write_text(proto.read_text().replace('data-ai-ac="AC-001"', 'data-ai-ac="AC-999"'), encoding="utf-8")
            self.run_tool(BINDING, "--prototype", proto, "--manifest", delivery / "prototype-manifest.json", "--prd", delivery / "Demo_PRD_DELIVERY.md", "--json", expect=1)

    def test_readiness_passes_only_with_consistent_evidence_and_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, hashes, _ = self.make_bundle(tmp)
            out = tmp / "readiness.json"
            result = self.run_tool(INTEGRITY, "--bundle", delivery, "--out", out)
            self.assertEqual(result["status"], "DESIGN_READY")
            self.assertTrue(result["contentReady"] and result["evidenceReady"] and result["bundleReady"])

    def test_readiness_blocks_q1_hash_contradiction(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, hashes, gr = self.make_bundle(tmp)
            q1 = json.loads((gr / "Q1.json").read_text())
            q1["checks"][0]["observed"] = {"Demo_Overview.html": "f" * 64}
            (gr / "Q1.json").write_text(json.dumps(q1), encoding="utf-8")
            out = tmp / "readiness.json"
            self.run_tool(INTEGRITY, "--bundle", delivery, "--out", out, expect=1)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "EVIDENCE_BLOCKED")
            self.assertFalse(report["evidenceReady"])
            self.assertIn("INTEGRITY.GATE_INTERNAL_HASHES", report["findings"])

    def test_required_audit_blocks_without_audit_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, _, _ = self.make_bundle(tmp)
            out = tmp / "readiness.json"
            self.run_tool(INTEGRITY, "--bundle", delivery, "--require-audit", "--out", out, expect=1)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "AUDIT_BLOCKED")
            self.assertFalse(report["auditReady"])
            self.assertIn("AUDIT.TRACK", report["findings"])

    def test_required_audit_passes_with_bound_summary(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, _, _ = self.make_bundle(tmp)
            self.write_audit_track(delivery)
            out = tmp / "readiness.json"
            result = self.run_tool(INTEGRITY, "--bundle", delivery, "--require-audit", "--out", out)
            self.assertEqual(result["status"], "DESIGN_READY")
            self.assertTrue(result["auditReady"])

    def test_audit_summary_plan_drift_blocks_design_ready(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, _, _ = self.make_bundle(tmp)
            self.write_audit_track(delivery)
            plan_path = delivery / ".delivery" / "audit-plan.json"
            plan = json.loads(plan_path.read_text())
            plan["auditPlanId"] = "changed-after-summary"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            out = tmp / "readiness.json"
            self.run_tool(INTEGRITY, "--bundle", delivery, "--require-audit", "--out", out, expect=1)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "AUDIT_BLOCKED")
            self.assertIn("AUDIT.TRACK", report["findings"])

    def test_readiness_blocks_non_self_contained_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            delivery, hashes, _ = self.make_bundle(tmp)
            (delivery / "requirements.json").unlink()
            out = tmp / "readiness.json"
            self.run_tool(INTEGRITY, "--bundle", delivery, "--out", out, expect=1)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "BUNDLE_BLOCKED")
            self.assertFalse(report["bundleReady"])


if __name__ == "__main__":
    unittest.main()
