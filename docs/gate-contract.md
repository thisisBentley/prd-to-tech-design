# Gate Contract Hardening

This contract prevents a generation session from turning a shallow self-check into an evidence-free PASS.

## Invariants

1. **Evidence-first PASS.** Every PASS must contain a complete check ledger, non-empty evidence references, consumed-object hashes, and zero blocking findings.
2. **No empty-proof pass.** An empty `findings` array is not evidence. A PASS without executable checks is invalid and must be `INCOMPLETE`.
3. **Independent worker.** The candidate-producing session may seal a job, but only a `subagent`/`process` worker may write formal gate results and review evidence.
4. **Frozen scope.** Workers read only `.delivery/candidate-revisions/<revision>/`; hashes identify every consumed object.
5. **Recomputed Q1.** Q1 is computed from actual upstream results and findings; it is never copied from an expected table.
6. **Final consistency.** Bundle, state, seal, gate results, `Gates.md`, and `Workflow.md` must agree on revision and results.
7. **Incomplete blocks delivery.** Any `INCOMPLETE` check prevents finalization.

## Result files

- Gate Result v2: `.delivery/gate-results/<revision>/<GATE>.json`
- Summary v2: `.delivery/gate-results/<revision>/summary.json`
- Worker envelope: `.delivery/reviews/<reviewRunId>/envelope.json`
- Transcript/evidence: path recorded in the envelope.

## Validation commands

```bash
python tools/gate_contract_validator.py .delivery/gate-results/<revision>/*.json
python tools/validate_delivery_bundle.py 01-delivery
python tools/validate_source_provenance.py 01-delivery \
  --prd 01-delivery/PRD_DELIVERY.md \
  --prototype 01-delivery/Prototype.html \
  --overview 01-delivery/Overview.html
```

CI runs the adversarial tests in `tests/test_gate_contracts.py`. They intentionally reject the historical failure pattern: `result=PASS`, `findings=[]`, and no checks.

## Delivery readiness integrity

A Gate Result must be internally hash-consistent. Any `HASH_STABILITY` observation that differs from that gate's `objectHashes` invalidates the gate, even when `result=PASS`.

Final readiness is computed across:

```text
CONTENT_READY + EVIDENCE_READY + BUNDLE_READY
```

Use `tools/validate_prototype_binding.py` and `tools/verify_delivery_bundle_integrity.py`; see `docs/delivery-readiness.md`.
