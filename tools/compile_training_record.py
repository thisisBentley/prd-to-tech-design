#!/usr/bin/env python3
"""Compile legacy dataset records into one contract-valid training revision."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from agent_contracts import load, now, normalize_result, save, select_contract, sha256_file, sha256_text, validate_agent_result, validate_contract_release

SYSTEM_PROMPT = "你是受控 AI Native 数字员工。只引用给定证据，明确区分事实、推断和未知，不得补造实现、测试、验收或上线结果。"


def read_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    value = load(path)
    return value if isinstance(value, list) else [value]


def write_records(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def parse_user_message(record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    for message in record.get("messages", []) or []:
        if message.get("role") != "user":
            continue
        content = str(message.get("content", ""))
        try:
            value = json.loads(content)
            if isinstance(value, dict):
                return value, content
        except json.JSONDecodeError:
            pass
        return {"instruction": content}, content
    prompt = str(record.get("prompt", ""))
    return {"instruction": prompt}, prompt


def assert_output(record: dict[str, Any]) -> Any:
    if isinstance(record.get("referenceCompletion"), dict):
        return record["referenceCompletion"]
    if isinstance(record.get("referenceAnswer"), dict):
        return record["referenceAnswer"]
    for message in record.get("messages", []) or []:
        if message.get("role") == "assistant":
            try:
                return json.loads(str(message.get("content", "{}")))
            except json.JSONDecodeError:
                return {}
    return {}


def select_for_record(release: dict[str, Any], record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    task_type = str(record.get("taskType") or payload.get("taskType") or "").upper()
    capability = str(record.get("capabilityMode") or payload.get("capabilityMode") or "").upper()
    mapping = {
        "REVIEW": "AGENT-REVIEW-V1",
        "PLANNING": "AGENT-PLANNING-V1",
        "REPAIR": "AGENT-REPAIR-V1",
        "PROTOTYPE_REPAIR": "AGENT-REPAIR-V1",
        "EVALUATION": "AGENT-EVALUATION-V1",
        "TOOL_USE": "AGENT-TOOL-USE-V1",
        "ORCHESTRATION": "AGENT-ORCHESTRATION-V1",
    }
    contract_id = mapping.get(task_type) or mapping.get(capability)
    return select_contract(release, contract_id=contract_id, capability_mode=capability if not contract_id else None)


def evidence_pack(record: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    value = record.get("evidencePack") or payload.get("evidencePack") or {}
    return value if isinstance(value, dict) else {}


def evidence_refs(record: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    pack = evidence_pack(record, payload)
    refs: list[str] = []
    for key in ("allowedArtifacts", "artifactExcerpts"):
        for item in pack.get(key, []) or []:
            if isinstance(item, dict) and item.get("ref"):
                refs.append(str(item["ref"]))
    for item in record.get("evidenceRefs", []) or []:
        refs.append(str(item))
    for answer_key in ("referenceAnswer", "referenceCompletion"):
        answer = record.get(answer_key)
        if isinstance(answer, dict):
            for item in answer.get("evidence", []) or []:
                if isinstance(item, dict) and item.get("ref"):
                    refs.append(str(item["ref"]))
                elif isinstance(item, str):
                    refs.append(item)
    expected = payload.get("expectedOutput") if isinstance(payload.get("expectedOutput"), dict) else {}
    for item in expected.get("requiredEvidenceRefs", []) or []:
        refs.append(str(item))
    return list(dict.fromkeys(ref for ref in refs if ref.strip()))


def resolve_ref(dataset_root: Path | None, sample_id: str, ref: str) -> Path | None:
    candidate = Path(ref)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    if dataset_root is None:
        return None
    roots = [dataset_root / "issues" / sample_id, dataset_root / "issues" / sample_id / "00-source", dataset_root]
    for root in roots:
        path = root / ref
        if path.exists():
            return path
    return None


def build_context_pack(
    record: dict[str, Any],
    payload: dict[str, Any],
    contract: dict[str, Any],
    dataset_root: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sample_id = str(record.get("sampleId") or payload.get("sampleId") or "UNKNOWN")
    refs = evidence_refs(record, payload)
    evidence: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for index, ref in enumerate(refs, 1):
        resolved = resolve_ref(dataset_root, sample_id, ref)
        digest = sha256_file(resolved) if resolved else sha256_text(ref)
        evidence.append({"id": f"E-{index:03d}", "ref": ref, "sha256": digest})
        artifacts.append({"path": ref, "sha256": digest})
        if dataset_root is not None and resolved is None:
            unresolved.append(ref)
    pack = {
        "schemaVersion": 1,
        "packId": f"context-{record.get('taskId', 'task')}-{contract['contractVersion']}",
        "packType": "ROLE",
        "requirementId": sample_id,
        "revision": contract["contractVersion"],
        "role": "dataset-compiler",
        "scope": [str(record.get("taskId", "task"))],
        "sourceArtifacts": artifacts,
        "facts": [],
        "evidence": evidence,
        "rules": list(contract.get("constraints", [])),
        "forbidden": ["invent_product_facts", "invent_evidence", "modify_frozen_artifacts", "declare_gate_pass"],
        "createdAt": now(),
    }
    return pack, {"refs": refs, "unresolved": unresolved}


def compile_record(record: dict[str, Any], release: dict[str, Any], dataset_root: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, raw_user = parse_user_message(record)
    contract = select_for_record(release, record, payload)
    sample_id = str(record.get("sampleId") or payload.get("sampleId") or "UNKNOWN")
    refs = evidence_refs(record, payload)
    raw_result = assert_output(record)
    result = normalize_result(raw_result, contract, str(record.get("taskId") or payload.get("taskId")), refs)
    context_pack, context_meta = build_context_pack(record, payload, contract, dataset_root)
    validation = validate_agent_result(result, contract, context_pack)
    prompt_payload = dict(payload)
    prompt_payload["outputContract"] = {
        "contractId": contract["contractId"],
        "contractVersion": contract["contractVersion"],
        "taskStatus": " | ".join(contract["allowedTaskStatus"]),
        "reviewVerdict": " | ".join(contract["allowedVerdicts"]),
        "requiredSections": contract["requiredSections"],
        "mustCiteEvidence": bool(contract["evidencePolicy"]["mustCite"]),
    }
    prompt_payload["instructionToModel"] = "根据证据完成任务；只输出符合 outputContract 的结构化 JSON；不要输出分析过程。"
    messages = []
    source_messages = record.get("messages", []) or []
    if not source_messages:
        messages.append({"role": "system", "content": SYSTEM_PROMPT})
        messages.append({"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, indent=2)})
    else:
        for message in source_messages:
            if message.get("role") == "system":
                messages.append({"role": "system", "content": str(message.get("content", SYSTEM_PROMPT))})
            elif message.get("role") == "user":
                messages.append({"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False, indent=2)})
            elif message.get("role") == "assistant":
                messages.append({"role": "assistant", "content": json.dumps(result, ensure_ascii=False, indent=2)})
        if not any(item["role"] == "system" for item in messages):
            messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    compiled = dict(record)
    compiled.update({
        "contractId": contract["contractId"],
        "contractVersion": contract["contractVersion"],
        "contractReleasePath": str(release.get("sourceProfilePath", "")),
        "messages": messages,
        "referenceCompletion": result,
        "contractValidation": {"status": validation["status"], "errors": validation["errors"]},
        "contextPack": context_pack,
        "contextPackUnresolvedRefs": context_meta["unresolved"],
        "compiledAt": now(),
    })
    return compiled, validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--context-dir", type=Path)
    parser.add_argument("--dataset-root", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    release = load(args.release.resolve())
    release_errors = validate_contract_release(release)
    if release_errors:
        print(json.dumps({"status": "FAIL", "errors": release_errors}, ensure_ascii=False, indent=2))
        return 1
    records = read_records(args.input.resolve())
    compiled_records: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    context_dir = args.context_dir.resolve() if args.context_dir else None
    for record in records:
        compiled, validation = compile_record(record, release, args.dataset_root.resolve() if args.dataset_root else None)
        context_path = None
        if context_dir:
            context_path = context_dir / f"{compiled.get('recordId', compiled.get('taskId', 'record'))}.context.json"
            save(context_path, compiled["contextPack"])
            compiled["contextPackPath"] = str(context_path)
            compiled["contextPackSha256"] = sha256_file(context_path)
            compiled.pop("contextPack", None)
        compiled_records.append(compiled)
        results.append({
            "recordId": compiled.get("recordId") or compiled.get("taskId"),
            "taskId": compiled.get("taskId"),
            "contractId": compiled.get("contractId"),
            "taskStatus": compiled.get("referenceCompletion", {}).get("taskStatus"),
            "reviewVerdict": compiled.get("referenceCompletion", {}).get("reviewVerdict"),
            "contractStatus": validation["status"],
            "errors": validation["errors"],
            "unresolvedRefs": compiled.get("contextPackUnresolvedRefs", []),
        })
    write_records(args.out, compiled_records)
    valid = sum(item["contractStatus"] == "PASS" for item in results)
    summary = {
        "schemaVersion": 1,
        "status": "PASS" if valid == len(results) else "FAIL",
        "records": len(results),
        "contractValid": valid,
        "contractInvalid": len(results) - valid,
        "taskStatusCounts": dict(Counter(item["taskStatus"] for item in results)),
        "verdictCounts": dict(Counter(item["reviewVerdict"] for item in results)),
        "unresolvedEvidenceCount": sum(len(item["unresolvedRefs"]) for item in results),
        "out": str(args.out.resolve()),
        "results": results,
    }
    args.out.with_suffix(args.out.suffix + ".report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("status", "records", "contractValid", "contractInvalid", "taskStatusCounts", "verdictCounts", "unresolvedEvidenceCount", "out")}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "PASS" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
