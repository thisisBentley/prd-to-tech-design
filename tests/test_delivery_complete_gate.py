import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
GATE = ROOT / SCRIPTS / "delivery_complete_gate.py"
BENCHMARK = ROOT / SCRIPTS / "evaluate_delivery_quality.py"
EXAMPLES = ROOT / "examples"


class DeliveryCompleteGateTests(unittest.TestCase):
    def prepare(self, root):
        shutil.copytree(EXAMPLES, root / "examples")
        gate_input = root / "examples" / "delivery-complete" / "gate-input.json"
        return gate_input, json.loads(gate_input.read_text(encoding="utf-8"))

    def run_gate(self, gate_input, root, expect):
        out = root / "complete-result.json"
        proc = subprocess.run([sys.executable, str(GATE), "--input", str(gate_input), "--out", str(out), "--repo-root", str(ROOT)], text=True, capture_output=True)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return json.loads(out.read_text(encoding="utf-8"))

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_baseline_fixture_reaches_baseline_ready_not_complete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, _ = self.prepare(root)
            result = self.run_gate(gate_input, root, 0)
            self.assertEqual(result["status"], "BASELINE_READY")
            self.assertFalse(result["productionEligible"])
            self.assertEqual(result["blockingCount"], 0)

    def test_production_requires_real_production_eligible_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, data = self.prepare(root)
            data["mode"] = "PRODUCTION"
            self.write(gate_input, data)
            blocked = self.run_gate(gate_input, root, 1)
            self.assertEqual(blocked["status"], "BLOCKED")

            benchmark_input = root / "examples" / "p05" / "delivery-quality-baseline.json"
            benchmark = json.loads(benchmark_input.read_text(encoding="utf-8"))
            benchmark["dataClassification"] = "REAL"
            for sample in benchmark["samples"][:3]:
                sample["productionEligible"] = True
            self.write(benchmark_input, benchmark)
            result_path = root / "examples" / "delivery-complete" / "quality-benchmark-result.json"
            proc = subprocess.run([sys.executable, str(BENCHMARK), "--input", str(benchmark_input), "--out", str(result_path)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            complete = self.run_gate(gate_input, root, 0)
            self.assertEqual(complete["status"], "COMPLETE")
            self.assertTrue(complete["productionEligible"])

    def test_tampered_benchmark_result_is_blocked_by_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, _ = self.prepare(root)
            result_path = root / "examples" / "delivery-complete" / "quality-benchmark-result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["productionEligible"] = True
            self.write(result_path, result)
            blocked = self.run_gate(gate_input, root, 1)
            self.assertIn("COMPLETE.P0_5_SOURCE_BINDING", {c["checkId"] for c in blocked["checks"] if c["status"] == "failed"})

    def test_open_handoff_finding_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, _ = self.prepare(root)
            handoff_path = root / "examples" / "delivery-complete" / "handoff.json"
            handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
            handoff["openFindings"] = ["OPEN-1"]
            self.write(handoff_path, handoff)
            blocked = self.run_gate(gate_input, root, 1)
            self.assertIn("COMPLETE.HANDOFF", {c["checkId"] for c in blocked["checks"] if c["status"] == "failed"})

    def test_invalid_research_record_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, _ = self.prepare(root)
            research_path = root / "examples" / "delivery-complete" / "research-record.json"
            research = json.loads(research_path.read_text(encoding="utf-8"))
            research["decisionRequired"] = True
            self.write(research_path, research)
            blocked = self.run_gate(gate_input, root, 1)
            self.assertIn("COMPLETE.RESEARCH_EVIDENCE", {c["checkId"] for c in blocked["checks"] if c["status"] == "failed"})

    def test_non_identical_replay_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gate_input, data = self.prepare(root)
            data["replay"]["replayRunSha256"][1] = "f" * 64
            self.write(gate_input, data)
            blocked = self.run_gate(gate_input, root, 1)
            self.assertIn("COMPLETE.REPLAY", {c["checkId"] for c in blocked["checks"] if c["status"] == "failed"})


if __name__ == "__main__":
    unittest.main()
