# Delivery Control Plane

`Delivery Control Plane` verifies that one Delivery completion is represented consistently across execution, readiness, seals and orchestration.

It closes two concrete failure modes:

```text
Delivery state says DESIGN_READY
but orchestration still says DISCOVERY_AUTHORING

current revision says r19
but active evidence still points to r11, r16 or r17
```

## Contract

```text
Orchestration
↔ Delivery State
↔ Readiness
↔ Candidate / Final Seal
↔ Handoff
```

A Delivery cannot be treated as complete unless:

- Delivery state, Candidate Seal, Final Seal, Readiness and Handoff bind one revision;
- Delivery state, orchestration and handoff bind one `workflowId`;
- readiness is `DESIGN_READY` with `designReady=true`;
- the latest Delivery handoff is current, closed and registered in orchestration;
- orchestration is at `DELIVERY_SEALED` or a later non-blocked stage.

## Commands

Synchronize a completed Delivery handoff:

```bash
python tools/orchestrate.py sync-delivery \
  --run-root <runRoot> \
  --handoff <delivery-handoff.json> \
  --revision <revision>
```

Validate the complete control plane:

```bash
python tools/validate_delivery_control_plane.py \
  --run-root <runRoot> \
  --bundle <runRoot>/01-delivery \
  --readiness <runRoot>/.agents/delivery-readiness.json \
  --out <runRoot>/.agents/quality/delivery-control-plane.json
```

## Active Evidence Revision Isolation

Delivery integrity now scans active evidence only:

```text
.delivery/*.json
.delivery/gate-results/<current-revision>/**
.delivery/reviews/<current-reviewRunId>/**
```

Archived revisions under `.delivery/candidate-revisions/**` are excluded. Historical references must use explicit historical fields, for example:

```text
historicalEvidenceRefs
archivedEvidenceRefs
supersededEvidenceRefs
```

Any current evidence reference to another revision fails:

```text
INTEGRITY.ACTIVE_EVIDENCE_REFS
→ EVIDENCE_BLOCKED
```

This is an evidence-freshness check. It does not replace the Evidence Resolver: path existence, fragment resolution and semantic support remain separate requirements.

## Derived Evidence Rebuild

Changing evidence in a sealed revision is a new revision event. Do not patch evidence in place.

```bash
python tools/rebuild_derived_evidence.py \
  --bundle <runRoot>/01-delivery \
  --source-revision r19 \
  --target-revision r20 \
  --manifest-out <runRoot>/.agents/quality/derived-rebuild-manifest.json
```

The rebuild tool:

- copies the sealed source candidate to a new revision;
- rewrites references only when the target artifact exists;
- remaps line fragments through exact content or stable HTML anchors;
- regenerates the semantic review from the rebuilt evidence ledger;
- recomputes the new Candidate Seal;
- scans the rebuilt active evidence and fails on any remaining stale revision reference;
- emits `DerivedRebuildManifest`.

`--activate` archives the prior active evidence and old Final Seal before promoting the clean candidate. This intentionally invalidates the previous final review. Formal R0/G1/O1/U1/U2/QA/Q1 re-review and a new Final Seal are still required.
