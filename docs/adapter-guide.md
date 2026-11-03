# Adapter Guide

## Implement a provider

Create:

```text
adapters/<capability>/provider/<name>/
├── README.md
├── config.example.json
├── conformance.md
└── implementation files
```

## Requirements

1. Match the capability's `interface.json`.
2. Normalize provider-specific output to core schemas.
3. Return an explicit adapter failure state rather than an empty result.
4. Record scope and limitations in evidence metadata.
5. Never log or persist credentials.
6. For write functions, implement dry-run, confirmation hook, execution, and readback.

## Conformance checklist

- [ ] Read functions return normalized data
- [ ] Provider-specific IDs remain in adapter metadata
- [ ] Unauthorized/unavailable states are distinguishable
- [ ] Optional capabilities are declared
- [ ] Credentials come from host environment
- [ ] Write functions are disabled by default
- [ ] Write plans are complete and reviewable
- [ ] Execution verifies the result after writing
