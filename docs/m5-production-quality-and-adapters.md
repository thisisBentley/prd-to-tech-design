# M5 Production Quality and Research Adapter Harness

M5 closes two remaining engineering gaps after M4:

1. Research queries now execute through auditable read-only adapters.
2. Deterministic scaffold artifacts can no longer masquerade as production-quality delivery artifacts.

## Research adapter execution

```text
Research Request
→ configured source adapters
→ timeout + bounded exponential retry
→ normalized evidence records
→ attempt / latency / error ledger
→ Research Query Result
→ optional Research Package freeze and import
```

Commands:

```bash
python tools/run_research_queries.py \
  --request examples/research/research-request.example.json \
  --adapters examples/research/adapter-config.example.json \
  --out .agents/research/query-result.json

python tools/freeze_research_package.py \
  --root <packageRoot> \
  --requirement-key <issueKey> \
  --workflow-id <workflowId> \
  --classification REAL \
  --out <packageRoot>/manifest.json
```

The Delivery pipeline can execute the query stage directly:

```bash
python tools/delivery_pipeline.py ... \
  --research-request <request.json> \
  --research-adapters <adapters.json>
```

Source-specific execution is isolated in adapters. The bundled Jira adapter uses Project Management Space snapshots and never hardcodes issue fields into the Delivery core:

```text
adapters/research/providers/project_management_space_adapter.py
```

## Probe reliability

`detect_research_capabilities.py` now supports:

```text
--timeout
--retries
--backoff
```

Every source records attempt count, latency and actual errors. A timeout remains `CONFIGURED_ERROR`; it is not relabeled as unavailable or not configured.

## Production quality contract

`validate_delivery_artifacts.py` distinguishes:

```text
PASS / BLOCKED                 structural validity
PRODUCTION_CANDIDATE           semantic or externally provided production quality
BASELINE_ONLY                  deterministic scaffold
```

It checks:

- PRD sections and FR/AC traceability;
- Exceptions/Recovery;
- Prototype `data-ai-id` and FR/AC bindings;
- Prototype manifest alignment and placeholder leakage;
- Overview source hash and six review tabs;
- Jira four-part projection and FR coverage;
- PRD and downstream producer provenance separately.

Producer provenance is recorded by the actual worker:

```text
deterministic_worker.py     -> deterministic
m1_semantic_worker.py       -> semantic
artifact-source-dir input   -> provided downstream artifacts
```

`--producer-mode` alone cannot turn a deterministic PRD into a production candidate. The PRD producer mode is read from the Runtime Result.

## External production artifacts

M4/M5 pipeline can consume artifacts produced by the high-quality Delivery skills:

```bash
python tools/delivery_pipeline.py \
  --run-root <runRoot> \
  --requirement <requirement.md> \
  --workflow-id <id> \
  --requirement-name <name> \
  --artifact-profile PRD_PLUS_PROTOTYPE \
  --prototype-status TRIGGERED \
  --ui-ownership LOCAL \
  --worker <semantic-prd-worker.py> \
  --artifact-source-dir <artifactDir> \
  --producer-mode provided
```

Required artifact directory:

```text
PRD_PLUS_PROTOTYPE:
  Prototype.html
  prototype-manifest.json
  Overview.html
  Jira_Description.md

PRD_ONLY:
  Overview.html
  Jira_Description.md
```

The Pipeline still validates Pair, runtime, consistency, Overview projection, Semantic Coverage, Quality Exit, Handoff and replay. Supplying files does not bypass gates.

## COMPLETE Gate behavior

COMPLETE Gate now requires:

```text
artifact quality source binding = PASS
artifact quality = PRODUCTION_CANDIDATE in PRODUCTION mode
P0.5 benchmark replay = PASS
production-eligible real samples = true
replay = consistent
```

A deterministic baseline package can reach `PACKAGE_READY`, but it cannot reach production `COMPLETE`.

## Remaining boundary

- MCP adapters remain environment-specific commands. The harness records timeouts and retries; it does not invent MCP tools or contracts.
- The Jira adapter reads snapshots and attachment integrity. Deep binary/PDF extraction remains an adapter concern.
- Real production quality still requires high-quality semantic Producers supplied through the artifact source contract.
