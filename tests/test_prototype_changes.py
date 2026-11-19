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
CHANGES = TOOLS / "build_prototype_change_set.py"
IMPACT = TOOLS / "build_prototype_impact_report.py"
SCOPE = TOOLS / "build_prototype_patch_scope.py"
CONTEXT = TOOLS / "build_prototype_context_pack.py"
APPLY = TOOLS / "apply_scoped_patch.py"

PREVIOUS = """<!doctype html>
<html><head><title>Demo</title></head><body><main id="app">
<button data-ai-id="UI-SAVE" data-ai-fr="FR-001" data-ai-ac="AC-001" id="save-button">保存</button>
<div id="save-status" data-loading-state="loading">加载中</div>
</main><script>
const state = { saving: false };
document.querySelector('#save-button').addEventListener('click', function saveRecord(){ state.saving = true; });
</script></body></html>
"""
CURRENT = """<!doctype html>
<html><head><title>Demo</title></head><body><main id="app">
<button data-ai-id="UI-SAVE" data-ai-fr="FR-001" data-ai-ac="AC-001" data-permission="editor" id="save-button">保存并继续</button>
<div id="save-status" data-loading-state="loading">加载中</div>
</main><script>
const state = { saving: false };
function validateRecord(){ return true; }
document.querySelector('#save-button').addEventListener('click', function saveRecord(){ if (validateRecord()) state.saving = true; });
</script></body></html>
"""
MANIFEST = {
    "schemaVersion": 1, "manifestId": "M-DEMO", "workflowId": "WF-DEMO", "prototypeRevision": "r2",
    "prototypePath": "current.html", "prototypeHash": "a" * 64,
    "elements": [{
        "uiElementId": "UI-SAVE", "frIds": ["FR-001"], "acIds": ["AC-001"], "visibleLabel": "保存并继续",
        "states": ["default", "loading", "error", "no-permission"], "action": "click", "permissions": ["editor allowed"]
    }],
    "createdAt": "2026-11-19T00:00:00+08:00"
}


def run(argv, expect=0):
    process = subprocess.run([sys.executable, *map(str, argv)], text=True, capture_output=True)
    if process.returncode != expect:
        raise AssertionError(f"exit {process.returncode} != {expect}\nSTDOUT:\n{process.stdout}\nSTDERR:\n{process.stderr}")
    return json.loads(process.stdout)


