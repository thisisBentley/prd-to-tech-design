# DialogOS MCP Provider

`dialogos-mcp` is a read-only external dependency of the local Research Harness. It is an Adapter, not an Agent role, and it does not own PRD or Delivery facts.

## Registration

Global Codex registration lives only in `~/.codex/config.toml`:

```toml
[mcp_servers.dialogos-mcp]
url = "<dialogos-mcp-url>"
http_headers = { <auth-header> = "<host-provided-token>" }
```

Never commit the token, a transcript containing it, or a generated `.env` file.

## Tools

| Tool | Use | Evidence |
|---|---|---|
| `dialogos_get_overview` | Module map, module role/dependencies, static Talk chain | module refs and dependency refs |
| `dialogos_find_code` | Locate symbols, config keys, errors, routes | `module/path:line` and `read_hint` |
| `dialogos_read_code` | Read only the necessary source windows | line-numbered excerpts |
| `dialogos_diagnose` | Trace or namespace diagnosis | diagnosis result plus limitations |

Use `get_overview` for the module list, `find_code` for “where/how is X implemented”, `read_code` for cited windows, and `diagnose` only with a concrete namespace and trace/symptom.

## Research Harness mapping

```text
MCP_CODE     -> dialogos_find_code -> dialogos_read_code
MCP_MAINLINE -> dialogos_get_overview
RUNTIME      -> dialogos_diagnose (only with real trace/namespace evidence)
```

Executable adapter:

```bash
python3 adapters/research/providers/dialogos_mcp_adapter.py --mode find_code < request.json
```

Example adapter configuration:

```text
config.example.json
```

## Evidence rules

- Record `sourceRef`, `module/path:line`, query and limitations in the Research Record.
- Static code can prove current implementation; it cannot prove product intent.
- `unknown` or `insufficient_evidence` from diagnosis is not a confirmed fault.
- Results remain in scope only for the conversation platform.
