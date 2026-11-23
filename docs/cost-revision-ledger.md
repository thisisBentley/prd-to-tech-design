# Cost / Revision Ledger

## Purpose

The Cost / Revision Ledger makes one Delivery run auditable along two dimensions that are usually lost across retries:

- how many revisions were produced and why;
- how much execution time, transcript volume and repair activity was actually observed.

It is a measurement artifact. It does not prove business quality, replace the Delivery Quality Exit, or unlock M7 Exit.

## Build

```bash
python3 tools/build_cost_revision_ledger.py \
  --run-root <run-root> \
  --workflow-id <workflow-id> \
  --bundle <run-root>/01-delivery \
  --revision <final-revision> \
  --consumer-report <optional-consumer-acceptance-report.json> \
  --out <run-root>/.agents/quality/cost-revision-ledger.json
```

`delivery_pipeline.py` builds the ledger automatically after finalization and adds it to `package-evidence.json` and the Delivery Complete input manifest. The final package is rebound to the post-Repair revision before this happens.

## Sources

The ledger aggregates, when present:

- Agent Runtime records and transcripts;
- Audit Stage telemetry and job input counts;
- Bounded Repair cycles and changed artifacts;
- Candidate Seals for each observed revision;
- External Skill Finding ingestion;
- Consumer Acceptance Reports supplied with `--consumer-report`.

Every source is recorded with its absolute path and SHA-256. Missing sources remain explicit `MISSING` entries instead of disappearing from the ledger.

## Metrics Contract

`observedElapsedMs`, `observedTranscriptBytes`, `auditJobs`, `auditInputFiles` and `repairRounds` are observed facts from local artifacts.

`estimatedTranscriptTokens` is **not** provider-reported token usage. It is:

```text
ceil(transcriptBytes / 4)
```

It is useful for comparing runs with the same runtime and prompt shape. It must not be used as a billing number or as an input/output token split.

Human touch time has no reliable timer in the current runtime. It is therefore always emitted as:

```json
{
  "status": "UNAVAILABLE",
  "elapsedMs": null,
  "reason": "No human timer, review duration or calibrated human-touch source is attached to this run."
}
```

## Status Semantics

| Status | Meaning |
|---|---|
| `COMPLETE` | Every observed stage — Runtime, Audit, Repair, External Finding ingestion and Consumer Acceptance — exposes machine timing/volume telemetry, and the final revision is present. Human touch may still be unavailable. |
| `PARTIAL` | At least one machine stage has incomplete timing or coverage; totals are lower bounds. |
| `INSUFFICIENT` | No Audit or Runtime telemetry exists. A zero total means “not measured”, not “zero cost”. |

The ledger deliberately keeps repair duration and consumer review duration as evidence gaps when their source artifacts do not expose timestamps. Adding estimated values would make cost comparisons look more precise than the underlying evidence.

## Revision Binding

Each revision entry includes:

- observed Audit statuses;
- source references;
- Candidate Seal path and hash when available;
- canonical artifact snapshot hash from `artifactHashes`;
- artifacts changed by the preceding Repair round.

The Delivery Pipeline must publish `package-evidence.revision` equal to `candidate-seal.revision`. A repaired run may not retain r1 artifact hashes under an rN delivery.

## Non-Goals

- No provider billing reconciliation;
- no human effort inference from transcript size;
- no quality score;
- no automatic M7 Exit credit;
- no training approval.
