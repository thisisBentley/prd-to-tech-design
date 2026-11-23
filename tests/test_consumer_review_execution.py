import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_consumer_acceptance import ConsumerAcceptanceTests

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILDER = TOOLS / "build_consumer_review_jobs.py"
RUNNER = TOOLS / "run_consumer_review_jobs.py"
POLICY = ROOT / "config" / "consumer-acceptance" / "policy-v1.json"


def invoke(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


class ConsumerReviewExecutionTests(unittest.TestCase):
    def fixture(self, root: Path):
        request_path, request, _ = ConsumerAcceptanceTests().fixture(root)
        request["artifacts"].pop("productManagerReview", None)
        request["artifacts"].pop("architectReview", None)
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")

        worker = root / "fake_consumer_worker.py"
        worker.write_text(
            "import json, os\n"
            "from pathlib import Path\n"
            "task = json.loads(Path(os.environ['AI_NATIVE_TASK_MANIFEST']).read_text())\n"
            "transcript = Path(os.environ['AI_NATIVE_TRANSCRIPT_PATH'])\n"
            "transcript.parent.mkdir(parents=True, exist_ok=True)\n"
            "transcript.write_text('independent consumer execution\\n')\n"
            "inputs = [item['path'] for item in task.get('inputs', [])]\n"
            "result = {\n"
            " 'schemaVersion': 1,\n"
            " 'reviewRunId': task['reviewRunId'],\n"
            " 'reviewPlanId': task['reviewPlanId'],\n"
            " 'workflowId': task['workflowId'],\n"
            " 'producerRole': task['producerRole'],\n"
            " 'reviewerRole': task['role'],\n"
            " 'reviewType': 'consumer',\n"
            " 'targetHandoffId': task['targetHandoffId'],\n"
            " 'targetRevision': task['targetRevision'],\n"
            " 'independentContext': True,\n"
            " 'reviewerContextId': task['contextId'],\n"
            " 'reviewerTranscript': os.environ['AI_NATIVE_TRANSCRIPT_PATH'],\n"
            " 'reviewerRuntimeRecordPath': os.environ['AI_NATIVE_RUNTIME_RECORD_PATH'],\n"
            " 'verdict': 'ACCEPTED',\n"
            " 'completionStatus': 'complete',\n"
            " 'checks': [{'checkId': 'FAKE.CONSUMER.REVIEW', 'status': 'passed', 'evidenceRefs': inputs[:1], 'observed': 'reviewed', 'expected': 'reviewed'}],\n"
            " 'findings': [], 'blockingCount': 0, 'evidenceRefs': inputs[:2],\n"
            " 'checkedAt': '2026-11-23T00:00:00+00:00'\n"
            "}\n"
            "Path(os.environ['AI_NATIVE_RESULT_PATH']).write_text(json.dumps(result, ensure_ascii=False))\n",
            encoding="utf-8",
        )
        jobs_dir = root / "consumer-review-jobs"
        invoke([BUILDER, "--request", request_path, "--out-dir", jobs_dir])
        return request_path, jobs_dir, worker

    def test_runner_executes_both_jobs_and_evaluates_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, jobs_dir, worker = self.fixture(root)
            out_dir = root / "consumer-execution"
            out = root / "consumer-execution.json"
            result = invoke([
                RUNNER,
                "--request", request_path,
                "--manifest", jobs_dir / "manifest.json",
                "--policy", POLICY,
                "--out-dir", out_dir,
                "--out", out,
                "--worker", sys.executable, worker,
            ])
            execution = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(execution["status"], "PASS")
            self.assertEqual(len(execution["jobs"]), 2)
            self.assertTrue(all(item["status"] == "SUCCEEDED" for item in execution["jobs"]))
            report = json.loads(Path(execution["consumerReport"]).read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["m7ExitEvidenceEligible"])
            for item in execution["jobs"]:
                self.assertTrue(Path(item["runtimeRecord"]).is_file())
                self.assertTrue(Path(item["reviewResult"]).is_file())
                self.assertTrue(Path(item["transcript"]).is_file())

    def test_runner_fails_closed_on_source_task_hash_drift(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, jobs_dir, worker = self.fixture(root)
            task = jobs_dir / "product-manager-consumer.task.json"
            task.write_text(task.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            out = root / "consumer-execution.json"
            result = invoke([
                RUNNER,
                "--request", request_path,
                "--manifest", jobs_dir / "manifest.json",
                "--policy", POLICY,
                "--out-dir", root / "consumer-execution",
                "--out", out,
                "--worker", sys.executable, worker,
            ], expect=1)
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("hash drift", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
