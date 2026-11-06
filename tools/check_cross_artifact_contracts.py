#!/usr/bin/env python3
"""Static preflight for high-risk PRD/Prototype contract gaps.

This is a deterministic guardrail, not a replacement for formal G1/U1 review.
It detects the classes of gaps that ordinary section-presence checks miss.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RULES = [
    "X1.role.permission.matrix",
    "X2.action.export.contract",
    "X3.enum.dictionary",
    "X4.exception.field.render",
    "X5.event.timeout.render",
]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def finding(rule: str, refs: list[str], observed: str, expected: str) -> dict[str, Any]:
    return {
        "findingId": f"QA:{rule}:blocking",
        "ruleId": rule,
        "severity": "blocking",
        "requirementRefs": refs,
        "observed": observed,
        "expectedBasis": expected,
        "closeCondition": "Update the PRD/Prototype and rerun the cross-artifact check plus formal gates.",
    }


def role_check(prd: str) -> dict[str, Any] | None:
    low = prd.lower()
    if ("技术详情" in prd and "授权角色" in prd) or ("technical details" in low and "authorized role" in low):
        explicit = bool(re.search(r"(角色(清单|矩阵)|角色名称|运营管理员|技术管理员|实施人员|产品经理|测试人员|研发人员|运营管理员|viewer|operator|admin|role matrix|role list)", low))
        if not explicit:
            return finding(
                "X1.role.permission.matrix",
                ["PRD role/permission section"],
                "PRD says technical details are visible to authorized roles but does not name roles, visible fields, or denied behavior.",
                "Each role must have an explicit visible scope, denied result, and permission AC.",
            )
    return None


def export_check(prd: str) -> dict[str, Any] | None:
    low = prd.lower()
    if "导出" not in prd and "export" not in low:
        return None
    has_contract = any(k in low for k in ["文件格式", "csv", "xlsx", "最大记录", "记录上限", "空结果", "导出失败", "导出权限", "max record", "empty result", "export failure", "export permission", "file format"])
    has_ac = bool(re.search(r"(ac-[^\n]*(导出|export)|(导出|export)[^\n]*ac-)", low))
    if not (has_contract and has_ac):
        return finding(
            "X2.action.export.contract",
            ["PRD export action", "PRD acceptance criteria"],
            "Export is present but its field scope, format, limit, empty/failure/permission behavior, or export AC is incomplete.",
            "Define the full export contract and at least one observable export AC.",
        )
    return None


def enum_check(prd: str) -> dict[str, Any] | None:
    low = prd.lower()
    if ("逾期阶段" in prd or "overdue-stage" in low or "overdue stage" in low) and any(x in low for x in ["场景枚举", "场景字段", "scenario enum", "scenario field"]):
        explicit = bool(
            re.search(r"(逾期阶段|overdue[- ]?stage)[^\n]{0,160}(pd.{0,80}m1.{0,80}m2|枚举值|枚举清单)", low)
            or re.search(r"(pd.{0,80}m1.{0,80}m2)[^\n]{0,160}(逾期阶段|overdue)", low)
        )
        if not explicit:
            return finding(
                "X3.enum.dictionary",
                ["PRD overdue-stage filter"],
                "The overdue-stage filter refers to a scenario enum but does not list supported values or unknown-value behavior.",
                "List the complete enum, display names, and unknown/empty behavior.",
            )
    return None


def exception_check(prd: str, proto: str) -> dict[str, Any] | None:
    required = [token for token in ["detail.field", "code"] if token in prd]
    if required and any(token not in proto for token in required):
        missing = [token for token in required if token not in proto]
        return finding(
            "X4.exception.field.render",
            ["PRD exception fields", "Prototype exception section"],
            f"PRD requires exception fields but the prototype does not render: {', '.join(missing)}.",
            "Render every required exception field and define placeholders for missing values.",
        )
    return None


def timeout_check(prd: str, proto: str) -> dict[str, Any] | None:
    proto_low = proto.lower()
    represented = any(x in proto_low for x in ["[timeout]", "timeout-event", "timeout_event", "超时事件"])
    if ("[TIMEOUT]" in prd or "timeout event" in prd.lower()) and not represented:
        return finding(
            "X5.event.timeout.render",
            ["PRD conversation rendering", "Prototype conversation area"],
            "PRD requires [TIMEOUT] as a distinct timeout event but the prototype has no matching event representation.",
            "Show a distinct timeout event and provide an observable example/AC.",
        )
    return None


def check(prd: str, proto: str) -> dict[str, Any]:
    findings = [x for x in [
        role_check(prd),
        export_check(prd),
        enum_check(prd),
        exception_check(prd, proto),
        timeout_check(prd, proto),
    ] if x]
    checks = []
    found_rules = {f["ruleId"] for f in findings}
    for rule in RULES:
        checks.append({
            "checkId": rule,
            "status": "failed" if rule in found_rules else "passed",
            "evidenceRefs": ["PRD", "Prototype"],
        })
    return {
        "schemaVersion": 1,
        "artifactType": "cross-artifact-preflight",
        "result": "NEEDS_FIX" if findings else "PASS",
        "checks": checks,
        "findings": findings,
        "blockingFindings": len(findings),
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = check(read(args.prd), read(args.prototype))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.json or not args.out:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
