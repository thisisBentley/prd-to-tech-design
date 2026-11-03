#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
from pathlib import Path

PATTERNS = {
    "private_ipv4": re.compile(r"\b(?:10|127|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "public_ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "company_marker": re.compile(r"(?i)(wezhuiyi|zhuiyi|jira\.in\.|code\.in\.|opssvn)"),
    "credential_assignment": re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[:=]"),
    "authorization_header": re.compile(r"(?i)\bauthorization\s*[:=]"),
    "bearer_literal": re.compile(r"(?i)\bbearer\s+[a-z0-9._-]{8,}"),
}

ALLOWED = {
    "schemas/state.schema.json": {"public_ipv4"},
    "schemas/bundle.schema.json": {"public_ipv4"},
    "schemas/gate-result.schema.json": {"public_ipv4"},
    "schemas/context-snapshot.schema.json": {"public_ipv4"},
    "schemas/capability-ideation.schema.json": {"public_ipv4"},
    "schemas/capability-matrix.schema.json": {"public_ipv4"},
    "schemas/manifest.schema.json": {"public_ipv4"},
    "schemas/finding.schema.json": {"public_ipv4"},
    "tools/sanitize_scan.py": {"company_marker", "credential_assignment", "authorization_header"},
    ".gitignore": {"credential_assignment"},
}

def scan(root: Path) -> int:
    findings = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git/" in path.as_posix() or path.name == "sanitize_report.txt":
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        allowed = ALLOWED.get(rel, set())
        for name, pattern in PATTERNS.items():
            if name in allowed:
                continue
            for match in pattern.finditer(text):
                findings += 1
                print(f"{rel}\t{name}\t{match.group(0)[:160]}")
    return findings

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    count = scan(Path(args.root).resolve())
    print(f"TOTAL_FINDINGS={count}")
    return 1 if count else 0

if __name__ == "__main__":
    raise SystemExit(main())
