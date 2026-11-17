# Semantic Closure, Runtime AC and External Contract Hardening

This document defines the M7 hardening controls that close roadmap blockers
`B-022`, `B-023` and `B-024` in code and contract form.

## 1. Decision Impact Graph

A Decision Card may be `confirmed` or `closed`, but that does not prove its
business result has propagated to the authoritative delivery objects.

Every closed decision must add `decisionImpact` to its Decision Context entry:

```json
{
  "decisionImpact": {
    "affectedObjects": [
      {
        "objectId": "FR-004",
        "objectType": "FR",
        "artifact": "PRD_DELIVERY.md",
        "evidenceRefs": ["PRD_DELIVERY.md#FR-004"]
      }
    ],
    "expectedInvariant": "Parameter processing uses one rule in G-002, FR-004, BR-004 and AC-010.",
    "conflictingObjects": [],
    "verificationObjects": [
      {
        "objectId": "AC-010",
        "objectType": "AC",
        "artifact": "PRD_DELIVERY.md",
        "evidenceRefs": ["PRD_DELIVERY.md#AC-010"]
      }
    ],
    "evidenceRefs": ["PRD_DELIVERY.md"]
  }
}
```

`build_decision_impact_graph.py` fails closed when:

- a closed decision has no impact declaration;
- `affectedObjects` or `verificationObjects` is empty;
- an object or evidence reference cannot be resolved;
- an object is both affected and conflicting;
- no verification object is an AC, test plan, Prototype or evidence object.

The output is `decision-impact-graph.json`, bound to the PRD hash. A sidecar
`--impact-input` file may be supplied when the producer maintains the graph
outside the Decision Context.

## 2. Runtime AC Coverage

Runtime behavior cannot be accepted only because a configuration field can be
saved. Every runtime-relevant FR must contain both:

```text
配置态 AC
+ 运行态 AC
+ 证据契约
```

Template:

```markdown
### FR-001 Runtime counter

- 运行类型: RUNTIME
- 运行原因: The accumulated count must be observable after real events.

#### Acceptance criteria

- AC-001 [配置态]: The threshold can be saved and read back.
- AC-002 [运行态]: A real event increments the count and writes a queue record.
  - 证据类型: QUEUE
  - 证据引用: counter-events
```

Runtime relevance is explicit through `运行类型: RUNTIME`, or detected from
runtime keywords such as queueing, counting, arbitration, recovery and state
transition. A runtime AC must name at least one evidence type:

```text
STATE / LOG / QUEUE / ALERT / API / AUDIT_EVENT / DB / METRIC
```

The policy file is `config/runtime-ac/runtime-ac-policy.json`. The validator is
`validate_runtime_ac_coverage.py`.

## 3. External Skill Contract Profile and Source Lock

An external Skill is not allowed to become the first place where artifact
structure, metadata or review timing is checked.

A profile declares:

- the external Skill source path and SHA-256;
- applicable artifact profiles;
- required artifacts and formats;
- regex, literal text and JSON-key checks;
- review timing relative to candidate and final seal.

The neutral open-source profile is:

```text
config/external-skills/delivery-external-v2.3.0.profile.json
```

A private environment can keep its own profile and pass `--external-skill-source`
to validate the actual local Skill source. Hash drift blocks the result.

`validate_external_skill_contract.py` checks the locked source and every
applicable artifact before the final seal. Its result is
`external-skill-contract.json`.

## 4. Pipeline integration

`delivery_pipeline.py` supports independent modes:

```text
--semantic-closure-mode off|advisory|gate
--runtime-ac-mode off|advisory|gate
--external-contract-mode off|advisory|gate
```

Defaults are `advisory` for compatibility with baseline fixtures. Production
candidate runs must set all three to `gate`. A gate failure returns:

```text
HARDENING_BLOCKED
```

Reports are written under:

```text
01-delivery/.delivery/hardening/
├── decision-impact-graph.json
├── runtime-ac-coverage.json
├── external-skill-contract.json
└── hardening-summary.json
```

The summary is included in package evidence. `verify_delivery_bundle_integrity.py`
re-checks that every gate-mode report is `PASS`; the reports and source hashes
are therefore part of `EVIDENCE_READY`, not merely side logs.

## 5. Policy and audit mapping

The following blocking rules are added to `gate-policy-current.json`:

```text
G1.DECISION_IMPACT_CLOSURE
QA.RUNTIME_AC_COVERAGE
Q1.EXTERNAL_SKILL_CONTRACT
```

They are mapped in `delivery-toolbox-v2.json` to deterministic and semantic
executors so the audit track cannot omit them from applicable rule coverage.
