# Security and Data Policy

## Default posture

- Execute locally.
- Read adapters only.
- External writes disabled.
- No credential storage in the repository.
- No implicit network access requirement.

## Secret handling

Adapters must receive credentials through their host environment. A run must never:

- Copy credentials into artifacts
- Log credential values
- Add credentials to `state.json`
- Commit credential files
- Echo secrets in summaries

## Evidence handling

- Record source identity and stable references.
- Avoid copying large bodies of private content when a reference is sufficient.
- Redact personal data unless it is necessary and permitted.
- Mark runtime claims as unverified when only static evidence exists.

## Write adapters

A write adapter must:

1. Be explicitly configured.
2. Declare required permissions.
3. Dry-run by default.
4. Show a complete change plan.
5. Require separate user confirmation for each execution.
6. Read back the result.
7. Record success, partial success, or failure without changing gate conclusions.

## Publishing

Before publishing a fork or example:

1. Run `tools/sanitize_scan.py`.
2. Remove private history and private examples.
3. Confirm all case data is synthetic or licensed for redistribution.
4. Confirm the selected license and notice.
