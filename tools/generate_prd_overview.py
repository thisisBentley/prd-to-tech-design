#!/usr/bin/env python3
"""Generate an offline PRD-only Overview that only projects frozen PRD content."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    text = args.prd.read_text(encoding="utf-8")
    digest = hashlib.sha256(args.prd.read_bytes()).hexdigest()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    summary = next((line for line in lines if "方案摘要" in line or "summary" in line.lower()), lines[0] if lines else "PRD")
    frs = [line for line in lines if FR_RE.search(line)]
    acs = [line for line in lines if AC_RE.search(line)]
    fr_rows = "\n".join(f"<tr><td>{esc(FR_RE.search(line).group(0))}</td><td>{esc(line)}</td></tr>" for line in frs)
    ac_rows = "\n".join(f"<tr><td>{esc(AC_RE.search(line).group(0))}</td><td>{esc(line)}</td></tr>" for line in acs)
    body = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="source-prd" content="{esc(args.prd.name)}">
<meta name="source-prd-sha256" content="{digest}">
<meta name="overview-revision" content="{esc(args.revision)}">
<title>PRD Overview</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:1120px;margin:40px auto;padding:0 24px;color:#172033}}table{{width:100%;border-collapse:collapse}}th,td{{border:1px solid #d8dee9;padding:10px;text-align:left}}th{{background:#f4f7fb}}code{{word-break:break-all}}</style>
</head><body>
<h1>PRD Overview</h1>
<h2>方案摘要</h2><p>{esc(summary)}</p>
<h2>Functional Requirements</h2><table><thead><tr><th>ID</th><th>Source line</th></tr></thead><tbody>{fr_rows}</tbody></table>
<h2>Acceptance Criteria</h2><table><thead><tr><th>ID</th><th>Source line</th></tr></thead><tbody>{ac_rows}</tbody></table>
<h2>Source</h2><p>PRD SHA-256: <code>{digest}</code></p><p>本页面只投影当前 PRD，不新增业务事实。</p>
</body></html>
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": str(args.out), "revision": args.revision, "checkedAt": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
