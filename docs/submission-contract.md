# M7.6-B External Gate Oracle and Submission Contract

The Submission Contract is the only local authority allowed to say that a
candidate is externally closed. Trust Kernel `READY`, candidate sealing and
internal review can prepare a submission, but they cannot replace Jira QA/G1.

## Flow

```text
QA/G1 report
→ adapt_qa_g1_gate.py
→ canonical External Gate Verdict
→ cache_external_gate.py
→ content-addressed verdict cache
→ compile_submission_contract.py
→ Submission Contract + Bundle Manifest
→ validate_submission_contract.py
→ CLOSED / PENDING / FAILED / ENVIRONMENT_BLOCKED / BLOCKED
```

## Policy-selected gates

Required gates are selected by `config/trust-kernel/submission-policy-v1.json`,
not by a user choosing a workflow. The request must still declare the gates it
believes are required, and it blocks when that declaration differs from policy.

For a specialist PRD/Overview submission, policy requires:

```text
QA
G1
```

## Commands

```bash
python3 scripts/adapt_qa_g1_gate.py \
  --report qa-report.json \
  --target-binding target-binding-report.json \
  --out qa-verdict.json

python3 scripts/cache_external_gate.py \
  --verdict qa-verdict.json \
  --cache-dir .submission/gate-cache

python3 scripts/compile_submission_contract.py \
  --request submission-request.json \
  --out submission-contract.json \
  --manifest-out submission-bundle-manifest.json

python3 scripts/validate_submission_contract.py \
  --contract submission-contract.json \
  --manifest submission-bundle-manifest.json \
  --out submission-readiness.json
```

## Status precedence

```text
hash drift / target drift / tool drift / cache conflict
→ BLOCKED

external environment failure
→ ENVIRONMENT_BLOCKED

external NEEDS_FIX / REJECTED
→ EXTERNAL_GATE_FAILED

required gate missing or UNKNOWN
→ EXTERNAL_GATE_PENDING

all required gates PASS
→ CLOSED
```

Only `CLOSED` sets `closureEligible=true`.

## Verdict cache

The cache key is content-addressed and excludes timestamps. It includes:

```text
workflow / candidate revision
Jira key
gate type
tool id / version / source commit
candidate artifact paths and actual SHA-256
target binding report id
canonical verdict / findings
```

Repeated runs with the same candidate evidence and result reuse one cache entry.
Different verdicts for the same evidence key are a conflict and block instead of
silently taking the latest value.

## Submission bundle manifest

The manifest binds:

```text
Submission Contract id
candidate hashes
Jira target
specialist tool version
required gates
selected external verdict cache keys
Trust Kernel run id
target binding report id
replayable content SHA-256
```

The contract stores `submissionManifestSha256`; the validator recomputes the
manifest content hash and fails on drift.

## Final Gate integration

`final_gatekeeper.py` now checks both:

```text
FINAL.TRUST_KERNEL.BINDING
FINAL.SUBMISSION.CONTRACT
```

Missing, non-READY, non-CLOSED or hash-drifting evidence fails closed. Legacy
waiver flags remain explicit failures and cannot produce a production PASS.

## Boundary

M7.6-B does not repair findings, generate a new candidate revision or train a
model. It proves that the current candidate has an authoritative external gate
result. Bounded repair remains M7.6-D and training remains `HOLD`.
