#!/usr/bin/env python3
"""Build a pre-PRD generation contract from frozen requirement evidence.

This is a deterministic preflight, not a PRD producer. It turns the GitLab
V2.3.0 generation-contract rules into explicit checks and routes gaps to the
owner that can close them before PRD authoring starts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIREMENT_TYPES = [
    ("CRUD", r"新增|创建|编辑|修改|删除|查询|筛选|分页|排序"),
    ("CORE_WRITE", r"保存|提交|写入|审批|发布|导入|导出|任务"),
    ("MULTI_SYSTEM", r"接口|外部系统|上下游|同步|回调|消息|第三方"),
    ("ASYNC", r"异步|超时|重试|队列|批次|部分成功|晚到|补偿"),
    ("AI_LLM", r"大模型|LLM|Prompt|提示词|模型输出|智能体|拒答|Token|时延"),
    ("HIGH_CONCURRENCY", r"并发|高可用|容量|限流|降级|峰值"),
    ("LEGACY_CHANGE", r"存量|既有|沿用|回归|旧调用"),
    ("MIGRATION", r"迁移|历史数据|回滚"),
    ("COMPATIBILITY", r"兼容|旧版本|灰度|回退"),
    ("UI_INTERACTION", r"页面|入口|字段|按钮|弹窗|抽屉|交互|可见|隐藏|禁用|文案"),
    ("FRONTEND_BACKEND", r"前端|后端|前后端|联动"),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def has(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text, re.IGNORECASE))


def check(
    check_id: str,
    rule_id: str,
    title: str,
    passed: bool,
    observed: str,
    expected: str,
    refs: list[str],
    owner: str,
    close_condition: str,
    failure_status: str = "needs_product",
) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "ruleId": rule_id,
        "stage": "generation_contract",
        "status": "pass" if passed else failure_status,
        "title": title,
        "observed": observed,
        "expected": expected,
        "evidenceRefs": refs,
        "owner": owner,
        "closeCondition": close_condition,
    }


def detect_types(text: str) -> list[str]:
    return [name for name, pattern in REQUIREMENT_TYPES if has(text, pattern)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirement", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--artifact-profile", choices=["PRD_ONLY", "PRD_PLUS_PROTOTYPE", "EXISTING_PROTOTYPE_REVIEW", "EXTERNAL_UI_BOUNDARY"], default="PRD_ONLY")
    parser.add_argument("--decision-context", type=Path)
    parser.add_argument("--capability-context", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    requirement = args.requirement.resolve()
    if not requirement.exists():
        raise SystemExit(f"requirement not found: {requirement}")
    text = requirement.read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    ref = str(requirement)
    checks: list[dict[str, Any]] = []

    checks.append(check("GC.SOURCE", "GEN-01", "Requirement source is readable", bool(text.strip()), f"characters={len(text)}", "non-empty frozen requirement source", [ref], "delivery-producer", "Provide a readable requirement source.", "block"))
    checks.append(check("GC.SCOPE", "GEN-02", "Scope is explicit", has(text, r"本期范围|本期包含|本期不包含|范围"), "scope marker found" if has(text, r"范围") else "scope marker missing", "current scope and adjacent exclusions are identifiable", [ref], "delivery-producer", "Add explicit in-scope and out-of-scope statements."))
    checks.append(check("GC.GOALS", "GEN-03", "Goals are explicit and result-oriented", has(text, r"需求目标|总体目标|目标列表|G-[0-9]{3}"), "goal marker found" if has(text, r"目标|G-[0-9]{3}") else "goal marker missing", "goal describes an observable business result", [ref], "delivery-producer", "Add a business-result goal rather than an implementation action."))
    checks.append(check("GC.ACTORS", "GEN-04", "Actors and permissions are identifiable", has(text, r"角色|运营|管理员|用户|权限"), "actor/permission markers found" if has(text, r"角色|运营|管理员|用户|权限") else "actor/permission markers missing", "roles, visibility and action boundaries are identifiable", [ref], "delivery-producer", "Add role and permission boundaries."))
    checks.append(check("GC.FLOW", "GEN-05", "Primary flow and trigger are identifiable", has(text, r"主流程|流程|前置与触发|入口|点击|进入"), "flow/trigger markers found" if has(text, r"流程|前置与触发|入口|点击") else "flow/trigger markers missing", "entry, trigger, action and result form one closed flow", [ref], "delivery-producer", "Add entry, trigger, action and final result."))
    checks.append(check("GC.RULES", "GEN-06", "Business rules are explicit", has(text, r"业务规则|规则|计算|取值|优先级|互斥"), "business-rule markers found" if has(text, r"规则|计算|优先级|互斥") else "business-rule markers missing", "rules needed to reproduce user results are explicit", [ref], "delivery-producer", "Add the business rule or cite its authoritative location."))
    checks.append(check("GC.STATES", "GEN-07", "Relevant states and transitions are identifiable", has(text, r"状态|加载|空态|失败|禁用|成功|处理中"), "state markers found" if has(text, r"状态|空态|失败|禁用|成功") else "state markers missing", "material user-visible states and transitions are explicit", [ref], "delivery-producer", "Add normal, empty, loading, failure and recovery states where applicable."))
    checks.append(check("GC.EXCEPTIONS", "GEN-08", "Exceptions and recovery are explicit", has(text, r"异常|失败|超时|重试|补偿|恢复|兜底|无权限"), "exception markers found" if has(text, r"异常|失败|超时|重试|恢复") else "exception markers missing", "realistic failure paths state user feedback, retained data and recovery", [ref], "delivery-producer", "Add user-visible failure and recovery behavior."))
    checks.append(check("GC.ACCEPTANCE", "GEN-09", "Acceptance criteria are objectively testable", has(text, r"验收|AC-[0-9]{3}|WHEN|THEN"), "acceptance markers found" if has(text, r"验收|AC-[0-9]{3}|WHEN|THEN") else "acceptance markers missing", "each material behavior has an objective pass/fail criterion", [ref], "delivery-producer", "Add precondition, trigger, expected result and verification method."))

    decision_refs = [ref]
    if args.decision_context and args.decision_context.exists():
        context_path = args.decision_context.resolve()
        try:
            decision = json.loads(context_path.read_text(encoding="utf-8"))
            ready = decision.get("decisionReadiness") == "READY" or decision.get("readiness") == "READY"
            open_count = int(decision.get("openBlockingCount", 0))
            checks.append(check("GC.DECISION_CONTEXT", "GEN-10", "Blocking product decisions are closed", ready and open_count == 0, f"readiness={decision.get('decisionReadiness', decision.get('readiness'))} openBlockingCount={open_count}", "Decision Context is READY with no open blocking decisions", [str(context_path)], "product-owner", "Close open Decision Cards and refresh Decision Context.", "needs_product"))
            decision_refs.append(str(context_path))
        except Exception as exc:
            checks.append(check("GC.DECISION_CONTEXT", "GEN-10", "Blocking product decisions are closed", False, f"invalid decision context: {exc}", "Decision Context is readable and READY", [str(context_path)], "product-owner", "Repair the Decision Context.", "needs_product"))
    else:
        pending = has(text, r"待确认|待定|需产品确认|待产品")
        checks.append(check("GC.DECISION_CONTEXT", "GEN-10", "Decision readiness source exists", not pending, "decision context not supplied; no pending marker" if not pending else "pending product-decision marker exists without Decision Context", "Decision Context is READY or no blocking decision exists", decision_refs, "product-owner", "Create or consume a READY Decision Context."))

    if args.capability_context and args.capability_context.exists():
        capability_path = args.capability_context.resolve()
        try:
            capability = json.loads(capability_path.read_text(encoding="utf-8"))
            has_entries = bool(capability.get("capabilities") or capability.get("items") or capability.get("entries"))
            checks.append(check("GC.CAPABILITY_CONTEXT", "GEN-11", "Existing-capability evidence is available", has_entries, f"entries={len(capability.get('capabilities', capability.get('items', capability.get('entries', []))))}", "existing capability claims have provenance and confidence", [str(capability_path)], "delivery-producer", "Add verified capability records or record them as new capabilities.", "needs_role"))
        except Exception as exc:
            checks.append(check("GC.CAPABILITY_CONTEXT", "GEN-11", "Existing-capability evidence is available", False, f"invalid capability context: {exc}", "Capability Context is readable", [str(capability_path)], "delivery-producer", "Repair the Capability Context.", "needs_role"))
    else:
        checks.append(check("GC.CAPABILITY_CONTEXT", "GEN-11", "Existing-capability evidence is available", False, "capability context not supplied", "existing / new / extension claims are grounded", [ref], "delivery-producer", "Collect Capability Context or explicitly classify the capability as new.", "needs_role"))

    requirement_types = detect_types(text)
    conditional = {
        "UI_INTERACTION": ("GC.TYPE.UI", "User-visible entry, state, permission and feedback are explicit", r"入口|页面|可见|隐藏|禁用|文案|状态", "delivery-producer"),
        "CORE_WRITE": ("GC.TYPE.CORE_WRITE", "Repeat, concurrent and recovery outcomes are explicit", r"重复|并发|幂等|失败|恢复", "delivery-producer"),
        "ASYNC": ("GC.TYPE.ASYNC", "Timeout, partial success, retry and compensation are explicit", r"超时|重试|部分成功|补偿|晚到", "delivery-producer"),
        "AI_LLM": ("GC.TYPE.AI", "Output contract, quality, latency, cost and failure are explicit", r"输出契约|拒答|非法输出|质量|Token|时延|成本|降级|兜底", "delivery-producer"),
        "HIGH_CONCURRENCY": ("GC.TYPE.CAPACITY", "Capacity, limit and degradation are explicit", r"容量|上限|限流|排队|降级", "delivery-producer"),
        "LEGACY_CHANGE": ("GC.TYPE.LEGACY", "Legacy behavior and regression boundary are explicit", r"既有|沿用|回归|旧版本|兼容", "delivery-producer"),
        "MIGRATION": ("GC.TYPE.MIGRATION", "History, migration and rollback are explicit", r"历史数据|迁移|回滚|灰度", "delivery-producer"),
    }
    for requirement_type in requirement_types:
        if requirement_type not in conditional:
            continue
        check_id, title, pattern, owner = conditional[requirement_type]
        passed = has(text, pattern)
        checks.append(check(check_id, f"GEN-TYPE-{requirement_type}", title, passed, f"requirementType={requirement_type} present={'yes' if passed else 'no'}", "conditional contract facts are complete for the detected requirement type", [ref], owner, f"Add the {requirement_type} conditional facts before PRD authoring."))

    metrics = {
        "checks": len(checks),
        "passed": sum(1 for item in checks if item["status"] == "pass"),
        "warnings": sum(1 for item in checks if item["status"] == "warn"),
        "needsRole": sum(1 for item in checks if item["status"] == "needs_role"),
        "needsProduct": sum(1 for item in checks if item["status"] == "needs_product"),
        "blocked": sum(1 for item in checks if item["status"] == "block"),
    }
    if metrics["blocked"]:
        status = "BLOCKED"
    elif metrics["warnings"] or metrics["needsRole"] or metrics["needsProduct"]:
        status = "READY_WITH_ACTIONS"
    else:
        status = "READY"

    payload = {
        "schemaVersion": 1,
        "workflowId": args.workflow_id,
        "requirementId": args.requirement_id,
        "artifactProfile": args.artifact_profile,
        "sourcePath": ref,
        "sourceSha256": sha256(requirement),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "requirementTypes": requirement_types,
        "status": status,
        "checks": checks,
        "metrics": metrics,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "checks": len(checks), "requirementTypes": requirement_types, "out": str(args.out)}, ensure_ascii=False))
    return 0 if status != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
