# Challenger v0

## Purpose

Challenger v0 executes frozen Rehearsal Corpus scenarios through an isolated
worker. It tests whether the system detects known negative conditions.

```text
Rehearsal Corpus
→ Frozen Challenge Jobs
→ Isolated Worker Execution
→ Scenario Results
→ Challenge Run
```

Challenger is not an audit, release gate or training pipeline.

## Authority

```json
{
  "readOnly": true,
  "mayModifyArtifacts": false,
  "resultAuthority": "NONE",
  "releaseEligible": false,
  "trainingEligible": false
}
```

Challenger cannot modify candidates and cannot issue PASS.

## Modes

Pipeline integration supports:

```text
off        no challenger execution
advisory   execute and record results without blocking finalization
gate       execute and block finalization unless outcome is ALL_DETECTED
```

`off` is the default. Existing runs are unaffected until a worker is supplied.

## Worker Protocol

Command:

```bash
python3 tools/run_challenger.py \
  --corpus rehearsal-corpus.json \
  --run-root . \
  --artifact-root 01-delivery \
  --out challenger-run.json \
  --worker python3 path/to/challenger_worker.py
```

The worker receives:

```text
--job <frozen-challenger-job.json>
--out <scenario-result.json>
```

Worker result:

```json
{
  "schemaVersion": 1,
  "jobId": "CHALLENGE-RS-...",
  "scenarioId": "RS-...",
  "status": "DETECTED",
  "observedFailureSignal": {
    "kind": "RULE_NOT_PROVEN",
    "description": "negative condition detected"
  },
  "evidenceRefs": ["..."],
  "checkedAt": "2026-11-23T00:00:00Z"
}
```

Status values:

```text
DETECTED    expected failure signal observed
MISSED      negative condition was not detected
INCOMPLETE  worker could not complete the scenario
ERROR       invalid output or worker failure
```

## Outcomes

```text
ALL_DETECTED  every scenario was detected
GAPS_FOUND    one or more scenarios were missed
INCOMPLETE    one or more scenarios were incomplete
BLOCKED       worker error, corpus drift or candidate mutation
```

`GAPS_FOUND` is useful evidence. It is not a PASS or FAIL release verdict.

## Isolation Checks

The runner records candidate and corpus hashes:

```text
artifactSnapshotSha256Before
artifactSnapshotSha256After
corpusSha256
```

A changed candidate or changed corpus makes the challenge run `BLOCKED`.

## Pipeline Integration

```bash
python3 tools/delivery_pipeline.py \
  ... \
  --challenger-mode advisory \
  --challenger-worker python3 path/to/challenger_worker.py
```

In `gate` mode, successful finalization requires:

```text
challenger.status = COMPLETE
challenger.outcome = ALL_DETECTED
```

Even then, Challenger remains a negative-test signal, not a release authority.

## Non-goals

- no candidate modification;
- no external release approval;
- no training approval;
- no replacement for independent Audit;
- no claim that Fixture workers prove production quality.
