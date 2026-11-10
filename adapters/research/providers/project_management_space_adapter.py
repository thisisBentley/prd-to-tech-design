#!/usr/bin/env python3
"""Read-only Research Adapter backed by the project-management-space CLI."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")


def load_request() -> dict[str, Any]:
    data = json.load(sys.stdin)
    if not isinstance(data, dict) or not isinstance(data.get("query"), dict):
        raise ValueError("request requires query object")
    return data


def run_cli(args: argparse.Namespace, query: str, issue_key: str | None) -> tuple[dict[str, Any], int]:
    command = list(args.cli)
    env = os.environ.copy()
    skill_src = Path(args.skill_root).expanduser() / "src"
    if skill_src.exists():
        prior = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(skill_src) + (os.pathsep + prior if prior else "")
    if issue_key:
        command.extend(["--config", str(Path(args.config).expanduser()), "get", "--space", args.space, issue_key])
    else:
        command.extend(["--config", str(Path(args.config).expanduser()), "search", "--space", args.space, "--text", query, "--limit", str(args.limit)])
    process = subprocess.run(command, text=True, capture_output=True, timeout=args.timeout, env=env, check=False)
    if process.returncode != 0:
        raise RuntimeError(f"project-management-space exit {process.returncode}: {process.stderr[-2000:]}")
    return json.loads(process.stdout), process.returncode


def issue_record(snapshot: dict[str, Any], query: str) -> dict[str, Any]:
    key = snapshot.get("key", "")
    evidence_refs = [f"jira://{key}"]
    for attachment in snapshot.get("attachments", []) or []:
        digest = attachment.get("sha256")
        attachment_id = attachment.get("id")
        if digest:
            evidence_refs.append(f"jira://{key}/attachment/{attachment_id}?sha256={digest}")
    claims = [
        {"claim": f"Jira summary: {snapshot.get('summary', '')}", "confidence": "HIGH", "field": "summary"},
        {"claim": f"Jira status: {snapshot.get('status', '')}", "confidence": "HIGH", "field": "status"},
    ]
    return {
        "sourceRef": snapshot.get("url") or f"jira://{key}",
        "status": "CONFIRMED",
        "claims": claims,
        "evidenceRefs": evidence_refs,
        "query": query,
        "updatedAt": snapshot.get("updated_at"),
        "sourceHash": snapshot.get("sourceHash") or snapshot.get("source_hash"),
        "limitations": "Issue snapshot only; attachment contents require separate integrity and content checks.",
    }


def search_records(results: Any, query: str) -> list[dict[str, Any]]:
    items = results.get("issues", results.get("items", results)) if isinstance(results, dict) else results
    if not isinstance(items, list):
        return []
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        records.append({
            "sourceRef": item.get("url") or f"jira://{key}",
            "status": "CONFIRMED",
            "claims": [{"claim": f"Historical requirement {key}: {item.get('summary', '')}", "confidence": "MEDIUM", "field": "summary"}],
            "evidenceRefs": [f"jira://{key}"],
            "query": query,
            "limitations": "Search hit identifies related work; it does not prove implementation equivalence.",
        })
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=os.environ.get("PMS_CONFIG", "~/.codex/project-management-spaces.json"))
    parser.add_argument("--space", default=os.environ.get("PMS_SPACE", "jira"))
    parser.add_argument("--skill-root", default=os.environ.get("PMS_SKILL_ROOT", "~/.codex/skills/project-management-space"))
    parser.add_argument("--cli", nargs="+", default=[sys.executable, "-m", "project_management_space.cli"])
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    try:
        request = load_request()
        query = str(request["query"].get("query", "")).strip()
        if not query:
            raise ValueError("query.query must not be empty")
        issue_key = query if ISSUE_KEY.fullmatch(query) else None
        payload, _ = run_cli(args, query, issue_key)
        records = [issue_record(payload, query)] if issue_key else search_records(payload, query)
        print(json.dumps({"status": "OK", "records": records, "retryable": False}, ensure_ascii=False))
        return 0
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "ERROR", "records": [], "retryable": True, "error": f"adapter timeout after {args.timeout}s"}, ensure_ascii=False))
        return 2
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "records": [], "retryable": True, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
