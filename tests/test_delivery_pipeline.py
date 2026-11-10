import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
PIPELINE = ROOT / SCRIPTS / "delivery_pipeline.py"


class DeliveryPipelineTests(unittest.TestCase):
    def run_pipeline(self, root, requirement, profile, prototype_status, ui_ownership, expect=0, *extra):
        process = subprocess.run([
            sys.executable, str(PIPELINE), "--run-root", str(root), "--requirement", str(requirement),
            "--workflow-id", "WF-PIPELINE", "--requirement-name", "Pipeline Demo", "--requirement-id", "PIPE-1",
            "--artifact-profile", profile, "--prototype-status", prototype_status, "--ui-ownership", ui_ownership,
            *map(str, extra),
        ], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def requirement(self, root):
        path = root / "requirement.md"
        path.write_text("""# Scene Intent Feature

- FR-001: user can view result
- AC-001: result is visible

## Permissions
- task-owner ALLOWED view result
- viewer DENIED edit result

## States
- default: precondition defined by PRD and reachable from home
""", encoding="utf-8")
        return path

    def assert_package(self, root, result, profile):
        self.assertEqual(result["status"], "PACKAGE_READY")
        kinds = {item["kind"] for item in result["artifacts"]}
        self.assertTrue({"PRD", "OVERVIEW", "JIRA_DESCRIPTION"} <= kinds)
        if profile != "PRD_ONLY":
            self.assertIn("PROTOTYPE", kinds)
        self.assertTrue((root / "01-delivery" / "PRD_DELIVERY.md").exists())
        self.assertTrue((root / "01-delivery" / "Jira_Description.md").exists())
        quality = json.loads((root / ".agents" / "quality" / "delivery-quality-exit.json").read_text())
        self.assertEqual(quality["status"], "PASS")
        handoff = json.loads(Path(result["handoff"]).read_text())
        self.assertEqual(handoff["workflowId"], "WF-PIPELINE")
        complete_path = Path(result["completeGate"])
        if not complete_path.exists():
            report = json.loads((root / ".agents" / "quality" / "delivery-pipeline-report.json").read_text())
            self.fail(f"missing complete gate {complete_path}; invocation={report.get('completeGateInvocation')}; quality files={sorted(str(item) for item in (root / '.agents' / 'quality').glob('*'))}")
        complete = json.loads(complete_path.read_text())
        failed = {item["checkId"] for item in complete["checks"] if item["status"] == "failed"}
        self.assertIn("COMPLETE.P0_5_BENCHMARK", failed)
        self.assertIn("COMPLETE.REPLAY", failed)
        self.assertNotIn("COMPLETE.EVIDENCE_FILES", failed)
        self.assertNotIn("COMPLETE.SEMANTIC_REVIEW", failed)

    def test_prd_only_pipeline_builds_all_non_ui_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            result = self.run_pipeline(root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE")
            self.assert_package(root, result, "PRD_ONLY")

    def test_pipeline_executes_research_queries_before_decision_readiness(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            adapter = Path(td) / "adapter.py"
            adapter.write_text('import json,sys\njson.load(sys.stdin)\nprint(json.dumps({"status":"OK","records":[{"sourceRef":"jira://PIPE-1","status":"CONFIRMED","claims":[{"claim":"existing evidence","confidence":"HIGH"}],"evidenceRefs":["jira://PIPE-1"]}]}))\n', encoding="utf-8")
            request = {"schemaVersion": 1, "workflowId": "WF-PIPELINE", "requirementKey": "PIPE-1", "clues": [{"clueId": "C-1", "clue": "existing behavior", "clueType": "EXISTING_BEHAVIOR", "queries": [{"queryId": "Q-1", "source": "JIRA", "query": "PIPE-1", "purpose": "verify"}]}], "budget": {"maxQueries": 2, "timeoutSeconds": 2, "retries": 0, "backoffSeconds": 0}}
            request_path = Path(td) / "request.json"; request_path.write_text(json.dumps(request), encoding="utf-8")
            adapter_config = Path(td) / "adapters.json"; adapter_config.write_text(json.dumps({"schemaVersion": 1, "adapters": [{"source": "JIRA", "command": [sys.executable, str(adapter)]}]}), encoding="utf-8")
            result = self.run_pipeline(root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 0, "--research-request", request_path, "--research-adapters", adapter_config)
            self.assertEqual(result["status"], "PACKAGE_READY")
            query_result = json.loads((root / ".agents" / "research" / "query-result.json").read_text())
            self.assertEqual(query_result["status"], "COMPLETE")
            package = json.loads((root / ".agents" / "quality" / "package-evidence.json").read_text())
            self.assertIn("researchQueryResult", package)

    def test_external_production_artifacts_are_validated_and_packaged(self):
        prd_markdown = """# PRD_DELIVERY

## Requirement Summary
User views a result.

## Functional Requirements
- FR-001: User views the result after submission.

## Acceptance Criteria
- AC-001: Result visibility is verified for FR-001.

## Permissions
- task-owner ALLOWED view result
- viewer DENIED edit result

## States
- default: reachable from the task page with precondition defined

## Exceptions and Recovery
- unavailable result shows a retry action and preserves task context

## Non-Goals
- No new permission model.
"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "run"
            requirement = self.requirement(base)
            worker = base / "semantic_prd_worker.py"
            worker.write_text('''import hashlib,json,os,subprocess,sys
from pathlib import Path
worker=Path(os.environ["TEST_DETERMINISTIC_WORKER"])
p=subprocess.run([sys.executable,str(worker)],env=os.environ)
if p.returncode: raise SystemExit(p.returncode)
manifest=json.loads(Path(os.environ["AI_NATIVE_TASK_MANIFEST"]).read_text())
if manifest.get("role") in {"prd-producer","prd-repair-agent"}:
    result_path=Path(os.environ["AI_NATIVE_RESULT_PATH"])
    payload=json.loads(result_path.read_text())
    artifact=Path(payload["prdArtifactPath"])
    artifact.write_text(os.environ["TEST_PRD_MARKDOWN"],encoding="utf-8")
    payload["producerMode"]="semantic"
    payload["prdArtifactSha256"]=hashlib.sha256(artifact.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
''', encoding="utf-8")
            source = base / "external"
            source.mkdir()
            prd_hash = hashlib.sha256(prd_markdown.encode()).hexdigest()
            prototype_text = '<!doctype html><html><body><section data-ai-id="result-panel" data-ai-fr="FR-001" data-ai-ac="AC-001" data-ai-state="default" data-ai-permission-edge="P-1"><h1>Result</h1><button>Retry</button></section></body></html>\n'
            (source / "Prototype.html").write_text(prototype_text, encoding="utf-8")
            manifest = {"schemaVersion": 1, "workflowId": "WF-PIPELINE", "prototypeRevision": "r1", "prototypeHash": hashlib.sha256(prototype_text.encode()).hexdigest(), "elements": [{"uiElementId": "result-panel", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "Result", "states": ["default"], "permissions": ["task-owner allowed"]}]}
            (source / "prototype-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            tabs = ["方案摘要", "背景与现状", "目标与范围", "功能与规则", "流程与状态", "验收与风险"]
            (source / "Overview.html").write_text('<!doctype html><html><head><meta name="source-prd-sha256" content="' + prd_hash + '"></head><body>' + ''.join(f'<section><h2>{tab}</h2><p>FR-001 AC-001</p></section>' for tab in tabs) + '<p>revision r1</p></body></html>', encoding="utf-8")
            (source / "Jira_Description.md").write_text(f'<!-- source-prd-sha256: {prd_hash} -->\n## 1. 背景\nResult\n## 2. 现状\nManual\n## 3. 目标\nOnline\n## 4. 功能点\n- FR-001: User views the result.\n', encoding="utf-8")
            old = os.environ.get("TEST_PRD_MARKDOWN")
            os.environ["TEST_PRD_MARKDOWN"] = prd_markdown
            os.environ["TEST_DETERMINISTIC_WORKER"] = str(ROOT / SCRIPTS / "deterministic_worker.py")
            try:
                result = self.run_pipeline(root, requirement, "PRD_PLUS_PROTOTYPE", "TRIGGERED", "LOCAL", 0, "--worker", worker, "--artifact-source-dir", source, "--producer-mode", "provided")
            finally:
                if old is None: os.environ.pop("TEST_PRD_MARKDOWN", None)
                else: os.environ["TEST_PRD_MARKDOWN"] = old
                os.environ.pop("TEST_DETERMINISTIC_WORKER", None)
            self.assertEqual(result["status"], "PACKAGE_READY")
            self.assertEqual(result["prdProducerMode"], "semantic")
            self.assertEqual(result["downstreamProducerMode"], "provided")
            self.assertEqual(result["artifactQualityLevel"], "PRODUCTION_CANDIDATE")
            quality = json.loads(Path(result["artifactQuality"]).read_text())
            self.assertTrue(quality["productionCandidate"])

    def test_pair_pipeline_builds_prototype_pair_semantic_review_and_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            result = self.run_pipeline(root, requirement, "PRD_PLUS_PROTOTYPE", "TRIGGERED", "LOCAL")
            self.assert_package(root, result, "PRD_PLUS_PROTOTYPE")
            pair = json.loads((root / ".agents" / "m2" / "artifact-pair.json").read_text())
            self.assertEqual(pair["pairStatus"], "SYNCED")
            semantic = json.loads(Path(result["semanticReview"]).read_text())
            self.assertEqual(semantic["verdict"], "ACCEPTED")
            self.assertTrue(any(check["checkId"] == "SEMANTIC.COVERAGE" for check in semantic["checks"]))


if __name__ == "__main__":
    unittest.main()
