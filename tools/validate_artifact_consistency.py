#!/usr/bin/env python3
"""Deterministic PRD / Prototype / Overview consistency gate."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FR_RE = re.compile(r"\bFR-[0-9]{3}\b")
AC_RE = re.compile(r"\bAC-[0-9]{3}\b")
UI_RE = re.compile(r"\bUI-[A-Za-z0-9_-]+\b")
HTML_ID_RE = re.compile(r'data-ai-id=["\']([^"\']+)["\']')
HTML_TAG_RE = re.compile(r'<[^>]*data-ai-id=["\']([^"\']+)["\'][^>]*>')
HTML_FR_RE = re.compile(r'data-ai-fr=["\']([^"\']*)["\']')
HTML_AC_RE = re.compile(r'data-ai-ac=["\']([^"\']*)["\']')


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(check_id: str, kind: str, passed: bool, evidence: list[str], observed: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "checkId": check_id,
        "type": kind,
        "status": "passed" if passed else "failed",
        "severity": "NON_BLOCKING" if passed else "BLOCKING",
        "evidenceRefs": evidence,
        "observed": observed,
        "expected": "PRD, Prototype, Overview and Prototype Manifest are synchronized at the same revision.",
        "owner": extra.pop("owner", "delivery-main-agent"),
        "closeCondition": extra.pop("closeCondition", "Resolve the consistency finding and rerun the consistency gate."),
        "regressionTests": extra.pop("regressionTests", ["rerun artifact consistency gate"]),
    }
    payload.update(extra)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", type=Path, required=True)
    parser.add_argument("--prd", type=Path, required=True)
    parser.add_argument("--prototype", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--overview", type=Path)
    parser.add_argument("--delta", type=Path)
    parser.add_argument("--reconciliation", type=Path)
    parser.add_argument("--strict-copy", action="store_true")
    parser.add_argument("--strict-permissions", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pair = load(args.pair); manifest = load(args.manifest)
    prd_path = args.prd.resolve(); prototype_path = args.prototype.resolve()
    prd_text = prd_path.read_text(encoding="utf-8")
    html = prototype_path.read_text(encoding="utf-8")
    prd_fr = set(FR_RE.findall(prd_text)); prd_ac = set(AC_RE.findall(prd_text))
    prd_ui = set(UI_RE.findall(prd_text))
    manifest_ids = {item["uiElementId"] for item in manifest.get("elements", [])}
    html_ids = set(HTML_ID_RE.findall(html))
    html_bindings: dict[str, tuple[set[str], set[str]]] = {}
    for tag in HTML_TAG_RE.findall(html):
        tag_markup = next((part for part in re.findall(r'<[^>]*>', html) if f'data-ai-id="{tag}"' in part or f"data-ai-id='{tag}'" in part), "")
        fr_match = HTML_FR_RE.search(tag_markup)
        ac_match = HTML_AC_RE.search(tag_markup)
        split = lambda value: set(filter(None, re.split(r'[,;\s]+', value or '')))
        html_bindings[tag] = (split(fr_match.group(1) if fr_match else ""), split(ac_match.group(1) if ac_match else ""))
    checks: list[dict[str, Any]] = []

    authority = pair.get("authorityMatrix", {})
    authority_ok = authority == {"businessDomain": "PRD", "interactionDomain": "PROTOTYPE", "conflictPolicy": "RESYNC_REQUIRED"} and set(pair.get("sourceDomains", [])) >= {"PRD", "PROTOTYPE"}
    checks.append(check("PAIR.AUTHORITY", "SOURCE_AUTHORITY_CONTRACT", authority_ok, [str(args.pair)], f"authorityMatrix={authority}", owner="delivery-main-agent", closeCondition="Reseal the Artifact Pair with PRD business authority, Prototype interaction authority, and RESYNC_REQUIRED conflict policy."))

    revisions_match = pair.get("prdRevision") == pair.get("prototypeRevision") == manifest.get("prototypeRevision")
    checks.append(check("PAIR.REVISION", "STALE_ARTIFACT_PAIR", revisions_match, [str(args.pair), str(args.manifest)], f"PRD={pair.get('prdRevision')} Prototype={pair.get('prototypeRevision')} Manifest={manifest.get('prototypeRevision')}", owner="delivery-main-agent", closeCondition="Regenerate PRD/Prototype/Manifest on the same revision and re-seal the pair."))
    checks.append(check("PAIR.STATUS", "STALE_ARTIFACT_PAIR", pair.get("pairStatus") == "SYNCED", [str(args.pair)], f"pairStatus={pair.get('pairStatus')}", owner="delivery-main-agent", closeCondition="Resolve pending revisions and set pairStatus=SYNCED."))
    checks.append(check("PAIR.PRD_HASH", "STALE_ARTIFACT_PAIR", pair.get("prdHash") == digest(prd_path), [str(args.pair), str(prd_path)], "PRD hash must match the sealed Artifact Pair.", owner="delivery-main-agent", closeCondition="Rebuild the Artifact Pair after PRD changes."))
    checks.append(check("PAIR.PROTOTYPE_HASH", "STALE_ARTIFACT_PAIR", pair.get("prototypeHash") == digest(prototype_path) == manifest.get("prototypeHash"), [str(args.pair), str(prototype_path), str(args.manifest)], "Prototype hash must match Pair and Manifest.", owner="prototype-agent", closeCondition="Rebuild Prototype Manifest and Artifact Pair."))

    for element in manifest.get("elements", []):
        ui_id = element["uiElementId"]
        missing_fr = sorted(set(element.get("frIds", [])) - prd_fr)
        missing_ac = sorted(set(element.get("acIds", [])) - prd_ac)
        passed = not missing_fr and not missing_ac
        checks.append(check(f"ELEMENT.PRD_BINDING.{ui_id}", "ORPHAN_UI_ELEMENT", passed, [str(args.prd), str(args.manifest)], f"UI element {ui_id} references missing PRD ids FR={missing_fr} AC={missing_ac}", uiElementId=ui_id, frIds=element.get("frIds", []), acIds=element.get("acIds", []), owner="prototype-agent" if not passed else "delivery-main-agent", closeCondition=f"Bind {ui_id} to existing PRD FR/AC or remove it from Prototype."))
        checks.append(check(f"ELEMENT.HTML.{ui_id}", "PROTOTYPE_MANIFEST_HTML_DRIFT", ui_id in html_ids, [str(args.prototype), str(args.manifest)], f"Manifest element {ui_id} present in HTML={ui_id in html_ids}", uiElementId=ui_id, owner="prototype-agent", closeCondition=f"Add data-ai-id=\"{ui_id}\" to Prototype or remove it from Manifest."))
        checks.append(check(f"ELEMENT.STATE.{ui_id}", "MISSING_STATE_PROTOTYPE", bool(element.get("states")), [str(args.manifest)], f"States={element.get('states', [])}", uiElementId=ui_id, owner="prototype-agent", closeCondition=f"Declare at least one meaningful state for {ui_id}."))
        html_fr, html_ac = html_bindings.get(ui_id, (set(), set()))
        binding_ok = html_fr == set(element.get("frIds", [])) and html_ac == set(element.get("acIds", []))
        checks.append(check(f"ELEMENT.HTML_BINDING.{ui_id}", "PROTOTYPE_MANIFEST_HTML_DRIFT", binding_ok, [str(args.prototype), str(args.manifest)], f"HTML FR={sorted(html_fr)} AC={sorted(html_ac)}; Manifest FR={element.get('frIds', [])} AC={element.get('acIds', [])}", uiElementId=ui_id, owner="prototype-agent", closeCondition=f"Align data-ai-fr/data-ai-ac for {ui_id} with the Manifest and PRD."))

    for ui_id in sorted(prd_ui - manifest_ids):
        checks.append(check(f"PRD.REQUIRED_UI.{ui_id}", "MISSING_UI_ELEMENT", False, [str(args.prd), str(args.manifest)], f"PRD references {ui_id}, but Prototype Manifest does not contain it.", uiElementId=ui_id, owner="prototype-agent", closeCondition=f"Add {ui_id} to Prototype and Manifest or remove it from PRD."))
    for ui_id in sorted(html_ids - manifest_ids):
        checks.append(check(f"HTML.UNMANIFESTED.{ui_id}", "ORPHAN_UI_ELEMENT", False, [str(args.prototype), str(args.manifest)], f"Prototype HTML contains unmanifested element {ui_id}.", uiElementId=ui_id, owner="prototype-agent", closeCondition=f"Add {ui_id} to the Manifest with FR/AC links or remove it from Prototype."))

    if args.previous_manifest:
        previous = load(args.previous_manifest)
        previous_ids = {item["uiElementId"] for item in previous.get("elements", [])}
        for removed in previous.get("elements", []):
            ui_id = removed["uiElementId"]
            if ui_id in manifest_ids:
                continue
            leftover_fr = sorted(set(removed.get("frIds", [])) & prd_fr)
            leftover_ac = sorted(set(removed.get("acIds", [])) & prd_ac)
            passed = not leftover_fr and not leftover_ac
            checks.append(check(f"DELETED.PRD_SYNC.{ui_id}", "DELETED_UI_ELEMENT_STILL_PRESENT_IN_PRD", passed, [str(args.previous_manifest), str(args.manifest), str(args.prd)], f"Deleted {ui_id}; remaining PRD refs FR={leftover_fr} AC={leftover_ac}", uiElementId=ui_id, frIds=leftover_fr, acIds=leftover_ac, owner="prd-agent" if not passed else "delivery-main-agent", closeCondition=f"Delete, migrate, or mark NOT_APPLICABLE the PRD FR/AC for {ui_id}."))

    if args.overview:
        overview_path = args.overview.resolve()
        overview_hash_ok = pair.get("overviewHash") == digest(overview_path)
        overview_revision_ok = pair.get("overviewRevision") == pair.get("prdRevision")
        checks.append(check("PAIR.OVERVIEW", "STALE_OVERVIEW", overview_hash_ok and overview_revision_ok, [str(args.pair), str(overview_path)], f"Overview revision={pair.get('overviewRevision')} PRD revision={pair.get('prdRevision')} hashMatch={overview_hash_ok}", owner="overview-agent", closeCondition="Regenerate Overview from the current SYNCED PRD/Prototype pair."))

    reconciliation = load(args.reconciliation) if args.reconciliation else None
    if args.delta:
        delta = load(args.delta)
        needs_reconciliation = delta.get("changeType") == "SEMANTIC" or delta.get("requiresPrdReconciliation") is True
        reconciled = bool(
            reconciliation
            and reconciliation.get("status") == "SYNCED"
            and reconciliation.get("sourcePrototypeDeltaId") == delta.get("deltaId")
            and not reconciliation.get("unresolvedDeltas")
        )
        checks.append(check(
            "DELTA.PRD_RECONCILIATION",
            "UNRECONCILED_PROTOTYPE_DELTA",
            reconciled if needs_reconciliation else True,
            [str(args.delta)] + ([str(args.reconciliation)] if args.reconciliation else []),
            f"SEMANTIC={needs_reconciliation} reconciliationStatus={reconciliation.get('status') if reconciliation else 'MISSING'}",
            owner="prd-agent",
            closeCondition="Create a SYNCED PRD Reconciliation Result for this Prototype Delta.",
        ))
        for change in delta.get("changes", []):
            if change.get("action") != "DELETE":
                continue
            leftover_fr = sorted(set(change.get("linkedFeatureIds", [])) & prd_fr)
            leftover_ac = sorted(set(change.get("linkedAcIds", [])) & prd_ac)
            updated_fr = {item.get("frId") for item in (reconciliation or {}).get("updatedFeatures", []) if item.get("action") in {"DELETE", "MOVE", "NOT_APPLICABLE"}}
            updated_ac = {item.get("acId") for item in (reconciliation or {}).get("updatedAcceptanceCriteria", []) if item.get("action") in {"DELETE", "MOVE", "NOT_APPLICABLE"}}
            synced = all(item in updated_fr for item in leftover_fr) and all(item in updated_ac for item in leftover_ac)
            checks.append(check(
                f"DELTA.DELETE.{change.get('uiElementId')}",
                "DELETED_UI_ELEMENT_STILL_PRESENT_IN_PRD",
                synced if leftover_fr or leftover_ac else True,
                [str(args.delta), str(args.reconciliation) if args.reconciliation else str(args.prd)],
                f"Delta DELETE {change.get('uiElementId')} remaining FR={leftover_fr} AC={leftover_ac} reconciled={synced}",
                uiElementId=change.get("uiElementId"),
                frIds=leftover_fr,
                acIds=leftover_ac,
                owner="prd-agent",
                closeCondition="Delete, migrate, or mark NOT_APPLICABLE the linked PRD FR/AC.",
            ))

    if args.strict_copy:
        for element in manifest.get("elements", []):
            label = element.get("visibleLabel", "")
            if label and label not in prd_text:
                checks.append(check(
                    f"COPY.{element['uiElementId']}",
                    "INCONSISTENT_BUSINESS_COPY",
                    False,
                    [str(args.prd), str(args.manifest)],
                    f"Prototype label {label!r} is absent from PRD.",
                    uiElementId=element["uiElementId"],
                    owner="prd-agent",
                    closeCondition="Align the business copy in PRD and Prototype.",
                ))
    if args.strict_permissions:
        for element in manifest.get("elements", []):
            for permission in element.get("permissions", []):
                if permission not in prd_text:
                    checks.append(check(
                        f"PERMISSION.{element['uiElementId']}.{permission}",
                        "INCONSISTENT_PERMISSION_VISIBILITY",
                        False,
                        [str(args.prd), str(args.manifest)],
                        f"Prototype permission {permission!r} is absent from PRD.",
                        uiElementId=element["uiElementId"],
                        owner="prd-agent",
                        closeCondition="Define the permission/visibility rule in PRD and Prototype.",
                    ))

    failed = [item for item in checks if item["status"] == "failed"]
    result = {
        "schemaVersion": 1,
        "workflowId": pair.get("workflowId"),
        "pairId": pair.get("pairId"),
        "status": "PASS" if not failed else "NEEDS_FIX",
        "blockingCount": len(failed),
        "checks": checks,
        "findings": failed,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "blockingCount": result["blockingCount"], "out": str(args.out)}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
