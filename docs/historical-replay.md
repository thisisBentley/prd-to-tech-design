# Historical Consumer Replay

Historical replay validates whether the current delivery system can still read and
assess prior real delivery packages. It is a compatibility and regression check,
not an M7 Exit sample.

## What it answers

```text
Can the current checker understand legacy PRD / Overview / Prototype packages?
Which historical content is still reviewable?
Which gaps are real content gaps?
Which gaps are only missing modern contracts or machine bindings?
Did a stricter version accidentally stop recognizing valid legacy structures?
```

It does not answer whether an unseen new requirement can pass end to end.

## Inputs

A replay spec maps each historical case to:

```text
caseId
sourceRoot
artifactProfile
prd / overview / prototype / jira / runtime / gatesDir
```

The runner reads only those files. It never modifies historical packages.

## Commands

```bash
python3 scripts/run_historical_consumer_replay.py \
  --spec config/consumer-acceptance/historical-replay-samples-v1.json \
  --out-dir outputs/historical-consumer-replay-v1
```

## Result states

```text
REPLAY_PASS      core content is reviewable and no material historical gap remains
REPLAY_PARTIAL   content is readable but newer evidence or machine contracts are missing
REPLAY_BLOCKED   core content or required consumer evidence is missing
```

`versionCompatibility` is separate from `contentReadiness`:

```text
versionCompatibility: PASS | PARTIAL | FAIL
contentReadiness:     READY | PARTIAL | BLOCKED
```

A legacy package can be parseable (`PARTIAL`) while still being blocked by missing
FR/AC traceability or Prototype bindings.

## Legacy handling

The replay adapter recognizes:

- Chinese PRD section names;
- nested Overview headings without truncating tab content;
- source PRD metadata without a source hash;
- `data-testid`, `data-page-menu-sn`, `data-business-zone` and `data-metric-key`
  as legacy prototype bindings;
- legacy runtime evidence containing `loaded`, `mount` or `status=PASS`;
- historical G1/QA/U1/U2 JSON gate results.

Legacy recognition does not relax current production gates. It only lets us tell
compatibility gaps from content gaps.

## Hard boundary

```text
caseClassification = HISTORICAL_REPLAY
m7ExitEvidenceEligible = false
```

Historical replay cannot be counted as one of the two unseen REAL cases required
for M7 Exit. It cannot authorize training or release.
