# Security Policy

## Reporting

Please report security concerns privately to the repository maintainer.

## Safe use

- Do not commit credentials.
- Do not enable write adapters unless required.
- Use read-only adapters first.
- Confirm every external write plan explicitly.
- Keep company/customer examples out of this repository.

## Adapter security

Write adapters must support dry-run, confirmation, execution, and readback. A write result must never alter a quality-gate judgement.
