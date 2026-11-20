import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
BUILDER = TOOLS / "build_consumer_review_jobs.py"


def run(argv, expect=0):
    proc = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if proc.returncode != expect:
        raise AssertionError(f"exit {proc.returncode} != {expect}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(proc.stdout)


class ConsumerReviewJobTests(unittest.TestCase):
    def request_without_reviews(self, root):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_consumer_acceptance import ConsumerAcceptanceTests
        helper = ConsumerAcceptanceTests()
        request_path, request, _ = helper.fixture(root)
        request = dict(request)
        request["artifacts"] = dict(request["artifacts"])
        request["artifacts"].pop("productManagerReview", None)
        request["artifacts"].pop("architectReview", None)
        pending = root / "pending-request.json"
        pending.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        return pending, request

    def test_builds_two_isolated_jobs_with_frozen_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request = self.request_without_reviews(root)
            out = root / "jobs"
            result = run([BUILDER, "--request", request_path, "--out-dir", out])
            self.assertEqual(result["status"], "READY")
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["jobs"]), 2)
            self.assertGreaterEqual(len(manifest["frozenInputs"]), 7)
            tasks = []
            plans = []
            for job in manifest["jobs"]:
                task = json.loads(Path(job["taskPath"]).read_text(encoding="utf-8"))
                plan = json.loads(Path(job["reviewPlanPath"]).read_text(encoding="utf-8"))
                tasks.append(task)
                plans.append(plan)
                self.assertEqual(task["reviewMode"], "independent-review")
                self.assertTrue(task["readOnlyFrozenInputs"])
                self.assertIn(task["role"], {"product-manager-consumer", "architect-consumer"})
                self.assertEqual(task["inputs"], manifest["frozenInputs"])
                self.assertTrue(plan["questions"])
                self.assertTrue(plan["counterexamples"])
            self.assertNotEqual(tasks[0]["contextId"], tasks[1]["contextId"])
            self.assertNotEqual(tasks[0]["role"], tasks[1]["role"])
            self.assertEqual({plan["reviewerRole"] for plan in plans}, {"product-manager-consumer", "architect-consumer"})

    def test_shared_consumer_context_blocks_job_build(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request = self.request_without_reviews(root)
            request["architect"]["contextId"] = request["productManager"]["contextId"]
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            result = run([BUILDER, "--request", request_path, "--out-dir", root / "jobs"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("distinct" in item for item in result["errors"]))

    def test_missing_prototype_blocks_prototype_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            request_path, request = self.request_without_reviews(root)
            request["artifacts"]["prototype"] = str(root / "missing.html")
            request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
            result = run([BUILDER, "--request", request_path, "--out-dir", root / "jobs"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertTrue(any("artifact not found" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
