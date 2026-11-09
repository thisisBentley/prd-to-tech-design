#!/usr/bin/env python3
"""Test-only Codex CLI boundary fake."""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if "--output-last-message" not in args:
    raise SystemExit("fake codex requires output-last-message")
out = Path(args[args.index("--output-last-message") + 1])
out.parent.mkdir(parents=True, exist_ok=True)
payload = os.environ.get("AI_NATIVE_FAKE_CODEX_RESULT")
if not payload:
    payload = json.dumps({"schemaVersion": 1, "status": "SUCCEEDED", "outputs": [{"path": "PRD_DELIVERY.md"}]})
out.write_text(payload, encoding="utf-8")
# Persist argv boundary for tests.
audit = os.environ.get("AI_NATIVE_FAKE_CODEX_ARGV")
if audit:
    Path(audit).write_text(json.dumps(args, ensure_ascii=False), encoding="utf-8")
