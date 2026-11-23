#!/usr/bin/env python3
"""Build and validate source packs with explicit authority and allowed-use governance."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUTHORITY_ORDER = ["USER_DECISION", "NORMATIVE", "SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"]
AUTHORITY_RANK = {value: index for index, value in enumerate(AUTHORITY_ORDER)}
ALLOWED_USES = ["DESIGN_REFERENCE", "EVALUATION_CORPUS", "RUNTIME_INPUT", "TRAINING_CANDIDATE"]
SOURCE_CLASSES = ["NORMATIVE", "SOURCE_FACT", "MEASURED", "DERIVED", "REFERENCE", "INFERENCE"]
CLASS_LEVELS = {
    "NORMATIVE": {"USER_DECISION", "NORMATIVE"},
    "SOURCE_FACT": {"SOURCE_FACT"},
    "MEASURED": {"MEASURED"},
    "DERIVED": {"DERIVED"},
    "REFERENCE": {"REFERENCE"},
    "INFERENCE": {"INFERENCE"},
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_source_path(entry: dict[str, Any], repo_root: Path) -> Path | None:
    locator_type = entry.get("locatorType")
    value = str(entry.get("pathOrRef", ""))
    if locator_type == "REPO_PATH":
        direct = repo_root / value
        if direct.is_file():
            return direct.resolve()
        # Local Skills use references/ instead of docs/ and schemas/.
        if (repo_root / "scripts").is_dir():
            if value.startswith("schemas/"):
                local = repo_root / "references" / Path(value).name
                if local.is_file():
                    return local.resolve()
            if value.startswith("core/"):
                local = repo_root / "references" / Path(value).name
                if local.is_file():
                    return local.resolve()
            if value.startswith("docs/"):
                local = repo_root / "references" / Path(value).name
                if local.is_file():
                    return local.resolve()
        return direct.resolve()
    if locator_type == "LOCAL_PATH":
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (repo_root / path).resolve()
    return None


def build_registry(catalog: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in catalog.get("sources") or []:
        entry = {key: raw[key] for key in raw if key != "resolvePath"}
        source_id = str(entry["sourceId"])
        if source_id in seen:
            raise ValueError(f"duplicate sourceId: {source_id}")
        seen.add(source_id)
        path = resolve_source_path(entry, repo_root)
        if path is not None:
            if not path.is_file():
                raise ValueError(f"source file missing: {source_id}: {path}")
            entry["sha256"] = sha256_file(path)
            entry["sourceLock"] = {**entry["sourceLock"], "kind": "CONTENT_HASH", "locator": str(path), "status": "LOCKED"}
        elif entry.get("locatorType") == "ATTACHMENT" and entry.get("sha256"):
            entry["sourceLock"] = {**entry["sourceLock"], "kind": "CONTENT_HASH", "locator": str(entry["pathOrRef"]), "status": "LOCKED"}
        sources.append(entry)

    counts = {source_class: sum(1 for item in sources if item["sourceClass"] == source_class) for source_class in SOURCE_CLASSES}
    coverage = {source_class: {"status": "PRESENT" if counts[source_class] else "NOT_PRESENT", "count": counts[source_class]} for source_class in SOURCE_CLASSES}
    registry = {
        "schemaVersion": 1,
        "packId": catalog["packId"],
        "description": catalog.get("description", "Source Pack Registry"),
        "status": "PASS",
        "authorityOrder": AUTHORITY_ORDER,
        "allowedUses": ALLOWED_USES,
        "sources": sources,
        "conflicts": catalog.get("conflicts", []),
        "coverage": coverage,
        "metrics": {
            "sourceCount": len(sources),
            "lockedCount": sum(1 for item in sources if item["sourceLock"]["status"] == "LOCKED"),
            "trainingCandidateCount": sum(1 for item in sources if item["trainingCandidate"]),
            "conflictCount": len(catalog.get("conflicts", [])),
        },
        "createdAt": now(),
    }
    errors = validate_registry(registry, repo_root)
    registry["status"] = "PASS" if not errors else "BLOCKED"
    if errors:
        raise ValueError("; ".join(errors))
    return registry


def validate_registry(registry: dict[str, Any], repo_root: Path | None = None, verify_files: bool = True) -> list[str]:
    errors: list[str] = []
    if registry.get("authorityOrder") != AUTHORITY_ORDER:
        errors.append("authorityOrder must match the fixed hierarchy")
    if registry.get("allowedUses") != ALLOWED_USES:
        errors.append("allowedUses must match the fixed vocabulary")

    sources = registry.get("sources") or []
    source_ids: set[str] = set()
    for source in sources:
        source_id = str(source.get("sourceId") or "")
        if source_id in source_ids:
            errors.append(f"duplicate sourceId: {source_id}")
        source_ids.add(source_id)
        source_class = source.get("sourceClass")
        authority = source.get("authorityLevel")
        uses = set(source.get("allowedUses") or [])
        if authority not in CLASS_LEVELS.get(source_class, set()):
            errors.append(f"{source_id}: authorityLevel {authority} is invalid for {source_class}")
        if source.get("trainingCandidate") and "TRAINING_CANDIDATE" not in uses:
            errors.append(f"{source_id}: trainingCandidate requires TRAINING_CANDIDATE use")
        if source.get("trainingCandidate"):
            errors.append(f"{source_id}: TRAINING_CANDIDATE is disabled in D.12")
        if source_class == "REFERENCE" and uses != {"DESIGN_REFERENCE"}:
            errors.append(f"{source_id}: REFERENCE sources may only be used as DESIGN_REFERENCE")
        if source_class == "INFERENCE" and "RUNTIME_INPUT" in uses:
            errors.append(f"{source_id}: INFERENCE cannot be a runtime input")
        if source.get("license", {}).get("status") != "KNOWN" and ({"RUNTIME_INPUT", "EVALUATION_CORPUS", "TRAINING_CANDIDATE"} & uses):
            errors.append(f"{source_id}: unconfirmed license permits DESIGN_REFERENCE only")
        if source.get("confidentiality") == "UNKNOWN" and ({"RUNTIME_INPUT", "TRAINING_CANDIDATE"} & uses):
            errors.append(f"{source_id}: unknown confidentiality cannot be runtime or training input")
        if source.get("sourceLock", {}).get("status") == "STALE":
            errors.append(f"{source_id}: source lock is stale")
        path = resolve_source_path(source, repo_root) if repo_root is not None else None
        if verify_files and path is not None:
            if not path.is_file():
                errors.append(f"{source_id}: source file missing")
            elif source.get("sha256") != sha256_file(path):
                errors.append(f"{source_id}: sha256 drift")

    for conflict in registry.get("conflicts") or []:
        for source_id in conflict.get("sourceIds", []):
            if source_id not in source_ids:
                errors.append(f"{conflict.get('conflictId')}: unknown sourceId {source_id}")
        if conflict.get("resolution") == "OPEN":
            errors.append(f"{conflict.get('conflictId')}: conflict remains open")

    counts = {source_class: sum(1 for item in sources if item.get("sourceClass") == source_class) for source_class in SOURCE_CLASSES}
    for source_class, count in counts.items():
        coverage = (registry.get("coverage") or {}).get(source_class) or {}
        expected_status = "PRESENT" if count else "NOT_PRESENT"
        if coverage.get("status") != expected_status or coverage.get("count") != count:
            errors.append(f"coverage mismatch for {source_class}")
    return errors


def source_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("sourceId")): item for item in registry.get("sources") or []}


def validate_tool_sources(tool: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    available = source_map(registry)
    refs = tool.get("sourcePackRefs") or []
    if not refs:
        errors.append("tool sourcePackRefs must not be empty")
    for source_id in refs:
        source = available.get(source_id)
        if source is None:
            errors.append(f"unknown sourcePackRef: {source_id}")
            continue
        if "RUNTIME_INPUT" not in set(source.get("allowedUses") or []):
            errors.append(f"sourcePackRef {source_id} is not permitted as RUNTIME_INPUT")
        if source.get("sourceLock", {}).get("status") != "LOCKED":
            errors.append(f"sourcePackRef {source_id} is not locked")
    return errors
