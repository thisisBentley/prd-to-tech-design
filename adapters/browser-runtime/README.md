# Browser Runtime Adapter

`playwright_runner.py` is a real-browser runtime adapter for `verify_prototype_runtime.py`.

## Contract

Input: one JSON request on stdin:

```json
{
  "prototypePath": "/abs/Prototype.html",
  "interactionManifest": {"actions": [{"type": "click", "selector": "[data-ai-id=...]"}]}
}
```

Output: one JSON object on stdout:

```json
{
  "status": "PASS",
  "executionMode": "real-browser",
  "browserVersion": "chromium-...",
  "consoleErrors": [],
  "pageErrors": [],
  "requestFailures": [],
  "checks": []
}
```

## Requirements

```text
Python playright package
Chromium browser binary
```

Install in the target environment:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

Run through Delivery:

```bash
python3 tools/verify_prototype_runtime.py \
  --prototype Prototype.html \
  --browser-runner python3 adapters/browser-runtime/playwright_runner.py \
  --require-real-browser \
  --out prototype-runtime.json
```

If Playwright is not installed, the adapter returns a contract error; it does not emit a fake PASS.
