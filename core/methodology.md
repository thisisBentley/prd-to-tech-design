# Methodology

AI Native Delivery divides product work into three stages and a controlled review network:

1. **Discovery** — understand the current state, gather evidence and close product decisions.
2. **Delivery** — convert accepted facts into a product contract.
3. **Tech Solution** — convert the accepted product contract into a technically feasible, testable and operable solution.

Each stage has a producer role. Downstream consumers review upstream sufficiency. Independent reviewers challenge each stage. The deterministic Gatekeeper verifies the complete review chain.

The workflow engine remains the execution core used by Delivery. It may also be used directly.

## Operating principles

0. **Separation of duties**
   - The producer of a stage cannot review or approve its own work.
   - A downstream consumer may return upstream work but cannot rewrite upstream facts.
   - Reviewers use frozen artifacts and independent contexts.

1. **Independent entry points**
   - Discovery can run without Delivery.
   - Delivery can run without Discovery.
   - Discovery output is an optional input source, not a mandatory gate.

2. **Evidence before assertion**
   - Existing-capability claims need a source, confidence level, and limitation.
   - Absence of search evidence is not proof that a capability does not exist.

3. **One fact source**
   - `PRD_DELIVERY.md` is the sole business fact source.
   - Generated projections and summaries never introduce new business facts.

4. **Independent quality lenses**
   - R0, G1, O1, U1, U2, and QA judge their own objects.
   - Q1 is the only bundle-level aggregate conclusion.

5. **Root-cause finding identity**
   - Findings use `requirementId + artifact + rootCause`.
   - Multiple lenses discovering the same cause produce one finding.

6. **Hash-based consistency**
   - Artifacts and gate results bind to hashes.
   - Any candidate change creates a new revision and triggers the full formal gate set.

7. **Explicit external writes**
   - Core execution is local and read-only by default.
   - Any external write requires an adapter, configuration, and separate user confirmation.

## Collaboration routes

```text
Discovery Producer
→ Delivery Intake Review
→ Delivery Producer
→ Delivery Review + QA Red Team
→ Tech PRD Diagnosis
→ Tech Producer
→ Tech Review
→ Product Acceptance Review
→ Gatekeeper
```

Returned work goes back to its producer with a new revision. Unresolved business choices become Decision Cards; unresolved agent disagreement becomes an Escalation.

## Discovery route

```text
Input
→ Issue snapshot
→ Related-work search
→ Knowledge search
→ Code intelligence search
→ Optional Git evidence
→ Capability ideation
→ Capability matrix
→ Product questions
→ Requirement Brief
→ Concept Handoff
```

## Delivery route

```text
Input assembly
→ PRD
→ Manifest
→ Issue description
→ Overview
→ Prototype trigger
→ Gates
→ QA
→ Q1
→ Finding repair/rerun
→ Sealed bundle
```

Artifact display order remains fixed even when execution details differ.
