import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
BUILD = SCRIPTS / "build_policy_lock.py"
COVERAGE = SCRIPTS / "validate_gate_rule_coverage.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GatePolicyCoverageTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def build_lock(self, root: Path, profile="PRD_PLUS_PROTOTYPE", types="CRUD,UI_INTERACTION"):
        out = root / "policy-lock.json"
        self.run_tool(BUILD, "--artifact-profile", profile, "--requirement-types", types, "--prototype-status", "TRIGGERED", "--ui-ownership", "LOCAL", "--out", out)
        return out, json.loads(out.read_text())

    def write_gate_results(self, root: Path, lock_path: Path, lock: dict, omit=None):
        gate_dir = root / "gate-results"
        gate_dir.mkdir()
        for gate in ["R0", "G1", "O1", "U1", "U2", "QA", "Q1"]:
            rule_ids = lock["applicableRules"].get(gate, [])
            checks = [{"ruleId": rid, "checkId": rid, "status": "passed", "evidenceRefs": [f"evidence://{rid}"], "observed": "checked", "expected": "pass"} for rid in rule_ids if rid != omit]
            (gate_dir / f"{gate}.json").write_text(json.dumps({
                "schemaVersion": 2, "gate": gate, "revision": "r1", "frozenCopy": ".delivery/candidate-revisions/r1", "independentContext": True,
                "reviewRunId": "rev-1", "result": "PASS", "ruleSetVersion": lock["ruleSetVersion"],
                "policyLockSha256": sha(lock_path), "objectHashes": {"artifact": "a" * 64}, "checks": checks,
                "findings": [], "blockingCount": 0, "completionStatus": "complete", "tool": "independent-worker", "checkedAt": "2026-11-11T00:00:00Z",
            }), encoding="utf-8")
        return gate_dir

    def test_resolver_excludes_prototype_rules_for_prd_only(self):
        with tempfile.TemporaryDirectory() as td:
            _, lock = self.build_lock(Path(td), profile="PRD_ONLY", types="CRUD")
            self.assertFalse(lock["applicableRules"]["U1"])
            self.assertFalse(lock["applicableRules"]["U2"])
            self.assertIn("G1.MUST.ROLES_PERMISSIONS", lock["applicableRules"]["G1"])
            excluded = {item["ruleId"] for item in lock["excludedRules"]}
            self.assertIn("U1.MANIFEST_BINDING", excluded)

    def test_ai_requirement_activates_conditional_ai_rule(self):
        with tempfile.TemporaryDirectory() as td:
            _, lock = self.build_lock(Path(td), profile="PRD_PLUS_PROTOTYPE", types="AI_LLM")
            self.assertIn("G1.COND.AI_LLM", lock["applicableRules"]["G1"])

    def test_complete_rule_coverage_passes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock_path, lock = self.build_lock(root)
            gate_dir = self.write_gate_results(root, lock_path, lock)
            out = root / "coverage.json"
            result = self.run_tool(COVERAGE, "--policy-lock", lock_path, "--gate-dir", gate_dir, "--out", out)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["missing"], 0)

    def test_missing_rule_blocks_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock_path, lock = self.build_lock(root)
            gate_dir = self.write_gate_results(root, lock_path, lock, omit="G1.MUST.ROLES_PERMISSIONS")
            out = root / "coverage.json"
            self.run_tool(COVERAGE, "--policy-lock", lock_path, "--gate-dir", gate_dir, "--out", out, expect=1)
            result = json.loads(out.read_text())
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("G1.MUST.ROLES_PERMISSIONS", result["errors"][0])

    def test_wrong_policy_lock_hash_blocks_coverage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lock_path, lock = self.build_lock(root)
            gate_dir = self.write_gate_results(root, lock_path, lock)
            q1 = json.loads((gate_dir / "Q1.json").read_text())
            q1["policyLockSha256"] = "f" * 64
            (gate_dir / "Q1.json").write_text(json.dumps(q1), encoding="utf-8")
            out = root / "coverage.json"
            self.run_tool(COVERAGE, "--policy-lock", lock_path, "--gate-dir", gate_dir, "--out", out, expect=1)


if __name__ == "__main__":
    unittest.main()
