# Artifact Profile

Artifact Profile is a portable routing decision for a requirement. It is a quality decision, not an external-platform or Jira decision.

```text
PRD_ONLY
PRD_PLUS_PROTOTYPE
EXISTING_PROTOTYPE_REVIEW
EXTERNAL_UI_BOUNDARY
UNKNOWN
```

## Rules

- `PRD_ONLY`: no local Prototype is produced; product, data, permission, action, exception, recovery and acceptance contracts remain required.
- `PRD_PLUS_PROTOTYPE`: Prototype Contract Preflight, U1/U2 as applicable, and clean runtime evidence are required.
- `EXISTING_PROTOTYPE_REVIEW`: inspect the supplied Prototype first; Prototype-only assumptions must become Contract Delta items before Core Freeze.
- `EXTERNAL_UI_BOUNDARY`: the external owner supplies the UI; record a UI Boundary Contract and do not invent a placeholder Prototype.
- `UNKNOWN`: do not infer the route. Create a product Decision Card or keep the workflow blocked.

`NOT_APPLICABLE` is a real outcome for an untriggered Prototype review. It must not be rewritten as `PASS`.
