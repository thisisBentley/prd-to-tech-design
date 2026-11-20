# External Gate Adapters

The external-gate boundary accepts QA and G1 observations but never treats an
unstructured success message as a PASS. Adapters preserve source provenance,
normalize the raw result and bind the canonical verdict to candidate hashes,
Jira identity and tool version.

```text
raw QA/G1 report
→ adapt_qa_g1_gate.py
→ canonical External Gate Verdict
→ cache_external_gate.py
→ compile_submission_contract.py
```

Reference implementation:

```bash
python scripts/adapt_qa_g1_gate.py \
  --report qa-report.json \
  --target-binding target-binding-report.json \
  --out qa-verdict.json
```

The adapter input contract is `references/external-gate-report.schema.json`.
The canonical output is `references/external-gate-verdict.schema.json`.

Hard boundaries:

- only `QA` and `G1` use this adapter;
- source report ID and evidence references are retained;
- environment failures remain `ENVIRONMENT_BLOCKED`;
- PASS with a BLOCKING finding is downgraded to `NEEDS_FIX`;
- the adapter cannot approve its own output or close a submission without the
  Submission Contract gate.
