# Source Provenance

A delivery bundle must prove that each downstream artifact was built from the same PRD version.

## Checks

- PRD version is resolvable.
- Prototype declares its source PRD version and matches the PRD.
- Overview declares its source PRD version when available and matches the PRD.
- `.delivery/ui-pack.lock.json` exists for triggered prototypes.
- UI Pack hashes and U1/U2 gate versions are present.
- Any artifact-to-PRD mismatch blocks finalization.

## Command

```bash
python tools/validate_source_provenance.py 01-delivery \
  --prd 01-delivery/PRD_DELIVERY.md \
  --prototype 01-delivery/Prototype.html \
  --overview 01-delivery/Overview.html
```

The validator is intentionally conservative: a prototype without a declared `source-prd-version` fails provenance validation rather than being accepted by assumption.

This directly regression-tests the ZY20250117-779 failure where the prototype metadata referenced PRD v1.23 while the delivery bundle used PRD v1.1.
