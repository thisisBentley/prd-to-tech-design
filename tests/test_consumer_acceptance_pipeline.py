import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_consumer_review_execution import ConsumerReviewExecutionTests

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
PIPELINE = TOOLS / "run_consumer_acceptance_pipeline.py"
POLICY = ROOT / "config" / "consumer-acceptance" / "policy-v1.json"


class ConsumerAcceptancePipelineTests(unittest.TestCase):
    def test_intake_to_report_runs_without_manual_manifest_wiring(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, _, worker = ConsumerReviewExecutionTests().fixture(root)
            out_dir = root / "pipeline"
            out = root / "pipeline-report.json"
            process = subprocess.run([
                sys.executable, str(PIPELINE),
                "--request", str(request_path),
                "--policy", str(POLICY),
                "--out-dir", str(out_dir),
                "--out", str(out),
                "--worker", sys.executable, str(worker),
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(Path(report["jobsManifest"]).is_file())
            self.assertTrue(Path(report["executionReport"]).is_file())
            self.assertTrue(Path(report["consumerReport"]).is_file())
            self.assertFalse(report["m7ExitEvidenceEligible"])

    def test_builder_failure_is_reported_as_failed_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out = root / "pipeline-report.json"
            process = subprocess.run([
                sys.executable, str(PIPELINE),
                "--request", root / "missing-request.json",
                "--policy", str(POLICY),
                "--out-dir", root / "pipeline",
                "--out", str(out),
                "--worker", sys.executable, "-c", "pass",
            ], text=True, capture_output=True)
            self.assertEqual(process.returncode, 1)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "FAILED")
            self.assertTrue(report["errors"])


if __name__ == "__main__":
    unittest.main()
