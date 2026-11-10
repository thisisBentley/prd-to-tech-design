#!/usr/bin/env python3
"""Generate a source-bound four-part Jira description projection from PRD."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")


def extract_section(text: str, names: list[str]) -> str:
    lines = text.splitlines()
    collecting = False
    result = []
    for line in lines:
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            collecting = any(name.lower() in title for name in names)
            continue
        if collecting and line.strip():
            result.append(line.strip())
    return "\n".join(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--requirement-key", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    text = args.prd.read_text(encoding="utf-8")
    digest = hashlib.sha256(args.prd.read_bytes()).hexdigest()
    background = extract_section(text, ["background", "背景"])
    current = extract_section(text, ["current", "现状"])
    goal = extract_section(text, ["goal", "目标", "requirement summary"])
    frs = [line.strip() for line in text.splitlines() if FR_RE.search(line)]
    acs = [line.strip() for line in text.splitlines() if AC_RE.search(line)]
    if not background:
        background = "见 PRD 需求背景与方案摘要。"
    if not current:
        current = "见 PRD 当前状态、影响范围与已有能力说明。"
    if not goal:
        goal = "按 PRD 功能需求与验收标准完成本期范围。"
    body = f"""<!-- source-prd: {args.prd.name} -->
<!-- source-prd-sha256: {digest} -->
<!-- projection-version: 1 -->

## 1. 背景

{background}

## 2. 现状

{current}

## 3. 目标

{goal}

## 4. 功能点

{chr(10).join('- ' + line.removeprefix('- ').strip() for line in frs) if frs else '- 见 PRD 功能需求。'}

### 验收摘要

{chr(10).join('- ' + line.removeprefix('- ').strip() for line in acs) if acs else '- 见 PRD 验收标准。'}

---
需求编号：{args.requirement_key}  
PRD 为唯一业务事实源；本描述仅为派生投影。
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": str(args.out), "prdSha256": digest, "functionalPoints": len(frs), "checkedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
