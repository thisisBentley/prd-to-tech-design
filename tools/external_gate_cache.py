#!/usr/bin/env python3
"""Content-addressed cache helpers for normalized external gate verdicts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from semantic_convergence import canonical_hash, load, save, sha256_file
from trust_kernel import now, validate_schema_value


class VerdictCacheConflict(ValueError):
    """Raised when the same candidate evidence has conflicting external verdicts."""

    def __init__(self, message: str, conflicts: list[dict[str, Any]]):
        super().__init__(message)
        self.conflicts = conflicts


@dataclass(frozen=True)
class CacheIdentity:
    evidence_key: str
    cache_key: str


def _artifact_identity(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(item.get("path", "")),
            "declaredSha256": item.get("declaredSha256"),
            "actualSha256": item.get("actualSha256"),
        }
        for item in verdict.get("candidateArtifacts", [])
        if isinstance(item, dict)
    ]


def evidence_payload(verdict: dict[str, Any]) -> dict[str, Any]:
    """Identity that groups repeated gate runs for the same candidate evidence."""
    return {
        "workflowId": verdict.get("workflowId"),
        "candidateRevision": verdict.get("candidateRevision"),
        "jiraKey": verdict.get("jiraKey"),
        "gateType": verdict.get("gateType"),
        "tool": verdict.get("tool"),
        "candidateArtifacts": _artifact_identity(verdict),
        "targetBindingReportId": (verdict.get("targetBinding") or {}).get("reportId"),
    }


def result_payload(verdict: dict[str, Any]) -> dict[str, Any]:
    """Stable result identity; timestamps and local output paths are excluded."""
    return {
        "evidenceKey": canonical_hash(evidence_payload(verdict)),
        "verdict": verdict.get("verdict"),
        "releaseState": verdict.get("releaseState"),
        "closureEligible": bool(verdict.get("closureEligible")),
        "findings": verdict.get("findings", []),
        "tool": verdict.get("tool"),
        "candidateArtifacts": _artifact_identity(verdict),
        "targetBinding": verdict.get("targetBinding"),
    }


def identity_for_verdict(verdict: dict[str, Any]) -> CacheIdentity:
    errors = validate_schema_value(verdict, "external-gate-verdict.schema.json")
    if errors:
        raise ValueError("invalid external gate verdict: " + "; ".join(errors))
    result = result_payload(verdict)
    return CacheIdentity(
        evidence_key=result["evidenceKey"],
        cache_key=canonical_hash(result),
    )


def verify_cache_entry(entry: dict[str, Any]) -> list[str]:
    errors = validate_schema_value(entry, "external-gate-cache-entry.schema.json")
    if errors:
        return errors
    record = entry.get("verdictRecord")
    if not isinstance(record, dict):
        return ["verdictRecord must be an object"]
    record_errors = validate_schema_value(record, "external-gate-verdict.schema.json")
    if record_errors:
        return ["verdictRecord: " + item for item in record_errors]
    identity = identity_for_verdict(record)
    if entry.get("evidenceKey") != identity.evidence_key:
        return ["cache evidenceKey does not match verdictRecord"]
    if entry.get("cacheKey") != identity.cache_key:
        return ["cache key does not match verdictRecord"]
    if entry.get("verdictId") != record.get("verdictId"):
        return ["cache verdictId does not match verdictRecord"]
    if entry.get("recordSha256") != canonical_hash(record):
        return ["cache recordSha256 does not match verdictRecord"]
    for key in ("workflowId", "candidateRevision", "jiraKey", "gateType", "verdict", "releaseState", "closureEligible", "tool"):
        if entry.get(key) != record.get(key):
            return [f"cache {key} does not match verdictRecord"]
    if entry.get("candidateArtifacts") != record.get("candidateArtifacts"):
        return ["cache candidateArtifacts do not match verdictRecord"]
    return []


def load_cached_entries(cache_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entries: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    if not cache_dir.is_dir():
        return entries, invalid
    for path in sorted(cache_dir.glob("*.json")):
        try:
            entry = load(path)
            errors = verify_cache_entry(entry)
        except Exception as exc:
            errors = [str(exc)]
            entry = {}
        if errors:
            invalid.append({"path": str(path.resolve()), "errors": errors})
        else:
            entries.append({**entry, "_path": str(path.resolve())})
    return entries, invalid


def cache_verdict(verdict: dict[str, Any], cache_dir: Path, source_path: str = "") -> dict[str, Any]:
    identity = identity_for_verdict(verdict)
    cache_dir.mkdir(parents=True, exist_ok=True)
    record_sha = canonical_hash(verdict)
    entry_without_hash = {
        "schemaVersion": 1,
        "cacheKey": identity.cache_key,
        "evidenceKey": identity.evidence_key,
        "workflowId": verdict["workflowId"],
        "candidateRevision": verdict["candidateRevision"],
        "jiraKey": verdict["jiraKey"],
        "gateType": verdict["gateType"],
        "verdict": verdict["verdict"],
        "releaseState": verdict["releaseState"],
        "closureEligible": verdict["closureEligible"],
        "tool": verdict["tool"],
        "candidateArtifacts": verdict["candidateArtifacts"],
        "verdictId": verdict["verdictId"],
        "verdictRecord": verdict,
        "recordSha256": record_sha,
        "sourcePath": source_path or "<in-memory>",
    }
    entry = {
        **entry_without_hash,
        "cachedAt": now(),
    }
    errors = validate_schema_value(entry, "external-gate-cache-entry.schema.json")
    if errors:
        raise ValueError("invalid cache entry: " + "; ".join(errors))

    conflicts: list[dict[str, Any]] = []
    existing_entries, _ = load_cached_entries(cache_dir)
    for existing in existing_entries:
        if existing.get("evidenceKey") == identity.evidence_key and existing.get("cacheKey") != identity.cache_key:
            conflicts.append({
                "cacheKey": existing.get("cacheKey"),
                "verdict": existing.get("verdict"),
                "path": existing.get("_path"),
            })
    if conflicts:
        raise VerdictCacheConflict("conflicting external verdicts exist for the same candidate evidence", conflicts)

    path = cache_dir / f"{identity.cache_key}.json"
    if path.is_file():
        existing = load(path)
        errors = verify_cache_entry(existing)
        if errors:
            raise ValueError("existing cache entry is invalid: " + "; ".join(errors))
        if existing.get("cacheKey") != identity.cache_key:
            raise VerdictCacheConflict("existing cache entry conflicts with new verdict", [{"path": str(path)}])
        return {"status": "CACHED", "cacheKey": identity.cache_key, "evidenceKey": identity.evidence_key, "path": str(path.resolve()), "entry": existing}

    save(path, entry)
    return {"status": "WRITTEN", "cacheKey": identity.cache_key, "evidenceKey": identity.evidence_key, "path": str(path.resolve()), "entry": entry}
