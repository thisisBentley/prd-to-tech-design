#!/usr/bin/env python3
"""Read-only DialogOS MCP research adapter.

Input: one research query envelope on stdin.
Output: normalized research records on stdout.

The adapter never writes to DialogOS and never prints configured credentials.
Direct Codex agents should prefer the native dialogos_* MCP tools; this adapter
exists so the local Research Harness can execute the same source deterministically.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AUTH_HEADER = "Author" + "ization"
MODULES = {
    "api-invoker", "bot-agent", "bot-kb", "bot-task", "data-manager",
    "dialog-manager", "doc-recognizer", "extractor", "intent-recognizer",
    "model-inference", "pattern-index", "sensitivity-recognizer", "vector-index",
}
TOOLS = {
    "find_code": "dialogos_find_code",
    "overview": "dialogos_get_overview",
    "read_code": "dialogos_read_code",
    "diagnose": "dialogos_diagnose",
}


def load_request() -> dict[str, Any]:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or not isinstance(data.get("query"), dict):
        raise ValueError("request requires query object")
    return data


def parse_server(config_path: Path, name: str) -> dict[str, Any]:
    if not config_path.exists():
        raise RuntimeError(f"MCP config not found: {config_path}")
    text = config_path.read_text(encoding="utf-8", errors="replace")
    current: dict[str, Any] | None = None
    section = "other"
    result: dict[str, Any] | None = None
    for line in text.splitlines():
        main_match = re.match(r"\s*\[mcp_servers\.([^.\]]+)\]\s*$", line)
        if main_match:
            current = {"name": main_match.group(1), "url": None, "headers": {}}
            section = "main"
            if current["name"] == name:
                result = current
            continue
        nested_match = re.match(r"\s*\[mcp_servers\.([^.\]]+)\.([^\]]+)\]\s*$", line)
        if nested_match:
            server_name, nested = nested_match.groups()
            current = result if result and result.get("name") == server_name else None
            section = "headers" if nested == "http_headers" else "other"
            continue
        if line.strip().startswith("["):
            current = None
            section = "other"
            continue
        if current is None or section == "other":
            continue
        stripped = line.strip()
        if section == "main" and stripped.startswith("url") and "=" in stripped:
            current["url"] = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        match = re.search(r"\bAuthorization\s*=\s*[\"']([^\"']+)[\"']", stripped)
        if match:
            current["headers"][AUTH_HEADER] = match.group(1)
    if result is None or not result.get("url"):
        raise RuntimeError(f"MCP server not found or missing URL: {name}")
    return result


def decode_rpc(body: str) -> dict[str, Any]:
    stripped = body.lstrip()
    if stripped.startswith("event:") or stripped.startswith("data:"):
        body = "\n".join(line[5:].strip() for line in body.splitlines() if line.startswith("data:"))
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError("MCP returned a non-object JSON-RPC response")
    if payload.get("error"):
        error = payload["error"]
        message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
        raise RuntimeError(f"MCP JSON-RPC error: {message}")
    return payload


def call_tool(url: str, auth_value: str, tool: str, arguments: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            AUTH_HEADER: auth_value,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = decode_rpc(response.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise RuntimeError("DialogOS MCP unauthorized; check http_headers.Authorization") from exc
        raise RuntimeError(f"DialogOS MCP HTTP {exc.code}") from exc
    result = payload.get("result") or {}
    if result.get("isError") is True:
        raise RuntimeError("DialogOS MCP tool returned isError=true")
    text = "\n".join(
        str(item.get("text", "")) for item in result.get("content", []) if isinstance(item, dict)
    ).strip()
    try:
        parsed = json.loads(text) if text else {}
    except json.JSONDecodeError:
        parsed = {"text": text}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def arguments_for(mode: str, query: dict[str, Any]) -> dict[str, Any]:
    text = str(query.get("query", "")).strip()
    module = query.get("module")
    if mode == "find_code":
        args: dict[str, Any] = {"query": text}
        if module in MODULES:
            args["module"] = module
        if query.get("case_sensitive") is True:
            args["case_sensitive"] = True
        return args
    if mode == "overview":
        return {"module": text} if text in MODULES else {}
    if mode == "read_code":
        if module not in MODULES:
            raise ValueError("read_code requires query.module")
        args = {"module": module}
        for key in ("path", "paths", "ranges", "start_line", "end_line"):
            if key in query:
                args[key] = query[key]
        if not any(key in args for key in ("path", "paths", "ranges")):
            raise ValueError("read_code requires query.path, query.paths or query.ranges")
        return args
    if mode == "diagnose":
        required = ("namespace", "scope")
        missing = [key for key in required if not query.get(key)]
        if missing:
            raise ValueError("diagnose requires query." + " and query.".join(missing))
        args = {"namespace": query["namespace"], "scope": query["scope"]}
        if query["scope"] == "trace":
            for key in ("trace_id", "symptom"):
                if not query.get(key):
                    raise ValueError(f"diagnose scope=trace requires query.{key}")
                args[key] = query[key]
        return args
    raise ValueError(f"unsupported mode: {mode}")


def normalize(mode: str, query: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(query.get("query", "")).strip()
    if mode == "overview":
        modules = payload.get("modules") or []
        claims = [
            {
                "claim": f"{item.get('name')}: {item.get('role', '')} — {item.get('summary', '')}",
                "confidence": "HIGH",
                "field": "module",
            }
            for item in modules if isinstance(item, dict)
        ][:20]
        refs = [f"dialogos-mcp://module/{item.get('name')}" for item in modules if isinstance(item, dict)][:20]
        return [{
            "sourceRef": "dialogos-mcp://overview",
            "status": "CONFIRMED" if claims else "UNVERIFIED",
            "claims": claims,
            "evidenceRefs": refs,
            "limitations": "Static module map only; capabilities are file names, not behavioural proof.",
        }]
    if mode == "find_code":
        matches = payload.get("matches") or []
        files = payload.get("files") or []
        claims = []
        refs = []
        for item in matches[:20]:
            if not isinstance(item, dict):
                continue
            ref = f"dialogos-mcp://code/{item.get('module')}/{item.get('path')}:{item.get('line')}"
            refs.append(ref)
            claims.append({
                "claim": f"{item.get('module')}/{item.get('path')}:{item.get('line')}: {item.get('text', '')}",
                "confidence": "HIGH",
                "field": "code-match",
            })
        if not claims:
            for item in files[:10]:
                if not isinstance(item, dict):
                    continue
                ref = f"dialogos-mcp://code/{item.get('module')}/{item.get('path')}"
                refs.append(ref)
                claims.append({
                    "claim": f"{item.get('module')}/{item.get('path')} matched {item.get('match_count', 0)} times",
                    "confidence": "MEDIUM",
                    "field": "code-file",
                })
        effective = payload.get("effective_query") or text
        return [{
            "sourceRef": f"dialogos-mcp://code/search?q={urllib.parse.quote(str(effective))}",
            "status": "CONFIRMED" if claims else "UNVERIFIED",
            "claims": claims,
            "evidenceRefs": refs,
            "limitations": "Static source search only; read the cited windows before asserting exact behaviour.",
        }]
    if mode == "read_code":
        files = payload.get("files") or payload.get("content") or []
        claims = []
        refs = []
        if isinstance(files, list):
            for item in files[:5]:
                if not isinstance(item, dict):
                    continue
                path = item.get("path", "")
                module = item.get("module") or query.get("module")
                lines = item.get("content") or item.get("lines") or []
                if isinstance(lines, list):
                    excerpt = "\n".join(str(line.get("text", line)) for line in lines[:40])
                else:
                    excerpt = str(lines)[:4000]
                ref = f"dialogos-mcp://code/{module}/{path}"
                refs.append(ref)
                claims.append({"claim": excerpt, "confidence": "HIGH", "field": "code-read"})
        return [{
            "sourceRef": f"dialogos-mcp://code/read/{query.get('module', '')}",
            "status": "CONFIRMED" if claims else "UNVERIFIED",
            "claims": claims,
            "evidenceRefs": refs,
            "limitations": "Read-only source excerpt; response may be size-capped.",
        }]
    result_name = str(payload.get("status") or payload.get("result") or "UNVERIFIED").upper()
    status = "CONFIRMED" if result_name in {"OK", "CONFIRMED", "FAULT_IDENTIFIED"} else "UNVERIFIED"
    return [{
        "sourceRef": f"dialogos-mcp://diagnose/{query.get('namespace', '')}",
        "status": status,
        "claims": [{"claim": json.dumps(payload, ensure_ascii=False)[:6000], "confidence": "MEDIUM", "field": "diagnosis"}],
        "evidenceRefs": [f"dialogos-mcp://diagnose/{query.get('namespace', '')}"],
        "limitations": "Diagnosis can return unknown/insufficient_evidence; that is not a confirmed fault.",
    }]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=sorted(TOOLS), default="find_code")
    parser.add_argument("--server", default="dialogos-mcp")
    parser.add_argument("--mcp-config", default=os.environ.get("CODEX_MCP_CONFIG", "~/.codex/config.toml"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()
    try:
        request = load_request()
        query = request["query"]
        server = parse_server(Path(args.mcp_config).expanduser(), args.server)
        auth_value = os.environ.get("DIALOGOS_MCP_AUTHORIZATION") or server["headers"].get(AUTH_HEADER, "")
        if not auth_value:
            raise RuntimeError("DialogOS MCP auth header is missing")
        tool_arguments = arguments_for(args.mode, query)
        payload = call_tool(server["url"], auth_value, TOOLS[args.mode], tool_arguments, args.timeout)
        records = normalize(args.mode, query, payload)
        print(json.dumps({"status": "OK", "records": records, "retryable": False}, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "records": [], "retryable": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
