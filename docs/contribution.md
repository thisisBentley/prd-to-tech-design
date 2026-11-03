# Contribution Guide

## Before opening a PR

- Keep portable core free of company-specific data.
- Use synthetic examples only.
- Do not add private endpoints, credentials, customer names, or internal business rules.
- Add or update tests/schemas for any contract change.
- Run `tools/sanitize_scan.py`.

## Design expectations

- Prefer contracts over provider-specific behavior.
- Add capability through adapters.
- Preserve artifact order and gate independence.
- Keep provider-specific terms inside provider directories.
