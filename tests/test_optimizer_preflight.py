import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT / ("scripts" if (ROOT/"scripts").exists() else "tools")
BUILD=TOOLS/"build_optimizer_preflight.py"
VALIDATE=TOOLS/"validate_optimizer_preflight.py"

def run(argv, expect=0):
    process=subprocess.run([sys.executable,*map(str,argv)],text=True,capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)

class OptimizerPreflightTests(unittest.TestCase):
    def fixture(self, root, ready=False):
        def write(name, data):
            path=root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
            return path
        episode=write("episode.json", {
            "workflowId":"WF-OPT","requirementId":"REQ-OPT","revision":"r2",
            "status":"COMPLETE" if ready else "PARTIAL",
            "repairs":{"rounds":1 if ready else 0},
            "consumerAcceptance":{"realCount":1 if ready else 0},
            "gates":{"finalStatus":"PASS" if ready else "BLOCKED"},
        })
        observer=write("observer.json", {
            "workflowId":"WF-OPT","revision":"r2",
            "status":"READY" if ready else "PARTIAL",
            "evidenceGaps":[] if ready else ["CHALLENGER_RUN:MISSING"],
            "recommendations":[{"recommendationId":"REVIEW_ROOT_CAUSE","priority":"P0","owner":"delivery-owner","action":"Review root cause.","sourceRefs":["finding.json"]}],
        })
        decisions=root/"decisions"
        decision=write("decisions/D-1.json",{"decisionId":"D-1","status":"confirmed"})
        return episode,observer,decisions

    def args(self, paths, out):
        episode,observer,decisions=paths
        return [BUILD,"--episode",episode,"--observer",observer,"--decision-dir",decisions,"--out",out]

    def test_current_state_is_blocked_without_real_closed_loop(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=self.fixture(root,ready=False)
            out=root/"preflight.json"
            result=run(self.args(paths,out))
            self.assertEqual(result["status"],"BLOCKED")
            data=json.loads(out.read_text())
            self.assertFalse(data["authority"]["mayApply"])
            self.assertIn("REAL_CLOSED_LOOP:REQUIRED",data["evidenceGaps"])
            self.assertEqual(data["proposals"],[])

    def test_ready_fixture_only_prepares_human_change_set(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=self.fixture(root,ready=True)
            out=root/"preflight.json"
            result=run(self.args(paths,out))
            self.assertEqual(result["status"],"READY_FOR_HUMAN_CHANGE_SET")
            data=json.loads(out.read_text())
            self.assertEqual(len(data["proposals"]),1)
            self.assertEqual(data["proposals"][0]["applyStatus"],"REQUIRES_HUMAN_CHANGE_SET")
            self.assertFalse(data["authority"]["releaseEligible"])
            self.assertFalse(data["authority"]["trainingEligible"])
            validated=run([VALIDATE,"--preflight",out])
            self.assertEqual(validated["status"],"PASS")

    def test_open_decision_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            paths=self.fixture(root,ready=True)
            decision=paths[2]/"D-1.json"
            data=json.loads(decision.read_text()); data["status"]="open"; decision.write_text(json.dumps(data))
            out=root/"preflight.json"
            result=run(self.args(paths,out))
            self.assertEqual(result["status"],"BLOCKED")
            self.assertIn("HUMAN_ADJUDICATION:REQUIRED",json.loads(out.read_text())["evidenceGaps"])

if __name__=="__main__":
    unittest.main()
