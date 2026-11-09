#!/usr/bin/env python3
"""Assemble a deterministic Context Pack from structured frozen inputs."""
from __future__ import annotations
import argparse, hashlib, json, secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-type", required=True, choices=["PROJECT", "REQUIREMENT", "ROLE"])
    parser.add_argument("--requirement-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--input", action="append", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-id")
    parser.add_argument("--role")
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--parent-pack-id", action="append", default=[])
    args = parser.parse_args()

    facts: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    rules: list[str] = []
    forbidden: list[str] = ["invent_product_facts", "modify_frozen_artifacts", "share_private_reasoning"]
    artifacts: list[dict[str, str]] = []
    seen_facts: set[str] = set()
    seen_evidence: set[str] = set()
    seen_rules: set[str] = set()
    for path in args.input:
        data = load(path)
        path_hash = sha(path)
        artifacts.append({"path": str(path.resolve()), "sha256": path_hash})
        for item in data.get("facts", []) or []:
            item_id = str(item.get("id", ""))
            if not item_id or item_id in seen_facts:
                continue
            facts.append({"id": item_id, "text": str(item["text"]), "sourceRef": str(item.get("sourceRef", path)), "sourceHash": str(item.get("sourceHash", path_hash))})
            seen_facts.add(item_id)
        for item in data.get("evidence", []) or []:
            item_id = str(item.get("id", ""))
            if not item_id or item_id in seen_evidence:
                continue
            evidence.append({"id": item_id, "ref": str(item.get("ref", path)), "sha256": str(item.get("sha256", path_hash)), **({"quote": str(item["quote"])} if "quote" in item else {})})
            seen_evidence.add(item_id)
        for rule in data.get("rules", []) or []:
            if rule not in seen_rules:
                rules.append(str(rule)); seen_rules.add(rule)
        forbidden.extend(str(x) for x in data.get("forbidden", []) or [] if str(x) not in forbidden)

    result = {
        "schemaVersion": 1,
        "packId": f"context-pack-{args.pack_type.lower()}-{secrets.token_hex(4)}",
        "packType": args.pack_type,
        "requirementId": args.requirement_id,
        "revision": args.revision,
        "sourceArtifacts": artifacts,
        "facts": facts,
        "evidence": evidence,
        "rules": rules,
        "forbidden": list(dict.fromkeys(forbidden)),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    if args.project_id: result["projectId"] = args.project_id
    if args.role: result["role"] = args.role
    if args.scope: result["scope"] = args.scope
    if args.parent_pack_id: result["parentPackIds"] = args.parent_pack_id
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
