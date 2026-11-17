# {{Requirement Name}} PRD_DELIVERY

## 0. Document control

- Requirement ID:
- Version:
- Author:
- Status:
- Change summary:
- Decision Impact Graph:

## 1. Background and current problem

{{Why now? What currently fails or creates cost?}}

### Actors and scenarios

{{Who is affected and in which scenario?}}

### Scope

{{Included in this release.}}

### Non-goals

{{Explicitly excluded.}}

## 2. Goals

- {{Observable business goal}}
- {{Success measure}}

## 3. Functional requirements

### FR-001 {{Title}}

{{Normative behavior.}}

- 运行类型: NON_RUNTIME | RUNTIME
- 运行原因: {{Only for RUNTIME: which result must be observed at runtime?}}

#### Acceptance criteria

- AC-001 [配置态]: Given..., when..., then the configuration is saved and readable.
- AC-002 [运行态]: Given..., when..., then the runtime result is observable.
  - 证据类型: STATE | LOG | QUEUE | ALERT | API | AUDIT_EVENT | DB | METRIC
  - 证据引用: {{Stable event, state, log, queue or audit reference}}

## 4. Business and interaction rules

| Rule | Trigger | Condition | Result |
|---|---|---|---|

## 5. States and permissions

| State/Role | Visible | Allowed | Result |
|---|---|---|---|

## 6. Data contracts

| Field | Meaning | Default | Validation | Failure |
|---|---|---|---|---|

## 7. Exceptions and recovery

| Failure | User-visible result | Data state | Recovery |
|---|---|---|---|

## 8. Decision impact closure

> Every closed Decision Card must declare affected objects, one expected invariant,
> zero unresolved conflicts and verification objects. The machine-readable copy
> lives in `decision-context.json#decisionImpact`.

| Decision | Selected option | Affected objects | Expected invariant | Conflicting objects | Verification objects |
|---|---|---|---|---|---|
| D-001 | A | FR-001, BR-001 | {{Invariant}} | None | AC-002 |

## 9. Open questions

- {{Question and owner}}
