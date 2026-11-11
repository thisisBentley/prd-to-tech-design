import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load("gate_contract_validator")

    def passing_gate(self):
        return {
            "schemaVersion": 2,
            "gate": "G1",
            "revision": "r2",
            "frozenCopy": ".delivery/candidate-revisions/r2",
            "independentContext": True,
            "reviewRunId": "review-1",
            "result": "PASS",
            "ruleSetVersion": "delivery-final-v1",
            "objectHashes": {"PRD_DELIVERY.md": "a" * 64},
            "checks": [
                {"checkId": "G1.MUST.roles", "status": "passed", "evidenceRefs": ["PRD §3.8"]},
                {"checkId": "G1.MUST.rules", "status": "passed", "evidenceRefs": ["PRD §3.9"]}
            ],
            "findings": [],
            "blockingCount": 0,
            "completionStatus": "complete",
            "tool": "review-worker",
            "checkedAt": "2026-11-06T00:00:00Z",
        }

    def test_pass_requires_checks_and_evidence(self):
        errors = self.validator.validate_gate(self.passing_gate())
        self.assertEqual(errors, [])

    def test_empty_findings_pass_is_rejected(self):
        data = self.passing_gate()
        data["checks"] = []
        errors = self.validator.validate_gate(data)
        self.assertIn("PASS requires checks; use INCOMPLETE when checks did not run", errors)

    def test_unverified_check_cannot_pass(self):
        data = self.passing_gate()
        data["checks"].append({"checkId": "roles", "status": "unverified", "evidenceRefs": ["x"]})
        errors = self.validator.validate_gate(data)
        self.assertTrue(any("PASS gate contains unverified" in e for e in errors))

    def test_need_fix_requires_blocker(self):
        data = self.passing_gate()
        data["result"] = "NEEDS_FIX"
        errors = self.validator.validate_gate(data)
        self.assertTrue(any("blockingCount>0" in e for e in errors))

    def test_legacy_ruleset_cannot_pass(self):
        data = self.passing_gate()
        data["ruleSetVersion"] = "legacy-delivery-v1.5"
        errors = self.validator.validate_gate(data)
        self.assertTrue(any("not approved for formal PASS" in e for e in errors))

    def test_single_check_cannot_pass_g1(self):
        data = self.passing_gate()
        data["checks"] = [data["checks"][0]]
        errors = self.validator.validate_gate(data)
        self.assertTrue(any("at least 2 executable checks" in e for e in errors))

    def test_pass_cannot_hide_failed_check(self):
        data = self.passing_gate()
        data["checks"].append({"checkId": "G1.failed", "status": "failed", "evidenceRefs": ["x"]})
        errors = self.validator.validate_gate(data)
        self.assertTrue(any("contains failed check" in e for e in errors))

    def test_summary_rejects_finalizable_incomplete(self):
        data = {
            "schemaVersion": 2,
            "bundleId": "D",
            "revision": "r1",
            "reviewRunId": "review-1",
            "frozenCopy": ".x",
            "independentContext": True,
            "hashStable": True,
            "results": {g: "PASS" for g in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]},
            "openBlockingFindings": 0,
            "finalizable": True,
        }
        data["results"]["Q1"] = "INCOMPLETE"
        errors = self.validator.validate_summary(data)
        self.assertTrue(any("Q1=INCOMPLETE" in e for e in errors))


