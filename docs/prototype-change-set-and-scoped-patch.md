# Prototype Change Set and Scoped Patch

## Purpose

M7.5-B converts a Prototype modification into a deterministic, reviewable change
pipeline:

```text
Previous Model + Current Model
→ Change Set
→ Impact Report
→ Patch Scope
→ Context Pack V2
→ Scoped Patch
→ Patch Result
```

The model layer comes from `build_prototype_model.py`. A change set is calculated
from DOM nodes, event bindings, state indicators and script hashes, not from a
natural-language description alone.

## Artifacts

```text
prototype-change-set.schema.json
prototype-impact-report.schema.json
prototype-patch-scope.schema.json
prototype-context-pack.schema.json
scoped-patch.schema.json
scoped-patch-result.schema.json
```

## Commands

Build the change set:

```bash
python3 scripts/build_prototype_change_set.py \
  --previous-model previous-model.json \
  --current-model current-model.json \
  --workflow-id WF-1 \
  --from-revision r1 \
  --to-revision r2 \
  --out change-set.json
```

Build the impact report:

```bash
python3 scripts/build_prototype_impact_report.py \
  --change-set change-set.json \
  --current-model current-model.json \
  --manifest prototype-manifest.json \
  --out impact-report.json
```

Derive the patch scope:

```bash
python3 scripts/build_prototype_patch_scope.py \
  --change-set change-set.json \
  --impact-report impact-report.json \
  --current-model current-model.json \
  --prototype prototype.html \
  --out patch-scope.json
```

Build the minimum Context Pack:

```bash
python3 scripts/build_prototype_context_pack.py \
  --current-model current-model.json \
  --change-set change-set.json \
  --impact-report impact-report.json \
  --patch-scope patch-scope.json \
  --token-budget 4000 \
  --out context-pack.json \
  --strict
```

Apply a replacement-only patch:

```bash
python3 scripts/apply_scoped_patch.py \
  --prototype prototype.html \
  --current-model current-model.json \
  --patch-scope patch-scope.json \
  --patch scoped-patch.json \
  --out patched.html \
  --result-out patch-result.json
```

## Change classes

```text
COSMETIC        text, classes, style
STRUCTURAL      tag, DOM path or parent movement
BEHAVIORAL      event binding, interactivity or script change
DATA_CONTRACT   data-* contract or data-ai binding change
PERMISSION      permission / role / access attribute change
RUNTIME         loading, empty, error, timeout or state evidence change
POLICY          reserved for external contract or gate policy changes
```

## Fail-closed rules

- A change outside the DOM model cannot enter the change set.
- A DOM/event/state change without a stable UI element ID blocks the impact report.
- An impact report without a Manifest cannot resolve FR/AC and blocks.
- A BLOCKED impact report cannot produce a patch scope.
- A patch targeting an element or node outside the scope fails.
- Ambiguous `oldText`, overlapping edits and changes above the character limit fail.
- `replace-exact` is the only patch operation. It never reformats the entire HTML.
- A successful patch result does not replace static, runtime or semantic review.

## Context Pack V2

The pack includes:

- affected nodes;
- ancestors required to understand structure;
- direct descendants and state evidence;
- omitted nodes with an explicit reason;
- dependency closure from Change Set / Impact / Scope / FR / AC / event / state;
- token budget and deterministic context hash.

The pack must preserve every affected node even if the token estimate is over
budget. In that case it reports `TOKEN_BUDGET_EXCEEDED` rather than silently
dropping protected context.
