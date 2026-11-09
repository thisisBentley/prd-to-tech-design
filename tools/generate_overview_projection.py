#!/usr/bin/env python3
"""Generate a deterministic offline Overview projection from a synced PRD/Prototype pair."""
from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def lines_for_ids(text: str, pattern: re.Pattern[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        for identifier in pattern.findall(line):
            result.setdefault(identifier, line.strip())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--pair", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    pair = load(args.pair)
    prd_text = args.prd.read_text(encoding="utf-8")
    manifest = load(args.manifest)
    if pair.get("pairStatus") != "SYNCED":
        print(json.dumps({"status": "BLOCKED", "reason": "Artifact Pair must be SYNCED before Overview projection."}, ensure_ascii=False))
        return 1

    fr_lines = lines_for_ids(prd_text, FR_RE)
    ac_lines = lines_for_ids(prd_text, AC_RE)
    missing = []
    bindings = []
    for element in manifest.get("elements", []):
        fr_ids = element.get("frIds", [])
        ac_ids = element.get("acIds", [])
        missing.extend(identifier for identifier in fr_ids + ac_ids if identifier not in fr_lines and identifier not in ac_lines)
        bindings.append({
            "uiElementId": element.get("uiElementId"),
            "visibleLabel": element.get("visibleLabel"),
            "frIds": fr_ids,
            "acIds": ac_ids,
            "states": element.get("states", []),
        })
    if missing:
        print(json.dumps({"status": "BLOCKED", "reason": "Manifest contains IDs not found in PRD.", "missing": sorted(set(missing))}, ensure_ascii=False))
        return 1

    esc = html.escape
    fr_rows = "\n".join(f"<tr><td>{esc(identifier)}</td><td>{esc(fr_lines[identifier])}</td></tr>" for identifier in sorted(fr_lines))
    ac_rows = "\n".join(f"<tr><td>{esc(identifier)}</td><td>{esc(ac_lines[identifier])}</td></tr>" for identifier in sorted(ac_lines))
    binding_rows = "\n".join(
        f"<tr><td>{esc(str(item['uiElementId']))}</td><td>{esc(str(item['visibleLabel']))}</td><td>{esc(', '.join(item['frIds']))}</td><td>{esc(', '.join(item['acIds']))}</td><td>{esc(', '.join(item['states']))}</td></tr>"
        for item in bindings
    )
    source_hash = __import__("hashlib").sha256(args.prd.read_bytes()).hexdigest()
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="source-prd" content="PRD_DELIVERY.md"><meta name="source-prd-sha256" content="{source_hash}"><meta name="artifact-pair-id" content="{esc(str(pair.get('pairId', '')))}"><title>Delivery Overview</title><style>body{{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#1f2937}}table{{border-collapse:collapse;width:100%;margin:12px 0 28px}}th,td{{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top}}th{{background:#f3f4f6}}code{{background:#f3f4f6;padding:2px 4px}}</style></head>
<body><h1>Delivery Overview</h1><p>Projection only: this page is generated from the synchronized PRD / Prototype Pair and does not define new business facts.</p>
<h2>Source</h2><ul><li>Pair: <code>{esc(str(pair.get('pairId', '')))}</code></li><li>Revision: <code>{esc(str(pair.get('prdRevision', '')))}</code></li><li>PRD SHA-256: <code>{source_hash}</code></li></ul>
<h2>Functional Requirements</h2><table><thead><tr><th>ID</th><th>Source line</th></tr></thead><tbody>{fr_rows}</tbody></table>
<h2>Acceptance Criteria</h2><table><thead><tr><th>ID</th><th>Source line</th></tr></thead><tbody>{ac_rows}</tbody></table>
<h2>Prototype Coverage</h2><table><thead><tr><th>UI Element</th><th>Visible label</th><th>FR</th><th>AC</th><th>States</th></tr></thead><tbody>{binding_rows}</tbody></table>
</body></html>
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(json.dumps({"status": "PASS", "out": str(args.out), "pairId": pair.get("pairId"), "revision": pair.get("prdRevision")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
