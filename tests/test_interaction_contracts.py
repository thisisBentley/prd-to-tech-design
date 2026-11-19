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
VALIDATE = TOOLS / "validate_interaction_contract.py"
MIGRATE = TOOLS / "audit_prototype_migration.py"

HTML = """<!doctype html>
<html><head><title>Demo Prototype</title><meta name="source-prd-version" content="v1.0"></head>
<body><main id="app">
<button data-ai-id="UI-SAVE" data-ai-fr="FR-001" data-ai-ac="AC-001" id="save-button">保存</button>
<div id="save-status" data-loading-state="loading">加载中</div>
<div class="empty-state">暂无数据</div><div class="error-state">保存失败</div><div data-unauthorized-state="true">无权限</div>
</main><script>
const state = { saving: false };
document.querySelector('#save-button').addEventListener('click', function saveRecord(){ state.saving = true; });
</script></body></html>
"""
MANIFEST = {
    "schemaVersion": 1, "manifestId": "M-DEMO", "workflowId": "WF-DEMO", "prototypeRevision": "r1",
    "prototypePath": "prototype.html", "prototypeHash": "a" * 64,
    "elements": [{
        "uiElementId": "UI-SAVE", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "保存",
        "states": ["default", "loading", "empty", "error", "no-permission"], "action": "click",
        "permissions": ["editor allowed", "viewer denied"]
    }],
    "createdAt": "2026-11-19T00:00:00+08:00"
}
OVERLAY = {
    "schemaVersion": 1, "overlayId": "OV-DEMO", "createdAt": "2026-11-19T00:00:00+08:00",
    "elements": [{
        "uiElementId": "UI-SAVE",
        "events": [{
            "eventId": "EVT-SAVE", "type": "click", "preconditions": ["record is editable"],
            "postconditions": ["record is persisted", "success feedback is visible"],
            "stateTransitions": [{"from": "editing", "to": "saved", "trigger": "click save"}],
            "dataEffects": [{"kind": "WRITE", "target": "record", "description": "Persist the record."}],
            "runtimeScenarioIds": ["SCN-SAVE-SUCCESS"]
        }],
        "renderStates": ["default", "loading", "empty", "error", "no-permission"],
        "permissionRoles": ["editor", "viewer"]
    }],
    "runtimeScenarios": [{
        "scenarioId": "SCN-SAVE-SUCCESS", "elementId": "UI-SAVE", "eventId": "EVT-SAVE", "role": "editor",
        "initialState": ["record is editable"], "actions": [{"type": "click", "selector": "#save-button"}],
        "expected": {"view": "record detail", "states": ["saved"], "context": ["same record"], "dataEffects": ["record persisted"], "forbiddenEffects": ["navigation loss"]},
        "evidenceCapture": ["dom snapshot", "console", "network", "screenshot"]
    }]
}


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class InteractionContractTests(unittest.TestCase):
    def fixture(self, root):
        prototype = root / "prototype.html"
        manifest = root / "manifest.json"
        overlay = root / "overlay.json"
        prd = root / "prd.md"
        prototype.write_text(HTML, encoding="utf-8")
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        overlay.write_text(json.dumps(OVERLAY), encoding="utf-8")
        prd.write_text("# Demo\nFR-001 Save.\nAC-001 Persist without context loss.\n", encoding="utf-8")
        return prototype, manifest, overlay, prd

    def test_extracts_dom_model_and_script_binding(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prototype, _, _, _ = self.fixture(root)
            out = root / "model.json"
            result = run([MODEL, "--prototype", prototype, "--out", out])
            self.assertEqual(result["status"], "PASS")
            model = json.loads(out.read_text())
            self.assertEqual(model["metrics"]["dataAiIdNodes"], 1)
            self.assertEqual(model["metrics"]["interactiveNodes"], 1)
            self.assertTrue(any(item["selector"] == "#save-button" and item["event"] == "click" for item in model["eventBindings"]))
            self.assertIn("saveRecord", model["scripts"][0]["functionNames"])

    def test_builds_and_validates_complete_interaction_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prototype, manifest, overlay, prd = self.fixture(root)
            model = root / "model.json"
            contract = root / "contract.json"
            report = root / "validation.json"
            run([MODEL, "--prototype", prototype, "--out", model])
            built = run([CONTRACT, "--prototype", prototype, "--model", model, "--manifest", manifest, "--overlay", overlay, "--prd", prd, "--out", contract])
            self.assertEqual(built["status"], "PASS")
            validated = run([VALIDATE, "--contract", contract, "--prd", prd, "--out", report, "--json"])
            self.assertEqual(validated["status"], "PASS")
            data = json.loads(contract.read_text())
            self.assertEqual(data["metrics"]["eventsWithPostconditions"], 1)
            self.assertEqual(data["metrics"]["eventsWithRuntimeScenarios"], 1)

    def test_missing_overlay_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prototype, manifest, _, prd = self.fixture(root)
            model = root / "model.json"
            contract = root / "contract.json"
            run([MODEL, "--prototype", prototype, "--out", model])
            built = run([CONTRACT, "--prototype", prototype, "--model", model, "--manifest", manifest, "--prd", prd, "--out", contract])
            self.assertEqual(built["status"], "INCOMPLETE")
            data = json.loads(contract.read_text())
            codes = {item["code"] for item in data["findings"]}
            self.assertIn("MISSING_POSTCONDITION", codes)
            self.assertIn("MISSING_RUNTIME_SCENARIO", codes)
            result = run([VALIDATE, "--contract", contract, "--prd", prd, "--json"], expect=1)
            self.assertEqual(result["status"], "FAIL")

    def test_migration_audit_blocks_unbound_prototype(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prototype = root / "prototype.html"
            prototype.write_text("<!doctype html><html><body><button onclick=\"go()\">Go</button></body></html>", encoding="utf-8")
            model = root / "model.json"
            report = root / "migration.json"
            run([MODEL, "--prototype", prototype, "--out", model])
            result = run([MIGRATE, "--prototype", prototype, "--model", model, "--out", report], expect=1)
            self.assertEqual(result["status"], "MIGRATION_BLOCKED")
            self.assertIn("DATA_AI_ID_MISSING", result["findings"])
            self.assertIn("MANIFEST_MISSING", result["findings"])


if __name__ == "__main__":
    unittest.main()
