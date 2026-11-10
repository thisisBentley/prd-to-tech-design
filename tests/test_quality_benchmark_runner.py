import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = "scripts" if ROOT.name == "ai-native-delivery" else "tools"
COLLECT = ROOT / SCRIPTS / "collect_delivery_sample.py"
RUNNER = ROOT / SCRIPTS / "run_quality_benchmark.py"


class QualityBenchmarkRunnerTests(unittest.TestCase):
    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def make_run(self, root, sample_id, profile, finding_id=None):
        root.mkdir(parents=True, exist_ok=True)
        prd = root / "PRD_DELIVERY.md"
        prd.write_text("# PRD\n\n- FR-001: first behavior\n- AC-001: verifies FR-001\n- FR-002: second behavior\n- AC-002: verifies FR-002\n", encoding="utf-8")
        review = root / ".agents" / "reviews" / "DELIVERY-REVIEW.review.json"
        findings = []
        if finding_id:
            findings.append({"findingId": "F-1", "severity": "BLOCKING", "rootCauseId": finding_id})
        self.write(review, {"verdict": "RETURNED" if findings else "ACCEPTED", "blockingCount": len(findings), "findings": findings})
        result = root / ".agents" / "results" / "DELIVERY-REVIEW.json"
        self.write(result, {"reviewResultPath": str(review)})
        plan = root / ".agents" / "delivery-plan.json"
        self.write(plan, {"schemaVersion": 1, "workflowId": sample_id, "tasks": [
            {"taskId": "PRD-PRODUCE", "kind": "producer", "status": "SUCCEEDED", "startedAt": "2026-11-10T00:00:00Z", "completedAt": "2026-11-10T00:00:02Z"},
            {"taskId": "DELIVERY-REVIEW", "kind": "reviewer", "status": "SUCCEEDED", "resultPath": str(result)},
            {"taskId": "PRD-REPAIR-R1-01", "kind": "repair", "status": "SUCCEEDED", "repairRound": 1, "rootCauseId": finding_id or "none", "completedAt": "2026-11-10T00:00:05Z"},
        ]})
        quality = root / ".agents" / "quality" / "quality-exit.json"
        self.write(quality, {"status": "PASS", "blockingCount": 0, "metrics": {"unresolvedDelta": 0}})
        final = root / ".agents" / "gates" / "final.json"
        self.write(final, {"result": "PASS", "blockingCount": 0})
        pair = root / ".agents" / "pair.json"
        self.write(pair, {"pairStatus": "SYNCED" if profile != "PRD_ONLY" else "NOT_APPLICABLE"})
        overview = root / ".agents" / "overview.json"
        self.write(overview, {"status": "PASS", "blockingCount": 0})
        runtime = root / ".agents" / "runtime.json"
        self.write(runtime, {"status": "PASS", "consoleErrors": 0})
        self.write(root / ".agents" / "decisions" / "D-1.json", {"status": "confirmed", "decisionId": "D-1"})
        self.write(root / ".agents" / "escalations" / "E-1.json", {"status": "closed", "escalationId": "E-1"})
        return {
            "schemaVersion": 1, "sampleId": sample_id, "profile": profile,
            "caseTypes": ["SIMPLE_PRD_ONLY"], "productionEligible": True, "runRoot": str(root),
            "plan": str(plan), "qualityExit": str(quality), "finalGate": str(final), "pair": str(pair),
            "overviewGate": str(overview), "runtimeEvidence": str(runtime), "prd": str(prd),
            "groundTruthFindingIds": [finding_id] if finding_id else [],
        }

    def test_collects_run_and_builds_non_production_benchmark(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = self.make_run(root / "run", "S-1", "PRD_PLUS_PROTOTYPE", "STATE.PRECONDITION")
            spec_path = root / "sample.json"; self.write(spec_path, spec)
            collected = root / "sample-result.json"
            proc = subprocess.run([sys.executable, str(COLLECT), "--spec", str(spec_path), "--out", str(collected)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            sample = json.loads(collected.read_text())
            self.assertEqual(sample["detectedFindingIds"], ["STATE.PRECONDITION"])
            self.assertEqual(sample["traceability"]["frCovered"], 2)
            self.assertEqual(sample["pairStatus"], "SYNCED")

            batch = {"schemaVersion": 1, "benchmarkId": "SYNTHETIC-RUNNER", "dataClassification": "SYNTHETIC", "thresholds": {"minimumSamples": 3, "maximumSamples": 5, "minimumFindingRecall": 1.0, "maximumFalsePositiveRate": 0.05, "minimumReplayConsistency": 1.0}, "samples": []}
            for index, case in enumerate(["SIMPLE_PRD_ONLY", "COMPLEX_PERMISSION_STATE", "PRD_PROTOTYPE", "PROTOTYPE_SEMANTIC_DELETE", "EXISTING_CAPABILITY_TERMINOLOGY"]):
                item = self.make_run(root / f"run-{index}", f"S-{index}", "PRD_ONLY", None)
                item["caseTypes"] = [case]
                batch["samples"].append(item)
            batch["samples"][1]["caseTypes"] = ["COMPLEX_PERMISSION_STATE", "PRD_PROTOTYPE"]
            batch["samples"][2]["caseTypes"] = ["PROTOTYPE_SEMANTIC_DELETE", "MULTI_ROUND_REPAIR"]
            batch["samples"][3]["caseTypes"] = ["EXISTING_CAPABILITY_TERMINOLOGY"]
            batch["samples"][4]["caseTypes"] = ["DECISION_ESCALATION"]
            batch_path = root / "samples.json"; self.write(batch_path, batch)
            out = root / "out"
            proc = subprocess.run([sys.executable, str(RUNNER), "--samples", str(batch_path), "--out-dir", str(out)], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            result = json.loads((out / "result.json").read_text())
            self.assertEqual(result["status"], "PASS")
            self.assertFalse(result["productionEligible"])
            self.assertEqual(result["sampleCount"], 5)

    def test_missing_ground_truth_detection_fails_recall(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            spec = self.make_run(root / "run", "S-1", "PRD_ONLY", None)
            spec["groundTruthFindingIds"] = ["MISSING.BLOCKER"]
            spec_path = root / "sample.json"; self.write(spec_path, spec)
            batch = {"schemaVersion": 1, "benchmarkId": "MISS", "dataClassification": "SYNTHETIC", "thresholds": {"minimumSamples": 3, "maximumSamples": 5, "minimumFindingRecall": 1.0, "maximumFalsePositiveRate": 0.05, "minimumReplayConsistency": 1.0}, "samples": [spec, spec, spec]}
            for i, item in enumerate(batch["samples"]):
                item = dict(item); item["sampleId"] = f"S-{i}"; batch["samples"][i] = item
            batch_path = root / "samples.json"; self.write(batch_path, batch)
            proc = subprocess.run([sys.executable, str(RUNNER), "--samples", str(batch_path), "--out-dir", str(root / "out")], text=True, capture_output=True)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            result = json.loads((root / "out" / "result.json").read_text())
            self.assertEqual(result["status"], "FAIL")
            self.assertFalse(result["productionEligible"])


if __name__ == "__main__":
    unittest.main()
