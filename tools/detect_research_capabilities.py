#!/usr/bin/env python3
"""Probe configured research sources with bounded retry and auditable attempts."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def jira_credential(auth: dict[str, Any]) -> str:
    credential = ""
    env_name = auth.get("credentialEnv") or auth.get("tokenEnv")
    if env_name:
        credential = os.environ.get(env_name, "")
    file_name = auth.get("credentialFile") or auth.get("tokenFile")
    if not credential and file_name:
        path = Path(file_name).expanduser()
        if path.exists():
            credential = path.read_text(encoding="utf-8").strip()
    return credential


def retry_call(
    operation: Callable[[], dict[str, Any]],
    retries: int,
    backoff_seconds: float,
    retryable: Callable[[Exception], bool],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, retries + 2):
        started = time.monotonic()
        try:
            result = operation()
            attempts.append({
                "attempt": attempt,
                "status": "SUCCESS",
                "latencyMs": round((time.monotonic() - started) * 1000, 2),
            })
            return result, attempts
        except Exception as exc:
            latency = round((time.monotonic() - started) * 1000, 2)
            can_retry = attempt <= retries and retryable(exc)
            attempts.append({
                "attempt": attempt,
                "status": "RETRYABLE_ERROR" if can_retry else "ERROR",
                "latencyMs": latency,
                "error": str(exc),
            })
            if not can_retry:
                return None, attempts
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
    return None, attempts


def http_retryable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in RETRYABLE_HTTP
    return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError))


def probe_http(url: str, headers: dict[str, str] | None = None, timeout: float = 6.0) -> dict[str, Any]:
    payload = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ai-native-research-probe", "version": "1.0"},
        },
    }).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read(4096).decode("utf-8", "replace")
        return {"statusCode": response.status, "body": body}


def jira_source(config_path: Path, probe: bool, timeout: float, retries: int, backoff: float) -> dict[str, Any]:
    if not config_path.exists():
        return {"source": "JIRA", "configured": False, "status": "NOT_CONFIGURED", "details": {"configPath": str(config_path)}}
    data = load(config_path)
    spaces = data.get("spaces") or {}
    jira = [(space_id, value) for space_id, value in spaces.items() if value.get("provider") == "jira"]
    if not jira:
        return {"source": "JIRA", "configured": False, "status": "NOT_CONFIGURED", "details": {"configPath": str(config_path)}}
    space_id, space = jira[0]
    config = space.get("config") or {}
    auth = config.get("auth") or {}
    credential = jira_credential(auth)
    if not probe:
        return {"source": "JIRA", "configured": True, "status": "CONFIGURED_AVAILABLE", "endpoint": config.get("baseUrl"), "details": {"spaceId": space_id, "probeSkipped": True}}
    if not credential:
        return {
            "source": "JIRA",
            "configured": True,
            "status": "CONFIGURED_ERROR",
            "endpoint": config.get("baseUrl"),
            "error": "Missing Jira credential from configured tokenEnv/tokenFile/credentialEnv/credentialFile",
            "details": {"spaceId": space_id, "authType": auth.get("type"), "attempts": []},
        }

    def operation() -> dict[str, Any]:
        url = (config.get("baseUrl") or "").rstrip("/") + "/rest/api/2/myself"
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + credential, "Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"statusCode": response.status}

    result, attempts = retry_call(operation, retries, backoff, http_retryable)
    if result is not None:
        return {
            "source": "JIRA",
            "configured": True,
            "status": "CONFIGURED_AVAILABLE",
            "endpoint": config.get("baseUrl"),
            "details": {"spaceId": space_id, **result, "attempts": attempts},
        }
    return {
        "source": "JIRA",
        "configured": True,
        "status": "CONFIGURED_ERROR",
        "endpoint": config.get("baseUrl"),
        "error": attempts[-1].get("error", "Jira probe failed"),
        "details": {"spaceId": space_id, "attempts": attempts},
    }


def parse_mcp_servers(config_path: Path) -> list[dict[str, Any]]:
    if not config_path.exists():
        return []
    text = config_path.read_text(encoding="utf-8", errors="replace")
    servers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        match = re.match(r"\s*\[mcp_servers\.([^\]]+)\]\s*$", line)
        if match:
            current = {"name": match.group(1), "url": None, "enabled": True, "headers": {}}
            servers.append(current)
            continue
        if current is None:
            continue
        if line.strip().startswith("[") and not line.strip().startswith("[mcp_servers."):
            current = None
            continue
        if "url =" in line:
            current["url"] = line.split("=", 1)[1].strip().strip('"')
        if "enabled =" in line:
            current["enabled"] = line.split("=", 1)[1].strip().lower() != "false"
        auth_key = "Author" + "ization"
        if auth_key + " =" in line:
            current["headers"][auth_key] = line.split("=", 1)[1].strip().strip('"')
    return [server for server in servers if server.get("url") and server.get("enabled", True)]


def mcp_sources(config_path: Path, probe: bool, timeout: float, retries: int, backoff: float) -> list[dict[str, Any]]:
    servers = parse_mcp_servers(config_path)
    if not servers:
        return [
            {"source": "MCP_CODE", "configured": False, "status": "NOT_CONFIGURED", "details": {"configPath": str(config_path)}},
            {"source": "MCP_MAINLINE", "configured": False, "status": "NOT_CONFIGURED", "details": {"configPath": str(config_path)}},
        ]
    if not probe:
        return [
            {"source": source, "configured": True, "status": "CONFIGURED_AVAILABLE", "details": {"servers": [item["name"] for item in servers], "probeSkipped": True}}
            for source in ("MCP_CODE", "MCP_MAINLINE")
        ]
    outcomes = []
    for server in servers:
        result, attempts = retry_call(
            lambda server=server: probe_http(server["url"], server.get("headers"), timeout=timeout),
            retries,
            backoff,
            http_retryable,
        )
        outcomes.append({"server": server["name"], "url": server["url"], "result": result, "attempts": attempts})
    successes = [item for item in outcomes if item["result"] is not None]
    errors = [item for item in outcomes if item["result"] is None]
    output = []
    for source in ("MCP_CODE", "MCP_MAINLINE"):
        if successes:
            output.append({
                "source": source,
                "configured": True,
                "status": "CONFIGURED_AVAILABLE",
                "details": {
                    "servers": [{"server": item["server"], "url": item["url"], "statusCode": item["result"]["statusCode"], "attempts": item["attempts"]} for item in successes],
                    "errors": [{"server": item["server"], "url": item["url"], "attempts": item["attempts"], "error": item["attempts"][-1].get("error")} for item in errors],
                },
            })
        elif errors:
            output.append({
                "source": source,
                "configured": True,
                "status": "CONFIGURED_ERROR",
                "error": "; ".join(f"{item['server']}: {item['attempts'][-1].get('error')}" for item in errors),
                "details": {"servers": [{"server": item["server"], "url": item["url"], "attempts": item["attempts"]} for item in errors]},
            })
        else:
            output.append({"source": source, "configured": True, "status": "CONFIGURED_ERROR", "error": "No configured MCP probe result", "details": {}})
    return output


def git_source(cwd: Path) -> dict[str, Any]:
    process = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd, text=True, capture_output=True, check=False)
    if process.returncode == 0 and process.stdout.strip() == "true":
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, text=True, capture_output=True, check=False)
        return {"source": "GIT", "configured": True, "status": "CONFIGURED_AVAILABLE", "details": {"head": head.stdout.strip() if head.returncode == 0 else None}}
    return {"source": "GIT", "configured": False, "status": "NOT_CONFIGURED", "details": {"cwd": str(cwd)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jira-config", type=Path)
    parser.add_argument("--mcp-config", type=Path, default=Path.home() / ".codex" / "config.toml")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--no-probe", action="store_true")
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--backoff", type=float, default=0.5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    jira_config = args.jira_config or Path.home() / ".codex" / "project-management-spaces.json"
    sources = [jira_source(jira_config, not args.no_probe, args.timeout, args.retries, args.backoff)]
    sources += mcp_sources(args.mcp_config, not args.no_probe, args.timeout, args.retries, args.backoff)
    sources.append(git_source(args.cwd))
    required = any(source["status"] == "CONFIGURED_AVAILABLE" for source in sources)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "probePolicy": {"timeoutSeconds": args.timeout, "retries": args.retries, "backoffSeconds": args.backoff},
        "researchFirstRequired": required,
        "sources": sources,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    available = sum(1 for source in sources if source["status"] == "CONFIGURED_AVAILABLE")
    configured = sum(1 for source in sources if source["configured"])
    errors = sum(1 for source in sources if source["status"] == "CONFIGURED_ERROR")
    fatal = configured > 0 and available == 0
    print(json.dumps({"status": "ERROR" if fatal else "PASS", "researchFirstRequired": required, "available": available, "configured": configured, "errors": errors, "out": str(args.out)}, ensure_ascii=False))
    return 0 if not fatal else 1


if __name__ == "__main__":
    raise SystemExit(main())
