import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ("scripts" if ROOT.name == "ai-native-delivery" else "tools")
EXPORT = SCRIPTS / "export_semantic_review_jobs.py"
CONSOLIDATE = SCRIPTS / "consolidate_semantic_review_results.py"
RUNNER = SCRIPTS / "run_semantic_review_jobs.py"


class SemanticReviewJobsTests(unittest.TestCase):
    def run_tool(self, executable, *args, expect=0):
        process = subprocess.run([sys.executable, str(executable), *map(str, args)], text=True, capture_output=True)
        self.assertEqual(process.returncode, expect, process.stdout + process.stderr)
        return json.loads(process.stdout) if process.stdout.strip() else {}

    def model(self):
        return {
            "schemaVersion": 1,
            "workflowId": "WF-1",
            "targetRevision": "r1",
            "artifactProfile": "PRD_ONLY",
            "source": {"prdPath": "/tmp/prd.md", "prdSha256": "a" * 64},
            "globalContracts": [
                {"contractId": "GC-PERMISSIONS", "kind": "PERMISSION", "title": "Permissions", "statement": "Owner can export.", "sourceRef": "/tmp/prd.md#permissions", "authority": "PRD", "status": "ACTIVE"}
            ],
            "units": [
                {"unitId": "FR-001", "kind": "FEATURE_SLICE", "title": "Export", "statement": "Owner exports.", "sourceRef": "/tmp/prd.md#fr-001", "authority": "PRD", "frIds": ["FR-001"], "acIds": [], "dependencies": ["GC-PERMISSIONS"], "sections": {}, "fields": {}, "content": "export"},
                {"unitId": "AC-001", "kind": "ACCEPTANCE_CRITERION", "title": "Export works", "statement": "File exists.", "sourceRef": "/tmp/prd.md#ac-001", "authority": "PRD", "frIds": ["FR-001"], "acIds": ["AC-001"], "dependencies": ["FR-001"], "sections": {}, "fields": {}, "content": "file"},
                {"unitId": "JOURNEY-G-001", "kind": "JOURNEY", "title": "G-001", "statement": "Owner exports data.", "sourceRef": "/tmp/prd.md#goals", "authority": "PRD", "frIds": ["FR-001"], "acIds": [], "dependencies": ["FR-001"], "sections": {}, "fields": {}, "content": "goal"},
            ],
            "edges": [
                {"edgeId": "EDGE-0001", "fromUnitId": "FR-001", "toUnitId": "AC-001", "relation": "VERIFIED_BY", "status": "ACTIVE", "evidenceRefs": ["/tmp/prd.md"]},
                {"edgeId": "EDGE-0002", "fromUnitId": "AC-001", "toUnitId": "FR-001", "relation": "VERIFIES", "status": "ACTIVE", "evidenceRefs": ["/tmp/prd.md"]},
                {"edgeId": "EDGE-0003", "fromUnitId": "JOURNEY-G-001", "toUnitId": "FR-001", "relation": "COVERS", "status": "ACTIVE", "evidenceRefs": ["/tmp/prd.md"]},
            ],
            "findings": [],
            "metrics": {"globalContracts": 1, "featureSlices": 1, "acceptanceCriteria": 1, "interactionContracts": 0, "journeys": 1, "edges": 3},
            "generatedAt": "2026-11-11T00:00:00Z",
        }

    def review(self, job_id, verdict="ACCEPTED", findings=None, blocking=0):
        return {
            "schemaVersion": 1,
            "reviewRunId": f"REV-{job_id}",
            "reviewPlanId": f"PLAN-{job_id}",
            "workflowId": "WF-1",
            "producerRole": "prd-producer",
            "reviewerRole": "delivery-reviewer",
            "reviewType": "independent",
            "targetHandoffId": "HO-1",
            "targetRevision": "r1",
            "independentContext": True,
            "verdict": verdict,
            "checks": [{"checkId": "SEMANTIC.LOCAL", "status": "passed" if verdict == "ACCEPTED" else "failed", "evidenceRefs": ["/tmp/prd.md"], "observed": "reviewed", "expected": "coherent"}],
            "findings": findings or [],
            "blockingCount": blocking,
            "evidenceRefs": ["/tmp/prd.md"],
            "checkedAt": "2026-11-11T00:00:00Z",
            "completionStatus": "complete",
            "reviewerContextId": f"ctx-{job_id}",
            "reviewerTranscript": f"/tmp/{job_id}.log",
        }

    def test_exports_layer_isolated_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "model.json"
            model.write_text(json.dumps(self.model()), encoding="utf-8")
            out = root / "jobs"
            result = self.run_tool(EXPORT, "--model", model, "--out-dir", out)
            self.assertEqual(result["status"], "READY")
            manifest = json.loads((out / "job-manifest.json").read_text(encoding="utf-8"))
            layers = {item["layer"] for item in manifest["jobs"]}
            self.assertEqual(layers, {"CONTRACT", "LOCAL", "EDGE", "GLOBAL"})
            ids = {item["jobId"] for item in manifest["jobs"]}
            self.assertIn("LOCAL-FR-001", ids)
            self.assertIn("JOURNEY-JOURNEY-G-001", ids)

    def test_consolidation_blocks_missing_jobs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "model.json"
            model.write_text(json.dumps(self.model()), encoding="utf-8")
            jobs = root / "jobs"
            self.run_tool(EXPORT, "--model", model, "--out-dir", jobs)
            results = root / "results"
            results.mkdir()
            (results / "GLOBAL-CONTRACTS.review.json").write_text(json.dumps(self.review("GLOBAL-CONTRACTS")), encoding="utf-8")
            out = root / "aggregate.json"
            self.run_tool(CONSOLIDATE, "--manifest", jobs / "job-manifest.json", "--results-dir", results, "--out", out, expect=1)
            aggregate = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(aggregate["status"], "BLOCKED")
            self.assertGreater(aggregate["blockingCount"], 0)
            self.assertTrue(aggregate["missingJobs"])

    def test_runner_executes_isolated_jobs_and_aggregates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "model.json"
            model.write_text(json.dumps(self.model()), encoding="utf-8")
            jobs = root / "jobs"
            self.run_tool(EXPORT, "--model", model, "--out-dir", jobs)
            fake = root / "fake_worker.py"
            fake.write_text(
                "import json,sys\n"
                "job=json.load(sys.stdin)\n"
                "print(json.dumps({'schemaVersion':1,'reviewRunId':'REV-'+job['jobId'],'reviewPlanId':job['jobId'],'workflowId':job['workflowId'],'producerRole':'prd-producer','reviewerRole':'semantic-consistency-reviewer','reviewType':'independent','targetHandoffId':job['jobId'],'targetRevision':job['targetRevision'],'independentContext':True,'verdict':'ACCEPTED','checks':[{'checkId':'SEMANTIC.LOCAL','status':'passed','evidenceRefs':['/tmp/prd.md'],'observed':'reviewed','expected':'coherent'}],'findings':[],'blockingCount':0,'evidenceRefs':['/tmp/prd.md'],'checkedAt':'2026-11-11T00:00:00Z','completionStatus':'complete','reviewerContextId':'ctx-'+job['jobId'],'reviewerTranscript':'/tmp/fake.log'}))\n",
                encoding="utf-8",
            )
            results = root / "results"
            aggregate = root / "aggregate.json"
            result = self.run_tool(RUNNER, "--manifest", jobs / "job-manifest.json", "--worker-command", sys.executable, fake, "--results-dir", results, "--out", aggregate)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["jobsCompleted"], result["jobsRequested"])
            self.assertEqual(json.loads(aggregate.read_text(encoding="utf-8"))["blockingCount"], 0)

    def test_consolidation_returns_nonblocking_findings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model = root / "model.json"
            model.write_text(json.dumps(self.model()), encoding="utf-8")
            jobs = root / "jobs"
            self.run_tool(EXPORT, "--model", model, "--out-dir", jobs)
            manifest = json.loads((jobs / "job-manifest.json").read_text(encoding="utf-8"))
            results = root / "results"
            results.mkdir()
            for job in manifest["jobs"]:
                findings = [{"findingId": "F-1", "severity": "NON_BLOCKING", "title": "Minor ambiguity", "evidenceRefs": ["/tmp/prd.md"], "impact": "low", "closeCondition": "clarify", "owner": "prd-producer"}] if job["jobId"] == "LOCAL-FR-001" else []
                verdict = "ACCEPTED_WITH_ACTIONS" if findings else "ACCEPTED"
                (results / f"{job['jobId']}.review.json").write_text(json.dumps(self.review(job["jobId"], verdict, findings)), encoding="utf-8")
            out = root / "aggregate.json"
            result = self.run_tool(CONSOLIDATE, "--manifest", jobs / "job-manifest.json", "--results-dir", results, "--out", out)
            aggregate = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "PASS_WITH_NONBLOCKING")
            self.assertEqual(aggregate["blockingCount"], 0)


if __name__ == "__main__":
    unittest.main()
