import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ("scripts" if (ROOT / "scripts").exists() else "tools")
MODEL = TOOLS / "build_prototype_model.py"
CONTRACT = TOOLS / "build_interaction_contract.py"
STATIC = TOOLS / "build_prototype_static_report.py"
VERIFY = TOOLS / "verify_prototype_runtime.py"
RUNTIME_REPORT = TOOLS / "build_prototype_runtime_report.py"
SEMANTIC_REPORT = TOOLS / "build_prototype_semantic_report.py"
GATE = TOOLS / "run_prototype_three_layer_gate.py"

HTML = """<!doctype html><html><head><title>Replay Demo</title></head><body>
<main id="app"><button data-ai-id="UI-SAVE" data-ai-fr="FR-001" data-ai-ac="AC-001" id="save-button">保存</button>
<div id="loading" data-loading-state="loading">加载中</div><div id="empty" class="empty-state">暂无数据</div>
<div id="error" class="error-state">保存失败</div><div id="timeout" data-timeout-state="timeout">请求超时</div>
<div id="denied" data-unauthorized-state="true">无权限</div></main>
<script>document.querySelector('#save-button').addEventListener('click', () => { window.__saved = true; });</script>
</body></html>"""
STATES = ["success", "error", "empty", "timeout", "no-permission"]


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class ThreeLayerGateTests(unittest.TestCase):
    def fixture(self, root):
        prototype = root / "prototype.html"
        prototype.write_text(HTML, encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "schemaVersion": 1, "manifestId": "M-1", "workflowId": "WF-1", "prototypeRevision": "r1",
            "prototypePath": str(prototype), "prototypeHash": hashlib.sha256(prototype.read_bytes()).hexdigest(),
            "elements": [{"uiElementId": "UI-SAVE", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "保存", "states": STATES, "action": "click", "permissions": ["editor"]}],
            "createdAt": "2026-11-19T00:00:00+08:00"
        }), encoding="utf-8")
        scenarios = []
        for state in STATES:
            scenarios.append({
                "scenarioId": f"SCN-{state.upper().replace('-', '_')}", "elementId": "UI-SAVE", "eventId": "EVT-SAVE", "role": "editor",
                "initialState": ["editor"], "actions": [{"type": "click", "selector": "#save-button"}, {"type": "assert-visible", "selector": "#app"}],
                "expected": {"view": "Replay Demo", "states": [state], "context": ["editor"], "dataEffects": ["saved"], "forbiddenEffects": ["console error"]},
                "evidenceCapture": ["dom", "screenshot", "trace", "console"]
            })
        overlay = root / "overlay.json"
        overlay.write_text(json.dumps({
            "schemaVersion": 1, "overlayId": "OV-1", "createdAt": "2026-11-19T00:00:00+08:00",
            "elements": [{"uiElementId": "UI-SAVE", "events": [{"eventId": "EVT-SAVE", "type": "click", "preconditions": ["editor"], "postconditions": ["saved"], "stateTransitions": [], "dataEffects": [{"kind": "WRITE", "target": "saved", "description": "set saved"}], "runtimeScenarioIds": [item["scenarioId"] for item in scenarios]}], "renderStates": STATES, "permissionRoles": ["editor"]}],
            "runtimeScenarios": scenarios
        }), encoding="utf-8")
        prd = root / "prd.md"
        prd.write_text("# Replay Demo\nFR-001 Save.\nAC-001 All states visible.\n", encoding="utf-8")
        return prototype, manifest, overlay, prd

    def contract(self, root):
        prototype, manifest, overlay, prd = self.fixture(root)
        model = root / "model.json"
        contract = root / "contract.json"
        run([MODEL, "--prototype", prototype, "--out", model])
        run([CONTRACT, "--prototype", prototype, "--model", model, "--manifest", manifest, "--overlay", overlay, "--prd", prd, "--out", contract])
        return prototype, prd, contract

    def fake_runner(self, root):
        runner = root / "fake_browser.py"
        runner.write_text(r'''import json,sys
req=json.load(sys.stdin)
results=[]
for scenario in req.get("scenarios", []):
    states=[str(x) for x in scenario.get("expected",{}).get("states",[])]
    results.append({
      "scenarioId":scenario["scenarioId"],"status":"PASS","role":scenario.get("role","editor"),
      "checks":[{"checkId":"SCENARIO."+scenario["scenarioId"]+".PASS","status":"passed","observed":"ok","expected":"ok"}],
      "consoleErrors":[],"pageErrors":[],"requestFailures":[],"evidenceRefs":[],"failedCheckIds":[],"coveredStateKinds":states
    })
print(json.dumps({"status":"PASS","executionMode":"real-browser","browserVersion":"fake-chromium","scenarioResults":results,"consoleErrors":[],"pageErrors":[],"requestFailures":[],"checks":[]}))
''', encoding="utf-8")
        return runner

    def test_complete_three_layer_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype, prd, contract = self.contract(root); runner = self.fake_runner(root)
            static = root / "static.json"; runtime = root / "runtime.json"; runtime_report = root / "runtime-report.json"
            semantic = root / "semantic.json"; semantic_report = root / "semantic-report.json"; gate = root / "gate.json"
            run([STATIC, "--contract", contract, "--prd", prd, "--out", static])
            args = [VERIFY, "--prototype", prototype, "--contract", "--interaction-contract", contract, "--out", runtime, "--browser-runner", sys.executable, runner, "--require-real-browser"]
            args = [VERIFY, "--prototype", prototype, "--interaction-contract", contract, "--out", runtime, "--browser-runner", sys.executable, runner, "--require-real-browser"]
            for state in STATES:
                args.extend(["--required-state-kind", state])
            run(args)
            run([RUNTIME_REPORT, "--runtime", runtime, "--out", runtime_report])
            aggregate = root / "aggregate.json"
            aggregate.write_text(json.dumps({"schemaVersion": 1, "workflowId": "WF-1", "targetRevision": "r1", "status": "PASS", "blockingCount": 0, "jobsTotal": 1, "jobsReviewed": 1, "missingJobs": [], "verdicts": {"ACCEPTED": 1}, "findings": [], "generatedAt": "2026-11-19T00:00:00+08:00"}), encoding="utf-8")
            run([SEMANTIC_REPORT, "--aggregate", aggregate, "--contract", contract, "--out", semantic_report])
            result = run([GATE, "--static", static, "--runtime", runtime_report, "--semantic", semantic_report, "--require-real-browser", "--out", gate, "--json"])
            for state in STATES:
                result = run([GATE, "--static", static, "--runtime", runtime_report, "--semantic", semantic_report, "--require-real-browser", "--required-state-kind", state, "--out", gate, "--json"])
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["layers"], {"static": "PASS", "runtime": "PASS", "semantic": "PASS"})
            self.assertEqual(result["runtimeEvidenceLevel"], "REAL_BROWSER")

    def test_environment_blocked_runtime_blocks_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype, prd, contract = self.contract(root)
            static = root / "static.json"; runtime = root / "runtime.json"; runtime_report = root / "runtime-report.json"
            semantic_report = root / "semantic-report.json"; gate = root / "gate.json"
            run([STATIC, "--contract", contract, "--prd", prd, "--out", static])
            blocked = root / "blocked.py"
            blocked.write_text('import json\nprint(json.dumps({"status":"ENVIRONMENT_BLOCKED","executionMode":"real-browser","error":"chromium launch denied","scenarioResults":[],"consoleErrors":[],"pageErrors":[],"requestFailures":[],"checks":[]}))\n', encoding="utf-8")
            run([VERIFY, "--prototype", prototype, "--interaction-contract", contract, "--out", runtime, "--browser-runner", sys.executable, blocked, "--require-real-browser"], expect=1)
            run([RUNTIME_REPORT, "--runtime", runtime, "--out", runtime_report], expect=1)
            aggregate = root / "aggregate.json"
            aggregate.write_text(json.dumps({"workflowId": "WF-1", "targetRevision": "r1", "status": "PASS", "blockingCount": 0, "findings": [], "generatedAt": "2026-11-19T00:00:00+08:00"}), encoding="utf-8")
            run([SEMANTIC_REPORT, "--aggregate", aggregate, "--contract", contract, "--out", semantic_report])
            result = run([GATE, "--static", static, "--runtime", runtime_report, "--semantic", semantic_report, "--require-real-browser", "--out", gate, "--json"], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["layers"]["runtime"], "ENVIRONMENT_BLOCKED")

    def test_missing_runtime_layer_is_incomplete(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); prototype, prd, contract = self.contract(root)
            static = root / "static.json"; gate = root / "gate.json"
            run([STATIC, "--contract", contract, "--prd", prd, "--out", static])
            result = run([GATE, "--static", static, "--out", gate, "--json"], expect=1)
            self.assertEqual(result["status"], "INCOMPLETE")
            self.assertEqual(result["layers"]["runtime"], "MISSING")


if __name__ == "__main__":
    unittest.main()
