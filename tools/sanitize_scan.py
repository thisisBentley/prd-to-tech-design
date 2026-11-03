#!/usr/bin/env python3
from __future__ import annotations
import argparse
import re
from pathlib import Path

PATTERNS = {
    "ipv4_private": re.compile(r"\b(?:10|127|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "cloud_ip_like": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "url": re.compile(r"\bhttps?://[^\s`\"'<>]+", re.I),
    "credential": re.compile(r"(?i)(api[_-]?key|secret|token|password|authorization\s*[:=]|bearer\s+)"),
    "company_marker": re.compile(r"(?i)(wezhuiyi|zhuiyi|jira\.in\.|code\.in\.|opssvn)"),
}

def scan(root: Path) -> int:
    findings = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git/" in path.as_posix() or path.name == "sanitize_report.txt":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                findings += 1
                print(f"{path.relative_to(root)}\t{name}\t{match.group(0)[:160]}")
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
