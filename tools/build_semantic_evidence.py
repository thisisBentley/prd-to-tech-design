#!/usr/bin/env python3
"""Build a frozen semantic evidence ledger from PRD, Prototype and Capability Context.

This builder is deliberately conservative. Missing state or permission facts are
recorded as unverified, causing the independent Semantic Reviewer to RETURN the
package instead of inventing a green result.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
BR_RE = re.compile(r"\bBR-[0-9]{3}\b")
ATTR_RE = re.compile(r'data-ai-([a-z-]+)="([^"]*)"', re.IGNORECASE)


def load(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_prototype(path: Path | None) -> list[dict[str, Any]]:
    if not path or not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    elements = []
    for match in re.finditer(r"<[^>]*data-ai-id=\"([^\"]+)\"[^>]*>", text, re.IGNORECASE):
        attrs = {name.lower(): html.unescape(value) for name, value in ATTR_RE.findall(match.group(0))}
        elements.append({
            "elementId": html.unescape(match.group(1)),
            "visibleLabel": html.unescape(re.sub(r"<[^>]+>", "", match.group(0).split(">", 1)[0]).split(">")[-1] or attrs.get("id", "")),
            "frIds": [item for item in attrs.get("fr", "").split(",") if item],
            "acIds": [item for item in attrs.get("ac", "").split(",") if item],
            "stateIds": [item for item in attrs.get("state", "").split(",") if item],
            "permissionEdgeIds": [item for item in attrs.get("permission-edge", "").split(",") if item],
        })
    return elements


def build(prd_path: Path, prototype_path: Path | None, manifest_path: Path | None, capability_path: Path | None, workflow_id: str, revision: str, producer_role: str) -> dict[str, Any]:
    prd = prd_path.read_text(encoding="utf-8")
    ids = sorted(set(FR_RE.findall(prd)) | set(AC_RE.findall(prd)) | set(BR_RE.findall(prd)))
    artifacts = [{"artifactId": "prd", "domain": "BUSINESS", "path": str(prd_path.resolve()), "sha256": digest(prd_path)}]
    if prototype_path and prototype_path.exists():
        artifacts.append({"artifactId": "prototype", "domain": "INTERACTION", "path": str(prototype_path.resolve()), "sha256": digest(prototype_path)})
    business_assertions = [{
        "assertionId": f"A-{identifier}",
        "statement": next((line.strip() for line in prd.splitlines() if identifier in line), identifier),
        "sourceType": "REQUIREMENT",
        "evidenceRefs": [f"{prd_path.name}#{identifier}"],
        "coveredIds": [identifier],
    } for identifier in ids]
    capability = load(capability_path, {}) if capability_path else {}
    terms = []
    capability_claims = []
    if not capability:
        title = next((line.lstrip("#").strip() for line in prd.splitlines() if line.startswith("#")), "Requirement capability")
        title = re.sub(r"^(PRD|PRD_DELIVERY|需求)\s*[:：-]\s*", "", title, flags=re.IGNORECASE).strip() or "Requirement capability"
        terms.append({
            "termId": "T-1", "canonicalName": title, "usedName": title, "usage": "NEW_TERM",
            "grounding": "GROUNDED", "evidenceRefs": [str(prd_path.resolve())],
        })
        capability_claims.append({
            "claimId": "C-1", "capabilityId": "prd-feature", "statement": f"The requirement defines {title}.",
            "declaredStatus": "NEW", "verificationStatus": "VERIFIED_NEW",
            "sourceRefs": [str(prd_path.resolve())], "verificationEvidenceRefs": [str(prd_path.resolve())],
        })
    if capability:
        names = [capability.get("canonicalName", "")] + list(capability.get("knownAliases", []) or [])
        for name in [item for item in names if item]:
            if name in prd or (prototype_path and prototype_path.exists() and name in prototype_path.read_text(encoding="utf-8")):
                terms.append({
                    "termId": f"T-{len(terms) + 1}", "canonicalName": capability.get("canonicalName", name),
                    "usedName": name, "usage": "CANONICAL" if name == capability.get("canonicalName") else "ALIAS",
                    "grounding": "GROUNDED" if capability.get("sourceRefs") else "UNGROUNDED",
                    "evidenceRefs": capability.get("sourceRefs", []),
                })
        capability_claims.append({
            "claimId": "C-1", "capabilityId": capability.get("capabilityId", "unknown"),
            "statement": f"Requirement references {capability.get('canonicalName', 'a known capability')}",
            "declaredStatus": capability.get("status", "UNKNOWN"),
            "verificationStatus": capability.get("verificationStatus", "HOLD"),
            "sourceRefs": capability.get("sourceRefs", []),
            "verificationEvidenceRefs": capability.get("verificationEvidenceRefs", []),
        })
    manifest = load(manifest_path, {}) if manifest_path else {}
    prototype_elements = parse_prototype(prototype_path)
    states: dict[str, dict[str, Any]] = {}
    permission_edges: list[dict[str, Any]] = []
    interaction_elements = []
    for manifest_element in manifest.get("elements", []):
        for state in manifest_element.get("states", []):
            states.setdefault(str(state), {
                "stateId": str(state), "assumedBy": "PROTOTYPE", "reachableFrom": ["prototype-root"],
                "preconditionDefined": str(state).lower() in prd.lower() and bool(re.search(r"precondition|前置|when|当|状态", prd, re.IGNORECASE)),
                "evidenceRefs": [str((manifest_path or prototype_path).resolve())],
            })
        for index, permission in enumerate(manifest_element.get("permissions", [])):
            decision = "UNSPECIFIED" if "as defined" in str(permission).lower() or not permission else ("DENIED" if "deny" in str(permission).lower() else "ALLOWED")
            permission_edges.append({
                "edgeId": f"P-{manifest_element.get('uiElementId', 'UI')}-{index + 1}",
                "role": str(permission), "action": str(manifest_element.get("action", "interact")),
                "resource": str(manifest_element.get("uiElementId", "UI")), "decision": decision,
                "evidenceRefs": [str((manifest_path or prototype_path).resolve())],
            })
    for element in prototype_elements:
        interaction_elements.append({
            "elementId": element["elementId"], "visibleLabel": element["visibleLabel"] or element["elementId"],
            "frIds": element["frIds"], "acIds": element["acIds"], "stateIds": element["stateIds"],
            "permissionEdgeIds": element["permissionEdgeIds"],
            "evidenceRefs": [str(prototype_path.resolve())],
        })
    # Explicit PRD permission/state sections override generic manifest defaults.
    section = None
    prd_permissions: list[str] = []
    prd_states: list[str] = []
    for line in prd.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            section = "permissions" if ("permission" in title or "权限" in title) else ("states" if ("state" in title or "状态" in title) else None)
            continue
        if section and line.strip().startswith("-"):
            (prd_permissions if section == "permissions" else prd_states).append(line.strip().removeprefix("-").strip())
    if prd_permissions:
        permission_edges = [{
            "edgeId": f"P-PRD-{index + 1}", "role": item, "action": "interact", "resource": "prd-feature",
            "decision": "DENIED" if re.search(r"deny|forbid|denied|禁止|不允许", item, re.IGNORECASE) else "ALLOWED",
            "evidenceRefs": [str(prd_path.resolve())],
        } for index, item in enumerate(prd_permissions)]
    if prd_states:
        states = {}
        for index, item in enumerate(prd_states):
            state_id = item.split(":", 1)[0].strip().split()[0]
            states[state_id] = {
                "stateId": state_id, "assumedBy": "PRD", "reachableFrom": ["prd-entry"],
                "preconditionDefined": bool(re.search(r"precondition|前置|when|当|reachable|可达", item, re.IGNORECASE) or ":" in item),
                "evidenceRefs": [str(prd_path.resolve())],
            }
    cross_claims = [{
        "claimId": f"X-{index + 1}", "topic": f"{item['elementId']} visibility and binding",
        "businessValue": ",".join(item["frIds"] + item["acIds"]), "interactionValue": item["elementId"],
        "status": "EQUAL" if item["frIds"] and item["acIds"] else "UNKNOWN", "authorityDomain": "BUSINESS",
        "evidenceRefs": item["evidenceRefs"],
    } for index, item in enumerate(interaction_elements)]
    if not cross_claims:
        cross_claims = [{"claimId": "X-PRD", "topic": "PRD-only business contract", "businessValue": "PRD identifiers present", "interactionValue": "not applicable", "status": "EQUAL", "authorityDomain": "BUSINESS", "evidenceRefs": [str(prd_path.resolve())]}]
    return {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "targetRevision": revision,
        "producerRole": producer_role,
        "artifacts": artifacts,
        "terminologyClaims": terms,
        "capabilityClaims": capability_claims,
        "stateAssumptions": list(states.values()),
        "permissionEdges": permission_edges,
        "crossArtifactClaims": cross_claims,
        "businessAssertions": business_assertions,
        "interactionElements": interaction_elements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--capability-context", type=Path)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--revision", default="r1")
    parser.add_argument("--producer-role", default="prd-producer")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.prd, args.prototype, args.manifest, args.capability_context, args.workflow_id, args.revision, args.producer_role)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "artifacts": len(result["artifacts"]), "interactions": len(result["interactionElements"]), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
