# Delivery State Contract

Read the canonical contract:

```text
../../core/state-contract.md
```

Delivery may initialize state when absent and writes only `phase2`.

Delivery can run without Discovery. If Discovery output exists, record it in `inputSources`; do not treat it as mandatory.
