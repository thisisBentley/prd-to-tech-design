# P0.5 Delivery Quality Acceptance

P0.5 proves that Delivery is not only structurally complete, but can close realistic requirements with measurable quality, repair efficiency and replayability.

## Dataset rule

- Production acceptance requires **3 to 5 real requirements**.
- A sample is production-eligible only when it has real inputs, real evidence, independently reviewed results and replay evidence.
- Synthetic or mixed datasets may validate the measurement tool, but can never set `productionEligible=true`.
- Required dimensions across the sample set: simple PRD-only, complex permission/state, PRD+Prototype, Prototype semantic delete, existing capability/terminology, multi-round repair, decision/escalation.

## Required metrics

```text
Finding TP / FP / FN
Finding recall and precision
False-positive rate
Average repair rounds
Repeated root-cause count
Escalation and Decision counts
Open Escalation and Decision counts
FR / AC traceability
PRD/Prototype pair status
Unresolved delta
Stale Overview count
Runtime console errors
PRD_ONLY and PRD+Prototype P50 / P90 duration
Replay consistency
```

## Pass thresholds

```text
sample count                        3..5
required case coverage              all seven dimensions
finding recall                     100%
false-positive rate                <= 5%
traceability                       100%
pairStatus                          SYNCED for every Prototype profile
unresolved delta                    0
stale Overview                      0
runtime console errors              0
open Decisions / Escalations        0
replay consistency                  100%
```

The result is `PASS` only when these checks pass. `productionEligible=true` additionally requires `dataClassification=REAL` and 3 to 5 production-eligible samples.

## Commands

```bash
python tools/evaluate_delivery_quality.py \
  --input examples/p05/delivery-quality-baseline.json \
  --out /tmp/delivery-quality-result.json
```

The committed baseline is intentionally `SYNTHETIC` and must remain non-production. Replacing it with real samples is the remaining P0.5 acceptance activity.
