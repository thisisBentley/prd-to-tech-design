# M6 Production Runtime, Producers and Research Closure

M6 closes the three highest-priority gaps from the production-readiness assessment.

## 1. Real browser runtime

`verify_prototype_runtime.py` now distinguishes:

```text
STATIC_CONTRACT    static HTML check only
BROWSER_ADAPTER    browser adapter returned evidence
REAL_BROWSER       Playwright/Chromium execution evidence
```

Static fallback remains useful for controlled baseline runs, but it cannot make an artifact a `PRODUCTION_CANDIDATE`.

The bundled provider is:

```text
adapters/browser-runtime/playwright_runner.py
```

It requires Playwright and Chromium. It records:

- browser version;
- page load;
- click actions;
- console errors;
- page errors;
- request failures;
- runtime checks.

Delivery pipeline forwarding:

```bash
python tools/delivery_pipeline.py ... \
  --browser-runner python3 adapters/browser-runtime/playwright_runner.py \
  --require-real-browser
```

`Artifact Quality` requires `RUNTIME.REAL_BROWSER` for production candidate Prototype packages.

## 2. Producer Registry

`producer-registry.schema.json` defines command-based artifact producers for:

```text
prd
prototype
overview
jira
semantic-evidence
```

`run_producer.py` sends a frozen JSON request on stdin and verifies required artifacts and hashes.

```bash
python tools/run_producer.py \
  --registry producer-registry.json \
  --kind prototype \
  --workflow-id WF-1 \
  --run-root <runRoot> \
  --output-dir <producer-out> \
  --prd <PRD_DELIVERY.md> \
  --requirement <requirement.md> \
  --out <producer-result.json>
```

`delivery_pipeline.py --producer-registry` may now use registered Prototype, Overview, Jira and Semantic Evidence producers. Registered semantic producers do not fall back to deterministic generation.

## 3. Research Synthesizer and Decision Closure

`synthesize_research.py` turns Query Results into:

```text
Research Record
TECH gap
PRODUCT Decision Card candidate
research/index.json
technical-gaps.json
```

It only resolves a fact when a query result contains claims and evidence. Conflicting or missing evidence remains `FACT_CONFLICT` / `NO_EVIDENCE`; product ownership is explicit.

`close_decision.py` closes a Decision Card and emits:

```text
decision-resync.json
requiresPrdResync = true
```

The Pipeline supports:

```bash
--research-request       execute adapter queries
--research-adapters      adapter command config
--decision-closure       apply a confirmed Decision Card before PRD work
```

If a synthesized product decision remains open, the Pipeline stops at `DECISION_REQUIRED`; it does not write a PRD using an invented default.

## Quality semantics

```text
PACKAGE_READY            full package and Quality Exit passed
BASELINE_ONLY            deterministic or static-runtime package
PRODUCTION_CANDIDATE     semantic/provided PRD + semantic/provided downstream artifacts + real browser evidence
COMPLETE                 production candidate + 3..5 real eligible samples + replay
```

## Remaining environment boundaries

- MCP/Git adapters still need environment-specific commands and credentials.
- Playwright/Chromium must be installed for REAL_BROWSER evidence.
- PDF/Office/XMind extraction remains an adapter concern.
- High-quality semantic producers must be supplied by the target runtime or model environment.
