# Contributing

See `docs/contribution.md`.

Before submitting changes:

```bash
python tools/validate_json_schemas.py
python tools/sanitize_scan.py .
```

The sanitizer must report zero findings before publishing.