class PrototypeChangeTests(unittest.TestCase):
    def fixture(self, root):
        previous = root / "previous.html"
        current = root / "current.html"
        previous.write_text(PREVIOUS, encoding="utf-8")
        current.write_text(CURRENT, encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(MANIFEST), encoding="utf-8")
        return previous, current, manifest

    def build_pipeline(self, root):
        previous, current, manifest = self.fixture(root)
        previous_model = root / "previous-model.json"
        current_model = root / "current-model.json"
        change_set = root / "change-set.json"
        impact = root / "impact.json"
        scope = root / "scope.json"
        context = root / "context.json"
        run([MODEL, "--prototype", previous, "--out", previous_model])
        run([MODEL, "--prototype", current, "--out", current_model])
        run([CHANGES, "--previous-model", previous_model, "--current-model", current_model, "--out", change_set])
        run([IMPACT, "--change-set", change_set, "--current-model", current_model, "--manifest", manifest, "--out", impact])
        run([SCOPE, "--change-set", change_set, "--impact-report", impact, "--current-model", current_model, "--prototype", current, "--out", scope])
        run([CONTEXT, "--current-model", current_model, "--change-set", change_set, "--impact-report", impact, "--patch-scope", scope, "--token-budget", "4000", "--out", context, "--strict"])
        return previous, current, manifest, previous_model, current_model, change_set, impact, scope, context

    def test_change_set_classifies_cosmetic_behavioral_and_permission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            *_, change_set, impact, scope, context = self.build_pipeline(root)
            changes = json.loads(change_set.read_text())
            self.assertEqual(changes["primaryType"], "PERMISSION")
            self.assertIn("COSMETIC", changes["changeTypes"])
            self.assertIn("BEHAVIORAL", changes["changeTypes"])
            self.assertIn("PERMISSION", changes["changeTypes"])
            self.assertTrue(changes["requiresPrdReconciliation"])
            impact_data = json.loads(impact.read_text())
            self.assertEqual(impact_data["riskLevel"], "CRITICAL")
            self.assertTrue(impact_data["requiresFullGate"])
            self.assertEqual(impact_data["affected"]["uiElementIds"], ["UI-SAVE"])
            self.assertIn("PERMISSION_MATRIX", impact_data["requiredReruns"])
            scope_data = json.loads(scope.read_text())
            self.assertEqual(scope_data["allowedUIElementIds"], ["UI-SAVE"])
            context_data = json.loads(context.read_text())
            self.assertTrue(context_data["withinTokenBudget"])
            self.assertTrue(any(node.get("uiElementId") == "UI-SAVE" for node in context_data["selectedNodes"]))
            self.assertTrue(context_data["omittedNodes"])

    def test_scoped_patch_applies_only_inside_declared_node(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, current, _, _, current_model, change_set, _, scope, _ = self.build_pipeline(root)
            changes = json.loads(change_set.read_text())
            scope_data = json.loads(scope.read_text())
            patch = {
                "schemaVersion": 1, "patchId": "PATCH-1", "workflowId": "WF-DEMO",
                "changeSetId": changes["changeSetId"], "scopeId": scope_data["scopeId"],
                "basePrototypeHash": scope_data["targetHash"],
                "operations": [{
                    "operationId": "OP-1", "uiElementId": "UI-SAVE", "changeKind": "COSMETIC",
                    "kind": "replace-exact", "oldText": "保存并继续", "newText": "保存草稿",
                    "evidenceRefs": ["change-set.json#CHG"]
                }],
                "createdAt": "2026-11-19T00:00:00+08:00"
            }
            patch_path = root / "patch.json"
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            patched = root / "patched.html"
            result_path = root / "patch-result.json"
            result = run([APPLY, "--prototype", current, "--current-model", current_model, "--patch-scope", scope, "--patch", patch_path, "--out", patched, "--result-out", result_path])
            self.assertEqual(result["status"], "PASS")
            self.assertIn("保存草稿", patched.read_text(encoding="utf-8"))
            self.assertNotIn("保存并继续", patched.read_text(encoding="utf-8"))

    def test_patch_rejects_target_outside_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _, current, _, _, current_model, change_set, _, scope, _ = self.build_pipeline(root)
            changes = json.loads(change_set.read_text())
            scope_data = json.loads(scope.read_text())
            patch = {
                "schemaVersion": 1, "patchId": "PATCH-2", "workflowId": "WF-DEMO",
                "changeSetId": changes["changeSetId"], "scopeId": scope_data["scopeId"],
                "basePrototypeHash": scope_data["targetHash"],
                "operations": [{
                    "operationId": "OP-2", "uiElementId": "UI-OTHER", "changeKind": "COSMETIC",
                    "kind": "replace-exact", "oldText": "加载中", "newText": "加载",
                    "evidenceRefs": ["change-set.json#CHG"]
                }],
                "createdAt": "2026-11-19T00:00:00+08:00"
            }
            patch_path = root / "patch.json"
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            result = run([APPLY, "--prototype", current, "--current-model", current_model, "--patch-scope", scope, "--patch", patch_path, "--out", root / "patched.html", "--result-out", root / "result.json"], expect=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("outside scope" in error for error in result["errors"]))

    def test_patch_rejects_ambiguous_old_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous, current, manifest = self.fixture(root)
            current.write_text(CURRENT.replace("保存并继续", "保存 保存"), encoding="utf-8")
            previous_model = root / "previous-model.json"
            current_model = root / "current-model.json"
            change_set = root / "change-set.json"
            impact = root / "impact.json"
            scope = root / "scope.json"
            run([MODEL, "--prototype", previous, "--out", previous_model])
            run([MODEL, "--prototype", current, "--out", current_model])
            run([CHANGES, "--previous-model", previous_model, "--current-model", current_model, "--out", change_set])
            run([IMPACT, "--change-set", change_set, "--current-model", current_model, "--manifest", manifest, "--out", impact])
            run([SCOPE, "--change-set", change_set, "--impact-report", impact, "--current-model", current_model, "--prototype", current, "--out", scope])
            changes = json.loads(change_set.read_text())
            scope_data = json.loads(scope.read_text())
            patch = {
                "schemaVersion": 1, "patchId": "PATCH-3", "workflowId": "WF-DEMO",
                "changeSetId": changes["changeSetId"], "scopeId": scope_data["scopeId"],
                "basePrototypeHash": scope_data["targetHash"],
                "operations": [{
                    "operationId": "OP-3", "uiElementId": "UI-SAVE", "changeKind": "COSMETIC",
                    "kind": "replace-exact", "oldText": "保存", "newText": "提交",
                    "evidenceRefs": ["change-set.json#CHG"]
                }],
                "createdAt": "2026-11-19T00:00:00+08:00"
            }
            patch_path = root / "patch.json"
            patch_path.write_text(json.dumps(patch), encoding="utf-8")
            result = run([APPLY, "--prototype", current, "--current-model", current_model, "--patch-scope", scope, "--patch", patch_path, "--out", root / "patched.html", "--result-out", root / "result.json"], expect=1)
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(any("oldText count" in error for error in result["errors"]))

    def test_missing_manifest_blocks_impact_and_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            previous, current, _ = self.fixture(root)
            previous_model = root / "previous-model.json"
            current_model = root / "current-model.json"
            change_set = root / "change-set.json"
            impact = root / "impact.json"
            scope = root / "scope.json"
            run([MODEL, "--prototype", previous, "--out", previous_model])
            run([MODEL, "--prototype", current, "--out", current_model])
            run([CHANGES, "--previous-model", previous_model, "--current-model", current_model, "--out", change_set])
            result = run([IMPACT, "--change-set", change_set, "--current-model", current_model, "--out", impact], expect=1)
            self.assertEqual(result["status"], "BLOCKED")
            impact_data = json.loads(impact.read_text())
            self.assertTrue(any("Manifest is required" in item for item in impact_data.get("rationale", [])))
            scope_result = run([SCOPE, "--change-set", change_set, "--impact-report", impact, "--current-model", current_model, "--prototype", current, "--out", scope], expect=1)
            self.assertEqual(scope_result["status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
