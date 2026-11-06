# Methodology

AI Native Delivery divides product work into two independent capabilities:

1. **Discovery** — understand the problem, gather evidence, compare candidate capabilities, and converge on product decisions.
2. **Delivery** — assemble authoritative inputs and produce a gated delivery bundle.

The workflow engine is the execution core used by Delivery. It may also be used directly.

## Operating principles

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
   - A file change triggers only the required reruns.

7. **Explicit external writes**
   - Core execution is local and read-only by default.
   - Any external write requires an adapter, configuration, and separate user confirmation.

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