class BundleValidatorTests(unittest.TestCase):
    def make_bundle(self):
        self.tmp = Path(tempfile.TemporaryDirectory().name)
        self.tmp.mkdir(parents=True)
        dd = self.tmp / ".delivery"
        cr = dd / "candidate-revisions" / "r1"
        cr.mkdir(parents=True)
        files = ["Demo_Jira_Description.md", "Demo_Overview.html", "Demo_PRD_DELIVERY.md", "Demo_Gates.md", "Demo_Workflow.md"]
        hashes = {}
        vals = {"R0":"PASS","G1":"PASS","O1":"PASS","U1":"PASS","U2":"PASS_WITH_NONBLOCKING","QA":"PASS","Q1":"PASS_WITH_NONBLOCKING"}
        table = "\n".join(f"| {g} | {v} |" for g, v in vals.items())
        (cr / "Demo_Gates.md").write_text(f"# Gates\n\n| Gate | Result |\n|---|---|\n{table}\n", encoding="utf-8")
        (cr / "Demo_Workflow.md").write_text(f"# Workflow\n\n| Gate | Result |\n|---|---|\n{table}\n", encoding="utf-8")
        for name in files:
            p = cr / name
            if not p.exists():
                p.write_text(name, encoding="utf-8")
        (dd / "requirements.json").write_text(json.dumps({"jiraKey": "DEMO"}), encoding="utf-8")
        import shutil
        shutil.copy2(dd / "requirements.json", cr / "requirements.json")
        for name in files:
            hashes[name] = __import__("hashlib").sha256((cr / name).read_bytes()).hexdigest()
        hashes["requirements.json"] = __import__("hashlib").sha256((dd / "requirements.json").read_bytes()).hexdigest()
        seal = {"bundleId": "DEMO", "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1", "artifactHashes": hashes}
        (dd / "candidate-seal.json").write_text(json.dumps(seal), encoding="utf-8")
        final = {
            "bundleId": "DEMO", "revision": "r1", "status": "DESIGN_READY",
            "reviewRunId": "rev", "independentExecution": True,
            "artifactsUnchangedDuringReview": True, "openBlockingFindings": 0
        }
        (dd / "final-seal.json").write_text(json.dumps(final), encoding="utf-8")
        state = {"phase2": {"bundleId": "DEMO", "revision": "r1", "status": "DESIGN_READY"}}
        (dd / "state.json").write_text(json.dumps(state), encoding="utf-8")
        dc = {"decisionReadiness": "READY"}
        (dd / "decision-context.json").write_text(json.dumps(dc), encoding="utf-8")
        policy_lock = dd / "policy-lock.json"
        policy_lock.write_text(json.dumps({"schemaVersion": 1, "policyPackId": "test", "policyPackVersion": "1.0.0", "ruleSetVersion": "delivery-final-v1", "policyPackSha256": "a" * 64, "generatedAt": "2026-11-06T00:00:00Z", "scope": {"artifactProfile": "PRD_PLUS_PROTOTYPE", "requirementTypes": [], "prototypeStatus": "TRIGGERED", "uiOwnership": "LOCAL"}, "applicableRules": {g: [] for g in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]}, "excludedRules": []}), encoding="utf-8")
        policy_hash = __import__("hashlib").sha256(policy_lock.read_bytes()).hexdigest()
        (dd / "generation-obligations.json").write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "policyLockPath": str(policy_lock), "policyLockSha256": policy_hash, "generatedAt": "2026-11-06T00:00:00Z", "obligations": [], "metrics": {"total": 0, "open": 0}}), encoding="utf-8")
        (dd / "obligation-declarations.json").write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "policyLockSha256": policy_hash, "declarations": [], "generatedAt": "2026-11-06T00:00:00Z"}), encoding="utf-8")
        gr = dd / "gate-results" / "r1"
        gr.mkdir(parents=True)
        for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
            result = vals[gate]
            gr.joinpath(f"{gate}.json").write_text(json.dumps({
                "schemaVersion": 2, "gate": gate, "revision": "r1",
                "frozenCopy": ".delivery/candidate-revisions/r1",
                "independentContext": True, "reviewRunId": "rev", "result": result,
                "ruleSetVersion": "delivery-final-v1", "policyLockSha256": policy_hash, "objectHashes": {
                    ("requirements.json" if gate == "R0" else
                     "Demo_Overview.html" if gate == "O1" else "Demo_PRD_DELIVERY.md"): hashes[
                        "requirements.json" if gate == "R0" else
                        "Demo_Overview.html" if gate == "O1" else "Demo_PRD_DELIVERY.md"
                    ]
                },
                "checks": [
                    {"checkId": "c1", "status": "passed", "evidenceRefs": ["e"]},
                    {"checkId": "c2", "status": "passed", "evidenceRefs": ["e"]}
                ],
                "findings": ["U2:nonblocking"] if gate in {"U2", "Q1"} else [],
                "blockingCount": 0, "completionStatus": "complete",
                "tool": "test-worker", "checkedAt": "2026-11-06T00:00:00Z"
            }), encoding="utf-8")
        reviews = dd / "reviews" / "rev"
        reviews.mkdir(parents=True)
        (reviews / "envelope.json").write_text(json.dumps({
            "schemaVersion": 1, "reviewRunId": "rev", "revision": "r1", "frozenCopy": "x",
            "createdAt": "2026-11-06T00:00:00Z", "worker": {"kind": "process", "identity": "test-worker"},
            "inputHashes": hashes, "transcript": "transcript.txt"
        }), encoding="utf-8")
        (reviews / "transcript.txt").write_text("independent worker transcript\n", encoding="utf-8")
        (dd / "cross-artifact-preflight.json").write_text(json.dumps({
            "schemaVersion": 1, "artifactType": "cross-artifact-preflight", "result": "PASS",
            "checks": [], "findings": [], "blockingFindings": 0, "checkedAt": "2026-11-06T00:00:00Z"
        }), encoding="utf-8")
        return self.tmp

    def test_valid_bundle_passes(self):
        bundle = self.make_bundle()
        spec = importlib.util.spec_from_file_location("bundle", ROOT / SCRIPTS / "validate_delivery_bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors = mod.validate_bundle(bundle)
        self.assertEqual(errors, [])

    def test_gate_internal_hash_contradiction_is_rejected(self):
        bundle = self.make_bundle()
        q1 = bundle / ".delivery" / "gate-results" / "r1" / "Q1.json"
        data = json.loads(q1.read_text())
        data["checks"][0]["checkId"] = "Q1.HASH_STABILITY"
        data["checks"][0]["observed"] = {"Demo_PRD_DELIVERY.md": "f" * 64}
        q1.write_text(json.dumps(data), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("bundle", ROOT / SCRIPTS / "validate_delivery_bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors = mod.validate_bundle(bundle)
        self.assertTrue(any("hash-stability observation" in error for error in errors))

    def test_missing_review_transcript_is_rejected(self):
        bundle = self.make_bundle()
        (bundle / ".delivery" / "reviews" / "rev" / "transcript.txt").write_text("", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("bundle", ROOT / SCRIPTS / "validate_delivery_bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors = mod.validate_bundle(bundle)
        self.assertTrue(any("transcript is missing or empty" in e for e in errors))

    def test_revision_drift_is_rejected(self):
        bundle = self.make_bundle()
        dd = bundle / ".delivery"
        data = json.loads((dd / "final-seal.json").read_text())
        data["revision"] = "r2"
        (dd / "final-seal.json").write_text(json.dumps(data))
        spec = importlib.util.spec_from_file_location("bundle", ROOT / SCRIPTS / "validate_delivery_bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors = mod.validate_bundle(bundle)
        self.assertTrue(errors)


class CLIContractTests(unittest.TestCase):
    def test_gate_validator_cli(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "gate.json"
            p.write_text(json.dumps({
                "schemaVersion": 2, "gate": "G1", "revision": "r1", "frozenCopy": "x",
                "independentContext": True, "reviewRunId": "rev", "result": "PASS",
                "ruleSetVersion": "delivery-final-v1", "objectHashes": {"a": "a" * 64}, "checks": [], "findings": [],
                "blockingCount": 0, "completionStatus": "complete", "tool": "worker",
                "checkedAt": "2026-11-06T00:00:00Z"
            }), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / SCRIPTS / "gate_contract_validator.py"), str(p)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("PASS requires checks", proc.stdout)


if __name__ == "__main__":
    unittest.main()
