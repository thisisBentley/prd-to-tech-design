# Observer v0

## Purpose

Observer v0 produces a deterministic, read-only analysis over existing delivery evidence:

    Finding Ledger
    Repair Cycle
    Cost / Revision Ledger
    Rehearsal Corpus
    Challenger Run
    Project Episode
    -> Observer Report

It highlights repeated root causes, observed repair effects, Challenger gaps, cost telemetry coverage and next actions. It does not infer causality.

## Authority

    readOnly: true
    resultAuthority: NONE
    releaseEligible: false
    trainingEligible: false
    causalClaims: false

Recommendations are advisory. changeSetRequired is always false; a separate human decision and controlled Change Set are required before any modification.

## Analysis

### Root Causes

The Observer groups Finding Ledger entries by rootCauseId and reports finding count, open blocking count, repair attempts, rule IDs and source references.

### Repair Effect

The Observer compares available open-blocking counts before and after the recorded Repair Cycle.

    IMPROVEMENT_OBSERVED
    NO_IMPROVEMENT_OBSERVED
    INSUFFICIENT_DATA
    NOT_AVAILABLE

This is a deterministic observation. It is not a causal claim that the repair alone produced the outcome.

### Challenger Patterns

When a Challenger Run exists, results are grouped by failure signal: DETECTED, MISSED, INCOMPLETE and ERROR. Without a Challenger Run the Observer remains PARTIAL and recommends a real or externally observed challenge run.

### Cost / Quality

Cost metrics are copied as descriptive observations. The Observer does not claim that a token or time change caused a quality change.

## Build

    python3 tools/build_observer_report.py \
      --episode .agents/quality/project-episode.json \
      --finding-ledger 01-delivery/.delivery/findings.json \
      --repair-cycle .agents/audit/repair-cycle-report.json \
      --cost-ledger .agents/quality/cost-revision-ledger.json \
      --corpus .agents/quality/rehearsal-corpus.json \
      --challenger-run .agents/quality/challenger-run.json \
      --out .agents/quality/observer-report.json

The delivery pipeline builds and validates the report after Challenger execution or after the corpus when Challenger mode is off.

## Status

    READY    all required analysis inputs exist and Episode is complete
    PARTIAL  missing optional evidence or Episode is partial
    BLOCKED  Episode is blocked or source identities conflict

## Validate

    python3 tools/validate_observer_report.py \
      --report .agents/quality/observer-report.json \
      --verify-source-hashes

Validation enforces read-only authority, no release or training eligibility, no causal claims, no automatic Change Set requirement and source hash stability.

## Non-goals

- no Prompt mutation;
- no candidate mutation;
- no release decision;
- no training decision;
- no automatic optimizer.
