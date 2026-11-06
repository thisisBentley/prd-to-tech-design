import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
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
            "ruleSetVersion": "prd-admission-1.0",
            "objectHashes": {"PRD_DELIVERY.md": "a" * 64},
            "checks": [
                {"checkId": "G1.MUST.roles", "status": "passed", "evidenceRefs": ["PRD §3.8"]}
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
        table = "\n".join(f"| {g} | PASS_WITH_NONBLOCKING |" for g in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"])
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
        final = {"bundleId": "DEMO", "revision": "r1", "status": "DESIGN_READY", "openBlockingFindings": 0}
        (dd / "final-seal.json").write_text(json.dumps(final), encoding="utf-8")
        state = {"phase2": {"bundleId": "DEMO", "revision": "r1", "status": "DESIGN_READY"}}
        (dd / "state.json").write_text(json.dumps(state), encoding="utf-8")
        dc = {"decisionReadiness": "READY"}
        (dd / "decision-context.json").write_text(json.dumps(dc), encoding="utf-8")
        gr = dd / "gate-results" / "r1"
        gr.mkdir(parents=True)
        for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
            gr.joinpath(f"{gate}.json").write_text(json.dumps({
                "schemaVersion": 2, "gate": gate, "revision": "r1", "frozenCopy": "x",
                "independentContext": True, "reviewRunId": "rev", "result": "PASS_WITH_NONBLOCKING",
                "ruleSetVersion": "1", "objectHashes": {"a": "a" * 64},
                "checks": [{"checkId": "c", "status": "passed", "evidenceRefs": ["e"]}],
                "findings": [], "blockingCount": 0, "completionStatus": "complete",
                "tool": "worker", "checkedAt": "2026-11-06T00:00:00Z"
            }), encoding="utf-8")
        return self.tmp

    def test_valid_bundle_passes(self):
        bundle = self.make_bundle()
        spec = importlib.util.spec_from_file_location("bundle", ROOT / "tools" / "validate_delivery_bundle.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        errors = mod.validate_bundle(bundle)
        self.assertEqual(errors, [])

    def test_revision_drift_is_rejected(self):
        bundle = self.make_bundle()
        dd = bundle / ".delivery"
        data = json.loads((dd / "final-seal.json").read_text())
        data["revision"] = "r2"
        (dd / "final-seal.json").write_text(json.dumps(data))
        spec = importlib.util.spec_from_file_location("bundle", ROOT / "tools" / "validate_delivery_bundle.py")
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
                "ruleSetVersion": "1", "objectHashes": {"a": "a" * 64}, "checks": [], "findings": [],
                "blockingCount": 0, "completionStatus": "complete", "tool": "worker",
                "checkedAt": "2026-11-06T00:00:00Z"
            }), encoding="utf-8")
            proc = subprocess.run([sys.executable, str(ROOT / "tools" / "gate_contract_validator.py"), str(p)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("PASS requires checks", proc.stdout)


if __name__ == "__main__":
    unittest.main()
