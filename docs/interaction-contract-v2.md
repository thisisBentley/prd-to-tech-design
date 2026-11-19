# Interaction Contract V2

## Purpose

Interaction Contract V2 turns a Prototype from a label-to-FR/AC binding table into
a machine-checkable behavior model:

```text
Prototype HTML
→ Prototype Model
→ Manifest binding
→ Interaction Contract
→ Runtime Scenario
→ Browser Replay
```

The model does not replace the HTML. It extracts DOM, event and state evidence
from the HTML so the contract can be checked against the real artifact.

## Artifacts

```text
prototype-model.schema.json
interaction-contract.schema.json
interaction-overlay.schema.json
```

- `Prototype Model`: DOM nodes, selectors, event bindings, scripts, functions and
  state indicators extracted from HTML.
- `Interaction Overlay`: semantic behavior supplied by a producer or human:
  preconditions, postconditions, transitions, data effects and runtime scenarios.
- `Interaction Contract`: merged contract bound to the real Prototype revision.

The builder must not infer business postconditions from a button label. Missing
semantics remain findings.

## Commands

Extract the DOM model:

```bash
python3 scripts/build_prototype_model.py \
  --prototype prototype.html \
  --out prototype-model.json
```

Check whether the Prototype can be migrated:

```bash
python3 scripts/audit_prototype_migration.py \
  --prototype prototype.html \
  --model prototype-model.json \
  --manifest prototype-manifest.json \
  --prd PRD_DELIVERY.md \
  --out migration.json
```

Build the contract:

```bash
python3 scripts/build_interaction_contract.py \
  --prototype prototype.html \
  --model prototype-model.json \
  --manifest prototype-manifest.json \
  --overlay interaction-overlay.json \
  --prd PRD_DELIVERY.md \
  --out interaction-contract.json
```

Validate closure:

```bash
python3 scripts/validate_interaction_contract.py \
  --contract interaction-contract.json \
  --prd PRD_DELIVERY.md \
  --out validation.json \
  --json
```

## Closure rules

A contract is `PASS` only when:

- every Manifest UI element binds to a real DOM selector;
- UI IDs are unique;
- every event has at least one postcondition;
- every event references at least one runtime scenario;
- every referenced scenario is defined;
- every FR / AC reference exists in the PRD;
- no blocking finding remains.

## Boundaries

- `READY_FOR_CONTRACT` means the prototype has enough binding evidence to build a
  contract. It does not mean the contract is complete.
- A contract `PASS` is still not a runtime pass. Browser replay must execute the
  declared scenarios.
- Missing `data-ai-id` must be fixed in the artifact, not silently replaced by
  label-only matching.
- `visible-label` matching is a migration aid. It is not equivalent to a stable
  `data-ai-id` binding.
- No state transition or data effect may be invented from the presence of a
  control.
