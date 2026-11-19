# Browser Runtime Adapter

`playwright_runner.py` executes Interaction Contract runtime scenarios in Chromium.

## Input

One JSON request on stdin:

```json
{
  "prototypePath": "/abs/prototype.html",
  "prototypeHash": "sha256",
  "contractPath": "/abs/interaction-contract.json",
  "scenarios": ["..."],
  "viewport": {"width": 1440, "height": 900},
  "evidenceDir": "/abs/runtime-evidence",
  "browserExecutablePath": "/optional/cached/chromium"
}
```

## Scenario execution

Each scenario runs in a fresh context and records:

```text
role
initial state
setup actions
scenario actions
expected view / states / context / data effects
forbidden effects
console errors
page errors
request failures
DOM snapshot
screenshot
Playwright trace
```

## Output

```json
{
  "status": "PASS",
  "executionMode": "real-browser",
  "browserVersion": "chromium-...",
  "scenarioResults": [],
  "scenarioMetrics": {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "coveredStateKinds": []
  },
  "consoleErrors": [],
  "pageErrors": [],
  "requestFailures": [],
  "checks": []
}
```

If Chromium cannot launch, the status is `ENVIRONMENT_BLOCKED`; it is never
converted into a real-browser PASS.

## Requirements

```text
Python playwright package
Chromium browser binary
```

Example:

```bash
python3 tools/verify_prototype_runtime.py \
  --prototype Prototype.html \
  --interaction-contract interaction-contract.json \
  --browser-runner python3 adapters/browser-runtime/playwright_runner.py \
  --require-real-browser \
  --evidence-dir runtime-evidence \
  --out prototype-runtime.json
```
