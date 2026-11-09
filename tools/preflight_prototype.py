#!/usr/bin/env python3
"""Run portable static Prototype Contract Preflight against frozen files."""
from __future__ import annotations
import argparse, json, re
from html import unescape
from pathlib import Path
from typing import Any

VISIBLE_PHRASES = ["查看日志", "重试", "暂无有效样本", "无权限", "数据不完整"]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def version(text: str) -> str | None:
    patterns = [r"current_prd_version\s*:\s*(v[0-9.]+)", r"prdVersion\s*:\s*(v[0-9.]+)", r"当前(?: PRD)? 版本[^v\n]*(v[0-9.]+)", r"PRD[^v\n]{0,80}(v[0-9.]+)"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match: return match.group(1)
    return None


def proto_source_version(text: str) -> str | None:
    patterns = [r"source-prd-version[\"']?\s+content=[\"']([^\"']+)", r"prototype-traceability[\"']?\s+content=[\"']([^\"']+)", r"PRD[^v\n]{0,80}(v[0-9.]+)"]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = match.group(1)
            v = re.search(r"v[0-9.]+", value, re.IGNORECASE)
            if v: return v.group(0)
    return None


def visible_text(html: str) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", html))).strip()


def check(check_id: str, status: str, observed: str, expected: str, evidence: list[str]) -> dict[str, Any]:
    return {"checkId": check_id, "status": status, "observed": observed, "expected": expected, "evidenceRefs": evidence}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--runtime-result", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    prd = read(args.prd)
    checks: list[dict[str, Any]] = []
    if not args.prototype:
        checks.append(check("PROTOTYPE.STATUS", "not_applicable", "prototype not supplied", "Prototype is not triggered", [str(args.prd)]))
        result = {"schemaVersion": 1, "status": "NOT_APPLICABLE", "prototypeStatus": "NOT_TRIGGERED", "checks": checks, "consoleErrors": 0}
    else:
        proto = read(args.prototype)
        prd_v = version(prd)
        proto_v = proto_source_version(proto)
        checks.append(check("PROVENANCE.PRD_VERSION", "passed" if prd_v and proto_v == prd_v else "failed", str(proto_v), str(prd_v), [str(args.prd), str(args.prototype)]))
        text = visible_text(proto)
        for phrase in VISIBLE_PHRASES:
            # Only treat a phrase as a visible-label requirement when PRD text
            # presents it as UI copy/entry, not when it merely mentions the
            # concept in a rule or evidence paragraph.
            matches = list(re.finditer(re.escape(phrase), prd))
            is_visible_requirement = any(re.search(r"(?:显示|展示|文案|入口|按钮|提示|可见|可点)", prd[max(0, m.start()-55):m.end()+55]) for m in matches)
            if not is_visible_requirement: continue
            present = phrase in text
            checks.append(check(f"VISIBLE.{phrase}", "passed" if present else "failed", "present" if present else "missing", f"visible label: {phrase}", [str(args.prd), str(args.prototype)]))
        # Static evidence for a navigable logs target when the PRD asks for log drilldown.
        if "查看日志" in prd or "客服日志" in prd:
            has_target = bool(re.search(r"drillDownToLogs|sessionLog|客服日志|logs", proto, re.IGNORECASE))
            checks.append(check("VISIBLE.LOG_TARGET", "passed" if has_target else "failed", "target found" if has_target else "target missing", "Prototype has a log target", [str(args.prototype)]))
        if args.overview:
            overview = read(args.overview)
            if prd_v:
                checks.append(check("PROVENANCE.OVERVIEW_VERSION", "passed" if prd_v in overview else "failed", "version referenced" if prd_v in overview else "version missing", f"Overview references {prd_v}", [str(args.prd), str(args.overview)]))
        if args.runtime_result:
            runtime = json.loads(read(args.runtime_result))
            diagnostics = runtime.get("consoleDiagnostics") or runtime.get("consoleErrors") or []
            status = "passed" if runtime.get("status") == "PASS" and not diagnostics and not runtime.get("pageErrors") and not runtime.get("requestFailures") else "failed"
            checks.append(check("RUNTIME.CLEAN", status, "clean" if status == "passed" else "runtime errors present", "zero unhandled runtime errors", [str(args.runtime_result)]))
        else:
            checks.append(check("RUNTIME.CLEAN", "not_executed", "runtime evidence not supplied", "zero unhandled runtime errors", [str(args.prototype)]))
        failed = any(c["status"] == "failed" for c in checks)
        incomplete = any(c["status"] in {"unverified", "not_executed"} for c in checks)
        result = {"schemaVersion": 1, "status": "NEEDS_FIX" if failed else ("INCOMPLETE" if incomplete else "PASS"), "prototypeStatus": "TRIGGERED", "checks": checks, "consoleErrors": 0}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "NOT_APPLICABLE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
