# Research Adapter Contract

Research-First uses read-only adapters. It never treats a model assertion as evidence.

## Sources

| Adapter | Purpose | Typical evidence |
|---|---|---|
| Project Space / Jira | Current item, linked items, attachments, comments, history | issue key, attachment hash, updated time |
| MCP Mainline | Existing capability, symbols, routes and documented contracts | capability id, symbol, route, resource uri |
| MCP Code | Current code behavior, field mapping, state and permission checks | repository, revision, file path, symbol |
| Git | Historical implementation and merged changes | commit, branch, diff scope |
| Runtime / Tests | Actual behavior and current system constraints | run id, test result, log reference |

## Research request

```json
{
  "clue": "机器人命中_回答类型映射",
  "clueType": "FIELD_MAPPING",
  "queries": [
    {"source": "JIRA", "query": "回答类型 字段映射", "purpose": "find existing delivery precedent"},
    {"source": "MCP_CODE", "query": "answerType mapping", "purpose": "inspect current implementation"}
  ]
}
```

## Research result

Every query returns an evidence record with:

```text
source
sourceRef
claim
confidence
scope
limitations
status
```

Statuses: `CONFIRMED`, `CURRENT_MAINLINE`, `HISTORICAL_ONLY`, `UNVERIFIED`, `CONFLICTING`, `UNAVAILABLE`, `NOT_APPLICABLE`.

## Stop conditions

Stop when:

- an authoritative source uniquely determines the fact;
- the core implementation path is confirmed;
- budget is reached;
- remaining queries return duplicate claims;
- required evidence is unavailable due to permissions.

Unavailable sources must be recorded. They cannot be silently ignored.

## Output routing

- `FACT_RESOLVED`: write the fact into PRD / Decision Context; do not ask the product.
- `FACT_CONFLICT`: retain conflicting references and recommend a resolution.
- `NO_EVIDENCE`: state the searched scope and then decide whether the business outcome is genuinely undecided.
- `NEEDS_BUSINESS_DECISION`: create a research-backed Decision Card.

## Budget

The default budget follows the shared Project Management Space research budget. Cache keys must include source revision/hash and query identity. Downstream Delivery and Tech Solution reuse the Evidence Ledger instead of re-reading all sources.
