import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
TOOL = ROOT / SCRIPTS / "evaluate_delivery_quality.py"
BASE = ROOT / "examples" / "p05" / "delivery-quality-baseline.json"


class DeliveryQualityBenchmarkTests(unittest.TestCase):
    def run_eval(self, data, root, expect):
        src = root / "benchmark.json"
        out = root / "result.json"
        src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run([sys.executable, str(TOOL), "--input", str(src), "--out", str(out)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(out.read_text(encoding="utf-8"))

    def base(self):
        return json.loads(BASE.read_text(encoding="utf-8"))

    def test_synthetic_baseline_passes_but_is_not_production_eligible(self):
        with tempfile.TemporaryDirectory() as td:
            result = self.run_eval(self.base(), Path(td), 0)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["productionEligible"])
            self.assertEqual(result["metrics"]["findingRecall"], 1.0)
            self.assertEqual(result["metrics"]["traceability"], 1.0)
            self.assertEqual(result["metrics"]["replayConsistency"], 1.0)

    def test_missed_blocking_finding_fails_recall(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["samples"][1]["detectedFindingIds"] = ["PERMISSION.BOUNDARY.UNDEFINED"]
            result = self.run_eval(data, Path(td), 1)
            self.assertEqual(result["status"], "FAIL")
            finding = next(c for c in result["checks"] if c["checkId"] == "BENCHMARK.FINDING_RECALL")
            self.assertEqual(finding["status"], "failed")

    def test_false_positive_fails_rate(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["samples"][0]["detectedFindingIds"] = ["UNEXPECTED.FALSE.POSITIVE"]
            result = self.run_eval(data, Path(td), 1)
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["metrics"]["falsePositiveRate"], 0)

    def test_open_decision_or_escalation_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["samples"][4]["openDecisionCount"] = 1
            result = self.run_eval(data, Path(td), 1)
            self.assertEqual(result["status"], "FAIL")

    def test_real_classification_requires_real_production_samples(self):
        with tempfile.TemporaryDirectory() as td:
            data = self.base()
            data["dataClassification"] = "REAL"
            result = self.run_eval(data, Path(td), 0)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["productionEligible"])
            data["samples"][0]["productionEligible"] = True
            data["samples"][1]["productionEligible"] = True
            data["samples"][2]["productionEligible"] = True
            result = self.run_eval(data, Path(td), 0)
            self.assertTrue(result["productionEligible"])


if __name__ == "__main__":
    unittest.main()
