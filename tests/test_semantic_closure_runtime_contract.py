import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
DECISION = SCRIPTS / "build_decision_impact_graph.py"
RUNTIME = SCRIPTS / "validate_runtime_ac_coverage.py"
EXTERNAL = SCRIPTS / "validate_external_skill_contract.py"
PIPELINE = SCRIPTS / "delivery_pipeline.py"


class SemanticClosureRuntimeContractTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def decision_context(self, with_impact=True):
        decision = {
            "decisionId": "D-001", "title": "Counter semantics", "category": "product_decision",
            "businessScenario": "Operators need deterministic counts.", "currentFacts": [{"claim": "Counts are ambiguous", "evidenceRef": "requirement.md", "confidence": "high"}],
            "whyDecisionIsNeeded": "The runtime result changes.", "options": [
                {"optionId": "A", "label": "Continuous", "userOrBusinessResult": "Counts accumulate.", "impact": "One invariant", "reversibility": "reversible"},
                {"optionId": "B", "label": "Reset", "userOrBusinessResult": "Counts reset.", "impact": "One invariant", "reversibility": "reversible"},
            ], "recommendation": {"optionId": "A", "reason": "Matches current operation", "confidence": "high"},
            "fallback": None, "owner": "product-owner", "blocking": True, "decisionNature": "reversible",
            "status": "confirmed", "confirmation": {"confirmedBy": "product-owner", "confirmedAt": "2026-11-17T00:00:00Z", "selectedOptionId": "A", "basis": "approved"},
            "affectedRequirements": ["FR-001"], "researchRecordRefs": ["research.json"],
            "researchVerdict": "NEEDS_BUSINESS_DECISION",
        }
        if with_impact:
            decision["decisionImpact"] = {
                "affectedObjects": [
                    {"objectId": "FR-001", "objectType": "FR", "artifact": "PRD_DELIVERY.md", "evidenceRefs": ["PRD_DELIVERY.md#FR-001"]},
                    {"objectId": "AC-001", "objectType": "AC", "artifact": "PRD_DELIVERY.md", "evidenceRefs": ["PRD_DELIVERY.md#AC-001"]},
                ],
                "expectedInvariant": "The same count rule appears in the FR and all ACs.",
                "conflictingObjects": [],
                "verificationObjects": [
                    {"objectId": "AC-002", "objectType": "AC", "artifact": "PRD_DELIVERY.md", "evidenceRefs": ["PRD_DELIVERY.md#AC-002"]}
                ],
                "evidenceRefs": ["PRD_DELIVERY.md"],
            }
        return {
            "schemaVersion": 1, "requirementName": "Counter", "issueKey": "DEMO", "generatedAt": "2026-11-17T00:00:00Z",
            "sourceStage": "delivery", "decisionReadiness": "READY", "decisions": [decision], "openBlockingCount": 0,
        }

    def test_closed_decision_requires_impact_declaration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD_DELIVERY.md"
            prd.write_text("# PRD\n### FR-001 Counter\n- AC-001 config\n- AC-002 runtime\n", encoding="utf-8")
            context = root / "decision-context.json"
            out = root / "decision-impact.json"
            context.write_text(json.dumps(self.decision_context(with_impact=True)), encoding="utf-8")
            result = self.run_tool(DECISION, "--prd", prd, "--decision-context", context, "--workflow-id", "WF-D", "--out", out)
            self.assertEqual(result["status"], "PASS")
            graph = json.loads(out.read_text())
            self.assertEqual(graph["metrics"]["closedDecisions"], 1)

            context.write_text(json.dumps(self.decision_context(with_impact=False)), encoding="utf-8")
            self.run_tool(DECISION, "--prd", prd, "--decision-context", context, "--workflow-id", "WF-D", "--out", out, expect=1)
            graph = json.loads(out.read_text())
            self.assertEqual(graph["status"], "BLOCKED")
            self.assertEqual(graph["findings"][0]["code"], "DECISION_IMPACT_GAP")

    def test_runtime_fr_requires_configuration_runtime_pair_and_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD_DELIVERY.md"
            prd.write_text("""# PRD\n\n### FR-001 Runtime counter\n运行类型: RUNTIME\n触发后连续计数，真实生效并写入队列。\n\n#### Acceptance criteria\n- AC-001: 配置态 保存计数阈值\n- 验收类型: 配置态\n- AC-002: 运行态 连续计数写入队列\n- 验收类型: 运行态\n- 证据类型: QUEUE\n- 证据引用: queue-counter-event\n""", encoding="utf-8")
            out = root / "runtime.json"
            result = self.run_tool(RUNTIME, "--prd", prd, "--workflow-id", "WF-R", "--out", out)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["runtimeRequirements"], 1)
            self.assertEqual(json.loads(out.read_text())["requirements"][0]["runtimeAcs"], ["AC-002"])

            prd.write_text("""# PRD\n\n### FR-001 Runtime counter\n运行类型: RUNTIME\n触发后连续计数。\n\n#### Acceptance criteria\n- AC-001: 配置态 保存计数阈值\n- 验收类型: 配置态\n""", encoding="utf-8")
            self.run_tool(RUNTIME, "--prd", prd, "--workflow-id", "WF-R", "--out", out, expect=1)
            coverage = json.loads(out.read_text())
            self.assertEqual(coverage["status"], "BLOCKED")
            self.assertTrue(any("runtime-state AC" in finding["message"] for finding in coverage["findings"]))

    def test_external_contract_source_lock_and_artifact_checks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle"
            bundle.mkdir()
            source = root / "external-contract.md"
            source.write_text("external contract source\n", encoding="utf-8")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            profile = {
                "schemaVersion": 1, "profileId": "EXT-TEST", "version": "1.0.0", "title": "External test",
                "purpose": "Test the source lock and artifact contract.",
                "reviewTiming": "BEFORE_FINAL_SEAL",
                "sourceLock": {"skillId": "ext", "version": "1.0.0", "path": str(source), "sha256": source_hash},
                "appliesToProfiles": ["PRD_ONLY"],
                "artifacts": [{
                    "artifactId": "PRD", "path": "PRD_DELIVERY.md", "required": True, "format": "MARKDOWN",
                    "appliesToProfiles": ["PRD_ONLY"],
                    "checks": [
                        {"checkId": "PRD.FR", "kind": "REGEX", "value": "FR-[0-9]{3}", "description": "PRD has an FR."},
                        {"checkId": "PRD.AC", "kind": "REGEX", "value": "AC-[0-9]{3}", "description": "PRD has an AC."},
                    ],
                }],
            }
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            (bundle / "PRD_DELIVERY.md").write_text("FR-001 AC-001\n", encoding="utf-8")
            out = root / "external-result.json"
            result = self.run_tool(EXTERNAL, "--bundle", bundle, "--profile", profile_path, "--workflow-id", "WF-E", "--artifact-profile", "PRD_ONLY", "--out", out)
            self.assertEqual(result["status"], "PASS")

            source.write_text("drifted\n", encoding="utf-8")
            self.run_tool(EXTERNAL, "--bundle", bundle, "--profile", profile_path, "--workflow-id", "WF-E", "--artifact-profile", "PRD_ONLY", "--out", out, expect=1)
            blocked = json.loads(out.read_text())
            self.assertEqual(blocked["sourceLock"]["status"], "BLOCKED")
            self.assertTrue(any(item["code"] == "SOURCE_LOCK_DRIFT" for item in blocked["findings"]))

    def test_external_contract_resolves_prefixed_artifact_paths_and_optional_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bundle = root / "bundle"
            bundle.mkdir()
            source = root / "external-contract.md"
            source.write_text("external contract source\n", encoding="utf-8")
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            profile = {
                "schemaVersion": 1, "profileId": "EXT-PATTERN", "version": "1.0.0", "title": "External pattern test",
                "purpose": "Test optional artifacts and prefixed filenames.",
                "reviewTiming": "BEFORE_FINAL_SEAL",
                "sourceLock": {"skillId": "ext", "version": "1.0.0", "path": str(source), "sha256": source_hash},
                "appliesToProfiles": ["PRD_ONLY"],
                "artifacts": [
                    {
                        "artifactId": "PRD", "path": "PRD_DELIVERY.md", "pathPatterns": ["*PRD_DELIVERY*.md"],
                        "required": True, "format": "MARKDOWN", "appliesToProfiles": ["PRD_ONLY"],
                        "checks": [{"checkId": "PRD.FR", "kind": "REGEX", "value": "FR-[0-9]{3}", "description": "PRD has an FR."}],
                    },
                    {
                        "artifactId": "JIRA", "path": "Jira_Description.md", "pathPatterns": ["*Jira*Description*.md"],
                        "required": False, "format": "MARKDOWN", "appliesToProfiles": ["PRD_ONLY"],
                        "checks": [{"checkId": "JIRA.FR", "kind": "REGEX", "value": "FR-[0-9]{3}", "description": "Jira has an FR."}],
                    },
                ],
            }
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            (bundle / "业务需求_PRD_DELIVERY_v1.18.md").write_text("FR-001\n", encoding="utf-8")
            out = root / "external-result.json"
            result = self.run_tool(EXTERNAL, "--bundle", bundle, "--profile", profile_path, "--workflow-id", "WF-P", "--artifact-profile", "PRD_ONLY", "--out", out)
            self.assertEqual(result["status"], "PASS")
            report = json.loads(out.read_text())
            self.assertTrue(report["artifacts"][0]["path"].endswith("业务需求_PRD_DELIVERY_v1.18.md"))
            self.assertEqual(report["artifacts"][1]["status"], "SKIPPED")

    def test_runtime_ac_supplement_can_classify_existing_acs_without_rewriting_prd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prd = root / "PRD_DELIVERY.md"
            prd.write_text("""# PRD

### FR-001 Runtime rule
运行态条件生效。

### AC-001 Config rule
- 验收方式：页面保存校验

### AC-002 Runtime rule
- 验收方式：多轮会话执行 + 队列记录核对
""", encoding="utf-8")
            supplemental = root / "runtime-input.json"
            supplemental.write_text(json.dumps({
                "schemaVersion": 1,
                "sampleId": "DEMO",
                "requirements": [{
                    "frId": "FR-001",
                    "runtimeRelevant": True,
                    "configurationAcs": ["AC-001"],
                    "runtimeAcs": ["AC-002"],
                    "evidenceContracts": [{"acId": "AC-002", "evidenceTypes": ["QUEUE"], "evidenceRefs": ["PRD_DELIVERY.md#AC-002"]}],
                }],
            }), encoding="utf-8")
            out = root / "runtime.json"
            result = self.run_tool(RUNTIME, "--prd", prd, "--workflow-id", "WF-S", "--coverage-input", supplemental, "--out", out)
            self.assertEqual(result["status"], "PASS")
            report = json.loads(out.read_text())
            self.assertEqual(report["requirements"][0]["configurationAcs"], ["AC-001"])
            self.assertEqual(report["requirements"][0]["runtimeAcs"], ["AC-002"])
            self.assertEqual(report["coverageInputPath"], str(supplemental.resolve()))

    def test_pipeline_gate_blocks_runtime_ac_gap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = Path(td) / "requirement.md"
            requirement.write_text("""# Runtime Counter

- FR-001: 触发后连续计数并写入队列
- AC-001: 配置态 保存阈值
""", encoding="utf-8")
            process = subprocess.run([
                sys.executable, str(PIPELINE), "--run-root", str(root), "--requirement", str(requirement),
                "--workflow-id", "WF-HARDENING", "--requirement-name", "Hardening Demo",
                "--semantic-closure-mode", "off", "--runtime-ac-mode", "gate", "--external-contract-mode", "off",
                "--readiness-mode", "advisory",
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "HARDENING_BLOCKED")
            self.assertEqual(result["check"], "runtimeAcCoverage")


if __name__ == "__main__":
    unittest.main()
