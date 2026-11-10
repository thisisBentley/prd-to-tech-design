#!/usr/bin/env python3
"""Execute bounded read-only Research queries through configured adapters."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_json_schemas import load as load_json, validate as validate_schema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = ROOT / "schemas" if (ROOT / "schemas").exists() else ROOT / "references"


def schema(name: str) -> dict[str, Any]:
    return load_json(SCHEMA_ROOT / name)


def retryable_result(returncode: int, payload: Any, error: str | None) -> bool:
    if returncode != 0 or error:
        return True
    if isinstance(payload, dict) and payload.get("retryable") is True:
        return True
    return False


def invoke_adapter(adapter: dict[str, Any], request_payload: dict[str, Any], timeout: float, retries: int, backoff: float) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    attempts: list[dict[str, Any]] = []
    last_error: str | None = None
    for attempt in range(1, retries + 2):
        started = time.monotonic()
        try:
            process = subprocess.run(
                adapter["command"],
                cwd=adapter.get("cwd") or None,
                input=json.dumps(request_payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            latency = round((time.monotonic() - started) * 1000, 2)
            payload = None
            error = None
            try:
                payload = json.loads(process.stdout) if process.stdout.strip() else None
            except json.JSONDecodeError as exc:
                error = f"invalid adapter JSON: {exc}"
            if process.returncode != 0:
                error = error or f"adapter exit {process.returncode}: {process.stderr[-1000:]}"
            if payload is not None and error is None:
                if isinstance(payload, list):
                    payload = {"status": "OK", "records": payload}
                if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
                    error = "adapter result requires records[]"
            retryable = retryable_result(process.returncode, payload, error)
            attempts.append({
                "attempt": attempt,
                "status": "SUCCESS" if error is None else ("RETRYABLE_ERROR" if retryable and attempt <= retries else "ERROR"),
                "latencyMs": latency,
                **({"error": error} if error else {}),
            })
            if error is None:
                return payload, attempts, None
            last_error = error
            if not retryable or attempt > retries:
                return None, attempts, error
        except subprocess.TimeoutExpired:
            latency = round((time.monotonic() - started) * 1000, 2)
            last_error = f"adapter timeout after {timeout}s"
            attempts.append({"attempt": attempt, "status": "RETRYABLE_ERROR" if attempt <= retries else "ERROR", "latencyMs": latency, "error": last_error})
            if attempt > retries:
                return None, attempts, last_error
        except Exception as exc:
            latency = round((time.monotonic() - started) * 1000, 2)
            last_error = f"adapter invocation failed: {exc}"
            attempts.append({"attempt": attempt, "status": "ERROR", "latencyMs": latency, "error": last_error})
            return None, attempts, last_error
        time.sleep(backoff * (2 ** (attempt - 1)))
    return None, attempts, last_error


def normalize_records(payload: dict[str, Any], clue: dict[str, Any], query: dict[str, Any], attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for raw in payload.get("records", []):
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "UNVERIFIED")).upper()
        aliases = {"OK": "CONFIRMED", "SUCCESS": "CONFIRMED", "ERROR": "UNAVAILABLE", "UNAUTHORIZED": "UNAVAILABLE", "RATE_LIMITED": "UNAVAILABLE"}
        status = aliases.get(status, status)
        if status not in {"CONFIRMED", "CURRENT_MAINLINE", "HISTORICAL_ONLY", "UNVERIFIED", "CONFLICTING", "UNAVAILABLE", "NOT_APPLICABLE"}:
            status = "UNVERIFIED"
        claims = raw.get("claims") or []
        if isinstance(claims, dict):
            claims = [claims]
        evidence_refs = raw.get("evidenceRefs") or []
        if isinstance(evidence_refs, str):
            evidence_refs = [evidence_refs]
        records.append({
            "clueId": clue["clueId"],
            "source": query["source"],
            "queryId": query["queryId"],
            "query": query["query"],
            "status": status,
            "sourceRef": str(raw.get("sourceRef", "")),
            "claims": claims if isinstance(claims, list) else [],
            "evidenceRefs": [str(item) for item in evidence_refs if item],
            "attempts": attempts,
            "latencyMs": round(sum(item.get("latencyMs", 0) for item in attempts), 2),
            "limitations": str(raw.get("limitations", "")),
            **({"error": str(raw.get("error"))} if raw.get("error") else {}),
            **({"cacheHit": bool(raw.get("cacheHit"))} if raw.get("cacheHit") is not None else {}),
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--adapters", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    request_path = args.request.resolve()
    request = load_json(request_path)
    adapters_config = load_json(args.adapters.resolve())
    request_errors = validate_schema(request, schema("research-request.schema.json"), schema("research-request.schema.json"))
    adapter_errors = validate_schema(adapters_config, schema("research-adapter-config.schema.json"), schema("research-adapter-config.schema.json"))
    if request_errors or adapter_errors:
        result = {
            "schemaVersion": 1,
            "workflowId": request.get("workflowId", "UNKNOWN"),
            "status": "BLOCKED",
            "requestSha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "records": [],
            "metrics": {"queries": 0, "available": 0, "errors": len(request_errors) + len(adapter_errors), "retries": 0},
            "generatedAt": datetime.now(timezone.utc).isoformat(),
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "errors": request_errors + adapter_errors, "out": str(args.out)}, ensure_ascii=False))
        return 1
    budget = request["budget"]
    queries = [(clue, query) for clue in request["clues"] for query in clue["queries"]]
    if len(queries) > int(budget["maxQueries"]):
        print(json.dumps({"status": "BLOCKED", "error": f"query budget exceeded: {len(queries)} > {budget['maxQueries']}"}, ensure_ascii=False))
        return 1
    adapters = {item["source"]: item for item in adapters_config["adapters"]}
    records: list[dict[str, Any]] = []
    retry_count = 0
    for clue, query in queries:
        adapter = adapters.get(query["source"])
        if adapter is None:
            records.append({
                "clueId": clue["clueId"], "source": query["source"], "queryId": query["queryId"], "query": query["query"],
                "status": "UNAVAILABLE", "claims": [], "evidenceRefs": [], "attempts": [],
                "error": "NOT_CONFIGURED", "limitations": "No adapter configured for this source.",
            })
            continue
        payload = {
            "schemaVersion": 1,
            "workflowId": request["workflowId"],
            "query": query,
        }
        adapter_result, attempts, error = invoke_adapter(adapter, payload, float(budget["timeoutSeconds"]), int(budget["retries"]), float(budget.get("backoffSeconds", 0)))
        retry_count += sum(1 for item in attempts if item.get("status") in {"RETRYABLE_ERROR", "ERROR"})
        if adapter_result is None:
            records.append({
                "clueId": clue["clueId"], "source": query["source"], "queryId": query["queryId"], "query": query["query"],
                "status": "UNAVAILABLE", "claims": [], "evidenceRefs": [], "attempts": attempts,
                "error": error or "adapter unavailable", "latencyMs": round(sum(item.get("latencyMs", 0) for item in attempts), 2),
            })
            continue
        normalized = normalize_records(adapter_result, clue, query, attempts)
        if not normalized:
            records.append({
                "clueId": clue["clueId"], "source": query["source"], "queryId": query["queryId"], "query": query["query"],
                "status": "UNVERIFIED", "claims": [], "evidenceRefs": [], "attempts": attempts,
                "error": "adapter returned no records", "limitations": "No evidence record was produced.",
            })
        else:
            records.extend(normalized)
    available = sum(1 for record in records if record["status"] not in {"UNAVAILABLE"})
    errors = sum(1 for record in records if record["status"] == "UNAVAILABLE")
    if errors == 0:
        status = "COMPLETE"
    elif available == 0:
        status = "BLOCKED"
    else:
        status = "PARTIAL"
    result = {
        "schemaVersion": 1,
        "workflowId": request["workflowId"],
        "status": status,
        "requestSha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
        "records": records,
        "metrics": {"queries": len(queries), "available": available, "errors": errors, "retries": retry_count},
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    result_schema = schema("research-query-result.schema.json")
    result_errors = validate_schema(result, result_schema, result_schema)
    if result_errors:
        result["status"] = "BLOCKED"
        result["records"].append({
            "clueId": "CONTRACT", "source": "INTERNAL", "queryId": "SCHEMA", "query": "result-contract",
            "status": "UNAVAILABLE", "claims": [], "evidenceRefs": [], "attempts": [],
            "error": "invalid research query result: " + "; ".join(result_errors[:5]),
        })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "records": len(records), "available": available, "errors": errors, "retries": retry_count, "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
