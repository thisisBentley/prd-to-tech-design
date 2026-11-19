# Prototype Replay and Three-Layer Gate

## Purpose

M7.5-C closes Prototype verification as three independent layers:

```text
Static Contract
+ Real Browser Scenario Replay
+ Semantic Consistency
= Prototype Three-Layer Gate
```

None of the three layers can substitute for another. A static contract PASS does
not prove runtime behavior. A browser click does not prove business semantics. A
semantic review does not prove that the visible control is reachable.

## Scenario execution

`verify_prototype_runtime.py` accepts an Interaction Contract and passes its
`runtimeScenarios` to the browser adapter.

```bash
python3 scripts/verify_prototype_runtime.py \
  --prototype prototype.html \
  --interaction-contract interaction-contract.json \
  --browser-runner python3 adapters/browser-runtime/playwright_runner.py \
  --require-real-browser \
  --required-state-kind success \
  --required-state-kind error \
  --required-state-kind empty \
  --required-state-kind timeout \
  --required-state-kind no-permission \
  --evidence-dir runtime-evidence \
  --out runtime.json
```

Each scenario runs in a fresh browser context with:

- role injection;
- initial prototype state;
- setup actions;
- scenario actions;
- expected view/state/context/data effect assertions;
- forbidden effect checks;
- console, page error and request failure capture;
- DOM snapshot, screenshot and Playwright trace.

Supported actions:

```text
click
fill
select
press
wait
assert-visible
assert-text
assert-url
assert-hash
assert-state
eval
```

## Layer reports

```bash
python3 scripts/build_prototype_static_report.py \
  --contract interaction-contract.json \
  --prd PRD_DELIVERY.md \
  --out prototype-static-report.json

python3 scripts/build_prototype_runtime_report.py \
  --runtime runtime.json \
  --out prototype-runtime-report.json

python3 scripts/build_prototype_semantic_report.py \
  --aggregate semantic-review-aggregate.json \
  --contract interaction-contract.json \
  --out prototype-semantic-report.json
```

## Three-layer gate

```bash
python3 scripts/run_prototype_three_layer_gate.py \
  --static prototype-static-report.json \
  --runtime prototype-runtime-report.json \
  --semantic prototype-semantic-report.json \
  --require-real-browser \
  --required-state-kind success \
  --required-state-kind error \
  --required-state-kind empty \
  --required-state-kind timeout \
  --required-state-kind no-permission \
  --out prototype-three-layer-gate.json
```

Gate rules:

- all three layers must bind the same workflow, contract and Prototype hash;
- static must be `PASS`;
- runtime must be `PASS` with `REAL_BROWSER` for a production claim;
- semantic must be `PASS` or `PASS_WITH_NONBLOCKING` with `blockingCount=0`;
- required state kinds must be present in executed scenarios;
- any missing layer is `INCOMPLETE`;
- any mismatch or failed layer is `BLOCKED`.

## Browser environment failure

If Chromium cannot launch, the adapter returns `ENVIRONMENT_BLOCKED`. It must not
degrade into `REAL_BROWSER` or an implicit PASS. The three-layer gate remains
blocked until a real browser can execute the scenarios in an allowed environment.

## Evidence

A production replay should retain:

```text
scenario result
DOM snapshot
screenshot
browser trace
console errors
page errors
request failures
state/context assertions
```

Evidence files must be tied to the exact Prototype hash and contract revision.
