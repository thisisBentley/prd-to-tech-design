# M4 Unified Delivery Pipeline

M4 closes the gap between independently working Delivery components and one executable package pipeline.

## Entry point

```bash
python tools/delivery_pipeline.py \
  --run-root <runRoot> \
  --requirement <requirement.md> \
  --workflow-id <workflowId> \
  --requirement-name <name> \
  --artifact-profile PRD_PLUS_PROTOTYPE \
  --prototype-status TRIGGERED \
  --ui-ownership LOCAL
```

Optional source-backed inputs:

```text
--research-package <dir>       verified Research Evidence Package
--semantic-input <json>        independent semantic evidence ledger
--benchmark-input <json>       P0.5 3..5 sample batch
--comparison-run-root <dir>    second run for replay evidence
```

## Flow

```text
Init / plan
→ Import Research Evidence Package (optional)
→ Decision Readiness + persist Research Records / TECH gaps
→ PRD Producer
→ Delivery / QA / Tech / initial Semantic Review
→ Finding Consolidation
→ Repair / Recheck
→ Prototype generation and Pair reconciliation
→ final Semantic Review + deterministic coverage
→ Overview projection
→ Jira Description projection
→ Quality Exit
→ Final Package Review
→ Delivery Gatekeeper
→ Delivery Handoff
→ P0.5 benchmark collection
→ Delivery COMPLETE Gate
```

PRD-only and Prototype profiles converge on the same final package contract.

## Harness guarantees

- The core loop stops at `PRD_CORE_READY` before artifact-phase work. A profile cannot silently “finish” with only a PRD.
- A final Semantic Review is added after Prototype and Pair creation. The initial PRD-only semantic review cannot substitute for the final Pair review.
- Semantic coverage compares PRD FR/AC/BR identifiers, Prototype `data-ai-id` bindings, declared states and known Capability Context terms against the frozen evidence ledger.
- Quality Exit checks the actual package: PRD, Overview, Jira Description, optional Prototype, Pair status, runtime, Overview projection, normalized semantic evidence and technical-gap evidence.
- `DELIVERY-QUALITY-EXIT` now runs the deterministic quality tool as its worker; it is not a synthetic review result.
- Research packages are hash-verified before import. Imported decisions and Research Records become frozen Agent Task inputs.
- TECH-owned `NO_EVIDENCE` and `FACT_CONFLICT` records are forwarded as `technicalUnknowns`; they do not become unnecessary product Decision Cards.
- The COMPLETE Gate replays semantic evidence and P0.5 benchmark data from their frozen inputs.
- A single synthetic run produces `PACKAGE_READY` but the COMPLETE Gate remains `BLOCKED` because production samples and a real replay are absent.

## Research lifecycle

```text
Research package
→ verify manifest hashes
→ import records / decisions / capability registry
→ persist Research Index and technical gaps
→ include evidence in Agent Task inputs
→ Decision Readiness consumes it
→ Quality Exit validates imported records
→ Handoff forwards TECH gaps
→ COMPLETE Gate checks the index and retained records
```

The package producer remains adapter-driven: Project Management Space, MCP, Git or another read-only adapter can create the package. The Delivery Harness owns verification, routing, consumption and replay, not source-specific API semantics.

## P0.5 runner

```bash
python tools/run_quality_benchmark.py \
  --samples <sample-batch.json> \
  --out-dir <quality-output>
```

Each sample points to a real run and ground-truth findings. The collector derives:

- expected vs detected findings;
- Repair rounds and repeated root causes;
- Decisions and Escalations;
- FR/AC traceability;
- Pair, Overview and runtime status;
- P50/P90 duration;
- replay hash.

A dataset is production eligible only when it is `REAL`, contains 3-5 production-eligible samples, and every metric check passes.

## Current limits

- Built-in Prototype, Overview and Jira generators are deterministic projections intended to prove the orchestration contract. They do not replace the high-quality semantic producers.
- Source-specific Jira/MCP query execution remains an adapter responsibility. M4 verifies and routes the resulting evidence package.
- A production declaration still requires 3-5 real samples, real ground truth and a second-run replay.

## Delivery Readiness finalize gate

`delivery_pipeline.py` defaults to `--readiness-mode gate`. The final report is `PACKAGE_READY` only when all three dimensions pass:

```text
CONTENT_READY + EVIDENCE_READY + BUNDLE_READY
```

Otherwise the pipeline returns `PACKAGE_BLOCKED`, writes `.agents/delivery-readiness.json`, and records the dimension booleans in `.agents/quality/delivery-pipeline-report.json`. Use `--readiness-mode advisory` only for structural smoke runs.
