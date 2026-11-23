import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
PIPELINE = ROOT / SCRIPTS / "delivery_pipeline.py"
REDERIVE = ROOT / SCRIPTS / "rederive_delivery_evidence.py"


class DeliveryPipelineTests(unittest.TestCase):
    def run_pipeline(self, root, requirement, profile, prototype_status, ui_ownership, expect=0, *extra):
        process = subprocess.run([
            sys.executable, str(PIPELINE), "--run-root", str(root), "--requirement", str(requirement),
            "--workflow-id", "WF-PIPELINE", "--requirement-name", "Pipeline Demo", "--requirement-id", "PIPE-1",
            "--artifact-profile", profile, "--prototype-status", prototype_status, "--ui-ownership", ui_ownership,
            "--readiness-mode", "advisory",
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
        report = json.loads((root / ".agents" / "quality" / "delivery-pipeline-report.json").read_text())
        self.assertIn(report.get("deliveryControlPlaneStatus"), {"PASS", "SKIPPED"})
        if report.get("deliveryControlPlaneStatus") == "PASS":
            control_plane = json.loads(Path(report["deliveryControlPlane"]).read_text())
            self.assertEqual(control_plane["status"], "PASS")
            orchestration = json.loads((root / ".agents" / "orchestration.json").read_text())
            self.assertEqual(orchestration["currentStage"], "DELIVERY_SEALED")
            self.assertIn(".agents/handoffs/delivery-ready.handoff.json", orchestration["handoffs"])
        self.assertIn(report.get("generationContractStatus"), {"READY", "READY_WITH_ACTIONS", "BLOCKED", "SKIPPED"})
        self.assertTrue(Path(report["generationContract"]).exists())
        self.assertIn(report.get("semanticDecompositionStatus"), {"PASS", "PASS_WITH_NONBLOCKING", "NEEDS_FIX", "BLOCKED", "SKIPPED"})
        self.assertTrue(Path(report["semanticModel"]).exists())
        self.assertTrue(Path(report["semanticIntegrationReview"]).exists())
        self.assertTrue(Path(report["semanticReviewJobs"]).exists())
        self.assertIn(report.get("semanticAggregateStatus"), {"PASS", "PASS_WITH_NONBLOCKING", "NEEDS_FIX", "BLOCKED", "SKIPPED"})
        cost_ledger_path = Path(result["costRevisionLedger"])
        self.assertTrue(cost_ledger_path.is_file())
        cost_ledger = json.loads(cost_ledger_path.read_text())
        self.assertIn(cost_ledger["status"], {"COMPLETE", "PARTIAL", "INSUFFICIENT"})
        procedure_path = Path(result["deliveryOperatingProcedure"])
        self.assertTrue(procedure_path.is_file())
        procedure = json.loads(procedure_path.read_text())
        self.assertIn(procedure["status"], {"READY", "READY_WITH_ACTIONS"})
        self.assertEqual(procedure["workflowId"], "WF-PIPELINE")
        self.assertGreaterEqual(procedure["metrics"]["toolRoutes"], 1)
        package = json.loads((root / ".agents" / "quality" / "package-evidence.json").read_text())
        self.assertEqual(package["revision"], result["finalRevision"])
        self.assertEqual(package["costRevisionLedgerPath"], str(cost_ledger_path))
        self.assertEqual(package["costRevisionLedgerSha256"], hashlib.sha256(cost_ledger_path.read_bytes()).hexdigest())
        self.assertEqual(package["deliveryOperatingProcedurePath"], str(procedure_path))
        self.assertEqual(package["deliveryOperatingProcedureSha256"], hashlib.sha256(procedure_path.read_bytes()).hexdigest())
        episode_path = Path(result["projectEpisode"])
        self.assertTrue(episode_path.is_file())
        episode = json.loads(episode_path.read_text())
        self.assertEqual(episode["workflowId"], "WF-PIPELINE")
        self.assertEqual(episode["revision"], result["finalRevision"])
        self.assertEqual(episode["trainingEligibility"]["eligible"], False)
        self.assertIn(episode["status"], {"COMPLETE", "PARTIAL", "BLOCKED"})
        self.assertEqual(package["projectEpisodePath"], str(episode_path))
        self.assertEqual(package["projectEpisodeSha256"], hashlib.sha256(episode_path.read_bytes()).hexdigest())
        self.assertFalse(package["projectEpisodeTrainingEligible"])
        surface_path = Path(result["collaborationSurface"])
        self.assertTrue(surface_path.is_file())
        self.assertTrue(Path(result["collaborationSurfaceMarkdown"]).is_file())
        surface = json.loads(surface_path.read_text())
        self.assertEqual(surface["workflowId"], "WF-PIPELINE")
        self.assertEqual(surface["revision"], result["finalRevision"])
        self.assertEqual(surface["authority"]["gateAuthority"], "UNCHANGED")
        self.assertEqual(surface["authority"]["trainingAuthority"], "NONE")
        self.assertIn(surface["status"], {"READY", "ACTION_REQUIRED", "BLOCKED"})
        self.assertEqual(package["collaborationSurfacePath"], str(surface_path))
        self.assertEqual(package["collaborationSurfaceSha256"], hashlib.sha256(surface_path.read_bytes()).hexdigest())
        rehearsal_path = Path(result["rehearsalCorpus"])
        self.assertTrue(rehearsal_path.is_file())
        self.assertTrue(Path(result["rehearsalCorpusMarkdown"]).is_file())
        rehearsal = json.loads(rehearsal_path.read_text())
        self.assertEqual(rehearsal["workflowId"], "WF-PIPELINE")
        self.assertEqual(rehearsal["revision"], result["finalRevision"])
        self.assertFalse(rehearsal["authority"]["releaseEligible"])
        self.assertFalse(rehearsal["authority"]["trainingEligible"])
        self.assertGreaterEqual(rehearsal["metrics"]["scenarioCount"], 1)
        self.assertEqual(package["rehearsalCorpusPath"], str(rehearsal_path))
        self.assertEqual(package["rehearsalCorpusSha256"], hashlib.sha256(rehearsal_path.read_bytes()).hexdigest())

    def test_pipeline_audit_gate_builds_candidate_seal_before_finalization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            result = self.run_pipeline(
                root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 0,
                "--audit-mode", "gate",
                "--audit-profile", ROOT / "config" / "audit-profiles" / "prd-only.json",
                "--audit-crosswalk", ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json",
                "--audit-worker", sys.executable, ROOT / "tests" / "fixtures" / "audit" / "fake_audit_worker.py",
            )
            self.assertEqual(result["status"], "PACKAGE_READY")
            dd = root / "01-delivery" / ".delivery"
            self.assertTrue((dd / "candidate-seal.json").exists())
            seal = json.loads((dd / "candidate-seal.json").read_text())
            self.assertTrue((root / "01-delivery" / seal["frozenCopy"]).exists())
            self.assertEqual(result["auditStageStatus"], "AUDIT_PASS")

    def test_pipeline_bounded_repair_rederives_and_propagates_final_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            audit_worker = ROOT / "tests" / "fixtures" / "audit" / "cycle_audit_worker.py"
            repair_worker = ROOT / "tests" / "fixtures" / "audit" / "cycle_repair_worker.py"
            result = self.run_pipeline(
                root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 0,
                "--audit-mode", "gate",
                "--audit-profile", ROOT / "config" / "audit-profiles" / "prd-only.json",
                "--audit-crosswalk", ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json",
                "--audit-worker", sys.executable, audit_worker.resolve(),
                "--repair-mode", "bounded",
                "--repair-worker", sys.executable, repair_worker.resolve(),
                "--repair-rederive-mode", "gate",
            )
            self.assertEqual(result["status"], "PACKAGE_READY", result)
            self.assertEqual(result["auditStageStatus"], "AUDIT_PASS")
            self.assertEqual(result["finalRevision"], "r2")
            self.assertEqual(result["findingMetrics"]["openBlocking"], 0)
            dd = root / "01-delivery" / ".delivery"
            self.assertEqual(json.loads((dd / "candidate-seal.json").read_text())["revision"], "r2")
            semantic = json.loads((dd / "semantic-consistency-input.json").read_text())
            self.assertEqual(semantic["targetRevision"], "r2")
            orchestrator_semantic = json.loads((root / ".agents" / "context" / "semantic-final-input.json").read_text())
            self.assertEqual(orchestrator_semantic["targetRevision"], "r2")
            orchestrator_review = json.loads((root / ".agents" / "reviews" / "SEMANTIC-FINAL-PACKAGE-REVIEW.review.json").read_text())
            self.assertEqual(orchestrator_review["targetRevision"], "r2")
            plan = json.loads((root / ".agents" / "delivery-plan.json").read_text())
            self.assertEqual(plan["finalDeliveryRevision"], "r2")
            ledger = json.loads((dd / "findings.json").read_text())
            self.assertEqual(ledger["currentRevision"], "r2")
            self.assertEqual(ledger["metrics"]["resolved"], 1)
            handoff = json.loads(Path(result["handoff"]).read_text())
            self.assertEqual(handoff["revision"], "r2")
            package = json.loads((root / ".agents" / "quality" / "package-evidence.json").read_text())
            self.assertEqual(package["revision"], "r2")
            self.assertEqual(package["costRevisionLedgerStatus"], "PARTIAL")
            self.assertTrue(Path(package["costRevisionLedgerPath"]).is_file())
            cost_ledger = json.loads(Path(package["costRevisionLedgerPath"]).read_text())
            self.assertEqual(cost_ledger["finalRevision"], "r2")
            self.assertEqual(cost_ledger["metrics"]["revisionCount"], 2)
            self.assertEqual(cost_ledger["metrics"]["repairRounds"], 1)
            self.assertTrue(any(item["revision"] == "r2" for item in cost_ledger["revisions"]))

    def test_pipeline_advisory_challenger_records_detected_scenarios(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            challenger_worker = ROOT / "tests" / "fixtures" / "challenger" / "fake_challenger_worker.py"
            result = self.run_pipeline(
                root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 0,
                "--challenger-mode", "advisory",
                "--challenger-worker", sys.executable, challenger_worker.resolve(),
            )
            self.assertEqual(result["status"], "PACKAGE_READY", result)
            self.assertEqual(result["finalRevision"], "r1")
            self.assertEqual(result["challengerMode"], "advisory")
            challenge = json.loads(Path(result["challengerRun"]).read_text())
            self.assertEqual(challenge["status"], "COMPLETE")
            self.assertEqual(challenge["outcome"], "ALL_DETECTED")
            self.assertFalse(challenge["authority"]["releaseEligible"])
            self.assertFalse(challenge["authority"]["trainingEligible"])
            package = json.loads((root / ".agents" / "quality" / "package-evidence.json").read_text())
            self.assertEqual(package["challengerOutcome"], "ALL_DETECTED")
            self.assertEqual(package["challengerRunPath"], result["challengerRun"])
            self.assertGreater(package["challengerDetectedCount"], 0)
            complete = json.loads(Path(result["completeGate"]).read_text())
            self.assertNotIn("COMPLETE.EVIDENCE_FILES", {item["checkId"] for item in complete["checks"] if item["status"] == "failed"})

    def test_pipeline_gate_challenger_blocks_missed_scenarios(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            challenger_worker = ROOT / "tests" / "fixtures" / "challenger" / "fake_challenger_worker.py"
            with mock.patch.dict(os.environ, {"FAKE_CHALLENGER_MISSED": "1"}):
                result = self.run_pipeline(
                    root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 1,
                    "--challenger-mode", "gate",
                    "--challenger-worker", sys.executable, challenger_worker.resolve(),
                )
            self.assertEqual(result["status"], "CHALLENGER_GATE_BLOCKED")
            self.assertEqual(result["challengerOutcome"], "GAPS_FOUND")
            challenge = json.loads(Path(result["challenger"]).read_text())
            self.assertEqual(challenge["outcome"], "GAPS_FOUND")
            self.assertEqual(challenge["status"], "COMPLETE")
            report = json.loads((root / ".agents" / "quality" / "delivery-pipeline-report.json").read_text())
            self.assertEqual(report["status"], "CHALLENGER_GATE_BLOCKED")

    def test_rederivation_reuses_unchanged_semantic_review(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            self.run_pipeline(root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE")
            bundle = root / "01-delivery"
            dd = bundle / ".delivery"
            dd.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / ".agents" / "context" / "semantic-final-input.json", dd / "semantic-consistency-input.json")
            shutil.copyfile(root / ".agents" / "reviews" / "SEMANTIC-FINAL-PACKAGE-REVIEW.review.json", dd / "semantic-consistency-review.json")
            out = root / ".agents" / "audit" / "rederive-r2.json"
            process = subprocess.run([
                sys.executable, str(REDERIVE), "--bundle", str(bundle), "--workflow-id", "WF-PIPELINE",
                "--revision", "r2", "--artifact-profile", "PRD_ONLY", "--semantic-mode", "gate",
                "--semantic-source", "auto", "--out", str(out),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "PASS")
            review = json.loads((dd / "semantic-consistency-review.json").read_text())
            self.assertEqual(review["verdict"], "ACCEPTED")
            self.assertEqual(review["targetRevision"], "r2")
            semantic_step = next(item for item in report["steps"] if item["step"] == "semanticReview")
            self.assertEqual(semantic_step["reportedStatus"], "ACCEPTED_REUSED_AND_REBOUND")

    def test_rederivation_uses_external_semantic_producer_and_refreshes_declarations(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            self.run_pipeline(root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE")
            bundle = root / "01-delivery"
            dd = bundle / ".delivery"
            dd.mkdir(parents=True, exist_ok=True)
            producer = Path(td) / "semantic_producer.py"
            producer.write_text(f'''import json, subprocess, sys
from pathlib import Path
request = json.load(sys.stdin)
out = Path(request["outputDir"])
cmd = [sys.executable, {str((ROOT / SCRIPTS / "build_semantic_evidence.py").resolve())!r}, "--prd", request["inputs"]["prd"], "--workflow-id", request["workflowId"], "--revision", request["revision"], "--out", str(out / "semantic-evidence.json")]
subprocess.run(cmd, check=True)
obligations = json.loads(Path(request["generationObligationsPath"]).read_text())
declarations = []
for item in obligations.get("obligations", []):
    if not item.get("declarationRequired"):
        continue
    declarations.append({{
        "obligationId": item["obligationId"], "ruleId": item["ruleId"], "producerRole": item["ownerRole"],
        "producerTaskId": "external-semantic-producer", "status": "DECLARED",
        "artifact": "semantic-evidence.json", "location": str(out / "semantic-evidence.json"),
        "evidenceRefs": [str(out / "semantic-evidence.json")], "notes": "external producer declaration",
    }})
(out / "obligation-declarations.json").write_text(json.dumps({{"declarations": declarations}}, ensure_ascii=False), encoding="utf-8")
''', encoding="utf-8")
            registry = Path(td) / "producer-registry.json"
            registry.write_text(json.dumps({"schemaVersion": 1, "producers": [{
                "kind": "semantic-evidence", "mode": "semantic",
                "command": [sys.executable, str(producer)],
                "requiredArtifacts": ["semantic-evidence.json"],
            }]}), encoding="utf-8")
            out = root / ".agents" / "audit" / "rederive-r2.json"
            process = subprocess.run([
                sys.executable, str(REDERIVE), "--bundle", str(bundle), "--workflow-id", "WF-PIPELINE",
                "--revision", "r2", "--artifact-profile", "PRD_ONLY", "--semantic-mode", "gate",
                "--semantic-source", "regenerate", "--producer-registry", str(registry),
                "--requirement", str(requirement), "--out", str(out),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads(out.read_text())
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(any(item["step"] == "semanticProducer" and item["status"] == "PASS" for item in report["steps"]))
            semantic = json.loads((dd / "semantic-consistency-input.json").read_text())
            self.assertEqual(semantic["targetRevision"], "r2")
            declarations = json.loads((dd / "obligation-declarations.json").read_text())
            self.assertEqual(declarations["targetRevision"], "r2")
            validation = json.loads((dd / "obligation-declarations-validation.json").read_text())
            self.assertEqual(validation["status"], "PASS")
            self.assertGreater(validation["declaredRequired"], 0)

    def test_pipeline_bounded_repair_uses_external_semantic_producer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            producer = Path(td) / "semantic_producer.py"
            producer.write_text(f'''import json, subprocess, sys
from pathlib import Path
request = json.load(sys.stdin)
out = Path(request["outputDir"])
subprocess.run([sys.executable, {str((ROOT / SCRIPTS / "build_semantic_evidence.py").resolve())!r}, "--prd", request["inputs"]["prd"], "--workflow-id", request["workflowId"], "--revision", request["revision"], "--out", str(out / "semantic-evidence.json")], check=True)
obligations = json.loads(Path(request["generationObligationsPath"]).read_text())
declarations = [{{"obligationId": item["obligationId"], "ruleId": item["ruleId"], "producerRole": item["ownerRole"], "producerTaskId": "external-semantic-producer", "status": "DECLARED", "artifact": "semantic-evidence.json", "location": str(out / "semantic-evidence.json"), "evidenceRefs": [str(out / "semantic-evidence.json")]}} for item in obligations.get("obligations", []) if item.get("declarationRequired")]
(out / "obligation-declarations.json").write_text(json.dumps({{"declarations": declarations}}, ensure_ascii=False), encoding="utf-8")
''', encoding="utf-8")
            registry = Path(td) / "producer-registry.json"
            registry.write_text(json.dumps({"schemaVersion": 1, "producers": [{"kind": "semantic-evidence", "mode": "semantic", "command": [sys.executable, str(producer)], "requiredArtifacts": ["semantic-evidence.json"]}]}), encoding="utf-8")
            audit_worker = ROOT / "tests" / "fixtures" / "audit" / "cycle_audit_worker.py"
            repair_worker = ROOT / "tests" / "fixtures" / "audit" / "cycle_repair_worker.py"
            result = self.run_pipeline(
                root, requirement, "PRD_ONLY", "NOT_TRIGGERED", "NONE", 0,
                "--audit-mode", "gate",
                "--audit-profile", ROOT / "config" / "audit-profiles" / "prd-only.json",
                "--audit-crosswalk", ROOT / "config" / "audit-crosswalk" / "delivery-toolbox-v2.json",
                "--audit-worker", sys.executable, audit_worker.resolve(),
                "--repair-mode", "bounded",
                "--repair-worker", sys.executable, repair_worker.resolve(),
                "--repair-rederive-mode", "gate",
                "--producer-registry", registry,
            )
            self.assertEqual(result["status"], "PACKAGE_READY", result)
            self.assertEqual(result["finalRevision"], "r2")
            producer_result = root / ".agents" / "producers" / "semantic-evidence-r2.result.json"
            self.assertTrue(producer_result.exists())
            self.assertEqual(json.loads(producer_result.read_text())["status"], "PASS")
            declarations = json.loads((root / "01-delivery" / ".delivery" / "obligation-declarations.json").read_text())
            self.assertEqual(declarations["targetRevision"], "r2")
    def test_pipeline_gate_blocks_when_formal_readiness_is_absent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "run"
            requirement = self.requirement(Path(td))
            process = subprocess.run([
                sys.executable, str(PIPELINE), "--run-root", str(root), "--requirement", str(requirement),
                "--workflow-id", "WF-PIPELINE", "--requirement-name", "Pipeline Demo", "--requirement-id", "PIPE-1",
                "--artifact-profile", "PRD_ONLY", "--prototype-status", "NOT_TRIGGERED", "--ui-ownership", "NONE",
                "--readiness-mode", "gate",
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "PACKAGE_BLOCKED")
            self.assertFalse(result["readiness"]["designReady"])
            self.assertTrue(Path(result["readiness"]["readinessPath"]).exists())
            report = json.loads(Path(result["report"]).read_text())
            self.assertEqual(report["status"], "PACKAGE_BLOCKED")
            self.assertFalse(report["designReady"])

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
            (source / "runtime-evidence.json").write_text(json.dumps({
                "schemaVersion": 2, "status": "PASS", "executionMode": "real-browser",
                "runtimeEvidenceLevel": "REAL_BROWSER", "prototypePath": str(source / "Prototype.html"),
                "prototypeHash": hashlib.sha256(prototype_text.encode()).hexdigest(),
                "consoleErrors": [], "pageErrors": [], "requestFailures": [], "checks": [],
                "checkedAt": "2026-11-10T00:00:00Z",
            }), encoding="utf-8")
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
            if result["artifactQualityLevel"] != "PRODUCTION_CANDIDATE":
                self.fail((Path(result["artifactQuality"]).read_text() if Path(result["artifactQuality"]).exists() else "missing quality"))
            self.assertEqual(result["artifactQualityLevel"], "PRODUCTION_CANDIDATE")
            quality = json.loads(Path(result["artifactQuality"]).read_text())
            self.assertTrue(quality["productionCandidate"])
            report = json.loads((root / ".agents" / "quality" / "delivery-pipeline-report.json").read_text())
            self.assertIn(report.get("deliveryControlPlaneStatus"), {"PASS", "SKIPPED"})

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
