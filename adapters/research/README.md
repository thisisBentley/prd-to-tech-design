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


## Executable harness

```bash
python tools/run_research_queries.py   --request research-request.json   --adapters adapter-config.json   --out research-query-result.json   --out research-query-result.json
```

An adapter command receives one query request JSON on stdin and returns:

```json
{
  "status": "OK",
  "records": [
    {
      "sourceRef": "jira://DEMO-1",
      "status": "CONFIRMED",
      "claims": [{"claim": "current behavior", "confidence": "HIGH"}],
      "evidenceRefs": ["jira://DEMO-1"]
    }
  ]
}
```

The runner owns timeout, exponential backoff, retries and the attempt ledger. An adapter may return `retryable=true` for a provider-specific transient failure.

Provider examples:

```text
providers/project_management_space_adapter.py
providers/dialogos_mcp_adapter.py
providers/dialogos-mcp/README.md
```

## DialogOS conversation-platform MCP

`dialogos-mcp` is mounted as a read-only external dependency for conversation-platform code and dialogue-chain evidence. It is not an Agent and cannot author PRD, Overview, Prototype or technical decisions.

Routing:

```text
MCP_MAINLINE -> dialogos_get_overview -> module map / role / dependencies
MCP_CODE     -> dialogos_find_code    -> dialogos_read_code
RUNTIME      -> dialogos_diagnose     -> only with namespace + trace/symptom
```

The executable Research Adapter is:

```text
providers/dialogos_mcp_adapter.py
```

Its provider contract, tool boundaries and evidence rules are in `providers/dialogos-mcp/README.md`. Credentials remain in the host global Codex configuration and must never enter a repository, artifact or transcript.
