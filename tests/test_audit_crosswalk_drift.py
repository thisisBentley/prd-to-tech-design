import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
TOOL = SCRIPTS / "validate_audit_crosswalk_drift.py"


class CrosswalkDriftTests(unittest.TestCase):
    def run_tool(self, *args, expect=0):
        process = subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def fixture(self, root: Path):
        policy = root / "policy.json"
        policy.write_text(json.dumps({"rules": [{"ruleId": "G1.MUST.A"}, {"ruleId": "QA.B"}]}), encoding="utf-8")
        crosswalk = root / "crosswalk.json"
        crosswalk.write_text(json.dumps({"crosswalkId": "test", "version": "1", "sourceSkills": [{"skillId": "skill-a"}], "mappings": [{"mappingId": "m1", "policyRuleIds": ["G1.MUST.A", "QA.B"], "executorTypes": ["DETERMINISTIC"], "skillId": "skill-a", "skillCheckIds": ["CHECK"], "requiredEvidence": ["PRD"], "owner": "reviewer", "appliesToProfiles": ["P"]}]}), encoding="utf-8")
        source_map = root / "source-map.json"
        source_map.write_text(json.dumps({"schemaVersion": 1, "skills": [{"skillId": "skill-a", "path": "skills/skill-a/SKILL.md", "pathKind": "CODEX_SKILLS"}]}), encoding="utf-8")
        source_root = root / "codex"; skill = source_root / "skills" / "skill-a" / "SKILL.md"; skill.parent.mkdir(parents=True); skill.write_text("v1", encoding="utf-8")
        lock = root / "lock.json"; out = root / "report.json"
        return policy, crosswalk, source_map, source_root, lock, out, skill

    def test_write_lock_then_pass_and_detect_source_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); policy, crosswalk, source_map, source_root, lock, out, skill = self.fixture(root)
            self.run_tool("--policy-pack", policy, "--crosswalk", crosswalk, "--source-map", source_map, "--source-root", source_root, "--lock", lock, "--write-lock", "--out", out)
            self.run_tool("--policy-pack", policy, "--crosswalk", crosswalk, "--source-map", source_map, "--source-root", source_root, "--lock", lock, "--out", out)
            skill.write_text("v2", encoding="utf-8")
            result = self.run_tool("--policy-pack", policy, "--crosswalk", crosswalk, "--source-map", source_map, "--source-root", source_root, "--lock", lock, "--out", out, expect=1)
            self.assertEqual(result["status"], "DRIFT")
            report = json.loads(out.read_text())
            self.assertTrue(any(item["code"] == "SOURCE_HASH_DRIFT" for item in report["drift"]))

    def test_unknown_policy_rule_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); policy, crosswalk, source_map, source_root, lock, out, _ = self.fixture(root)
            data = json.loads(crosswalk.read_text()); data["mappings"][0]["policyRuleIds"].append("UNKNOWN.RULE"); crosswalk.write_text(json.dumps(data), encoding="utf-8")
            result = self.run_tool("--policy-pack", policy, "--crosswalk", crosswalk, "--source-map", source_map, "--source-root", source_root, "--out", out, expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            report = json.loads(out.read_text())
            self.assertTrue(any(item["code"] == "UNKNOWN_POLICY_RULE" for item in report["errors"]))


if __name__ == "__main__":
    unittest.main()
