#!/usr/bin/env python3
"""Create or verify the local/Open-Source shared-file hash baseline."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "versioning" / "version-manifest.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_pairs(local_root: Path, open_root: Path) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for local_path in sorted((local_root / "scripts").glob("*.py")):
        open_path = open_root / "tools" / local_path.name
        if open_path.is_file():
            pairs.append({"local": local_path.relative_to(local_root).as_posix(), "openSource": open_path.relative_to(open_root).as_posix(), "kind": "tool"})
    for local_path in sorted((local_root / "references").glob("*.schema.json")):
        open_path = open_root / "schemas" / local_path.name
        if open_path.is_file():
            pairs.append({"local": local_path.relative_to(local_root).as_posix(), "openSource": open_path.relative_to(open_root).as_posix(), "kind": "schema"})
    for relative_root, kind, suffix in (("config", "config", ""), ("templates", "template", ".md")):
        base = local_root / relative_root
        if not base.is_dir():
            continue
        for local_path in sorted(base.rglob(f"*{suffix}")):
            if not local_path.is_file():
                continue
            relative = local_path.relative_to(local_root).as_posix()
            open_path = open_root / relative
            if open_path.is_file():
                pairs.append({"local": relative, "openSource": relative, "kind": kind})
    mapped_files = [
        ("references/gate-policy-current.json", "core/gate-policy-current.json", "policy"),
        ("references/gate-policy.md", "core/gate-policy.md", "docs"),
        ("references/audit-track.md", "docs/audit-track.md", "docs"),
        ("references/delivery-readiness.md", "docs/delivery-readiness.md", "docs"),
        ("references/semantic-closure-runtime-ac-contract.md", "docs/semantic-closure-runtime-ac-contract.md", "docs"),
        ("references/delivery-control-plane.md", "docs/delivery-control-plane.md", "docs"),
        ("references/finding-ledger.md", "core/finding-ledger.md", "docs"),
        ("references/m4-unified-delivery.md", "docs/m4-unified-delivery.md", "docs"),
        ("references/agent-contract-compiler.md", "docs/agent-contract-compiler.md", "docs"),
        ("references/interaction-contract-v2.md", "docs/interaction-contract-v2.md", "docs"),
        ("references/prototype-change-set-and-scoped-patch.md", "docs/prototype-change-set-and-scoped-patch.md", "docs"),
        ("references/prototype-replay-three-layer-gate.md", "docs/prototype-replay-three-layer-gate.md", "docs"),
        ("references/semantic-convergence.md", "docs/semantic-convergence.md", "docs"),
        ("references/evaluation-integrity.md", "docs/evaluation-integrity.md", "docs"),
        ("references/trust-kernel.md", "docs/trust-kernel.md", "docs"),
        ("references/decision-contract.md", "docs/decision-contract.md", "docs"),
        ("references/submission-contract.md", "docs/submission-contract.md", "docs"),
        ("references/change-sets.md", "docs/change-sets.md", "docs"),
        ("references/bounded-repair.md", "docs/bounded-repair.md", "docs"),
        ("references/consumer-acceptance.md", "docs/consumer-acceptance.md", "docs"),
        ("adapters/external-gates/README.md", "docs/external-gate-adapters.md", "docs"),
    ]
    for local_relative, open_relative, kind in mapped_files:
        if (local_root / local_relative).is_file() and (open_root / open_relative).is_file():
            pairs.append({"local": local_relative, "openSource": open_relative, "kind": kind})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for pair in pairs:
        unique[(pair["local"], pair["openSource"])] = pair
    return [unique[key] for key in sorted(unique)]


def build_baseline(local_root: Path, open_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    files = []
    for pair in discover_pairs(local_root, open_root):
        local_path = local_root / pair["local"]
        open_path = open_root / pair["openSource"]
        files.append({
            **pair,
            "localSha256": digest(local_path),
            "openSourceSha256": digest(open_path),
            "inSync": digest(local_path) == digest(open_path),
        })
    return {
        "schemaVersion": 1,
        "baselineId": manifest["sharedBaseline"]["baselineId"],
        "localSkillVersion": manifest["localSkill"]["version"],
        "openSourceCommit": manifest["openSource"]["commit"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "fileCount": len(files),
        "matchedCount": sum(1 for item in files if item["inSync"]),
        "mismatchCount": sum(1 for item in files if not item["inSync"]),
        "files": files,
    }


def check_baseline(local_root: Path, open_root: Path, manifest: dict[str, Any], baseline: dict[str, Any], allow_commit_change: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    expected_commit = str(manifest["openSource"].get("commit") or "")
    if baseline.get("openSourceCommit") != expected_commit:
        errors.append("baseline openSourceCommit does not match version manifest")
    if allow_commit_change:
        expected_commit = ""
    else:
        head = open_root / ".git" / "HEAD"
        if not head.is_file():
            errors.append("Open-Source repository .git/HEAD is missing")
        else:
            # Resolve a symbolic ref without invoking git.
            head_text = head.read_text(encoding="utf-8").strip()
            resolved = head_text
            if head_text.startswith("ref: "):
                ref_path = open_root / ".git" / head_text.removeprefix("ref: ").strip()
                resolved = ref_path.read_text(encoding="utf-8").strip() if ref_path.is_file() else ""
            if expected_commit and resolved != expected_commit:
                errors.append(f"Open-Source HEAD {resolved or 'UNRESOLVED'} != manifest {expected_commit}")
    file_errors: list[str] = []
    for item in baseline.get("files", []):
        local_path = local_root / item["local"]
        open_path = open_root / item["openSource"]
        if not local_path.is_file():
            file_errors.append(f"local file missing: {item['local']}")
            continue
        if not open_path.is_file():
            file_errors.append(f"Open-Source file missing: {item['openSource']}")
            continue
        local_hash = digest(local_path)
        open_hash = digest(open_path)
        if local_hash != item["localSha256"]:
            file_errors.append(f"local hash drift: {item['local']}")
        if open_hash != item["openSourceSha256"]:
            file_errors.append(f"Open-Source hash drift: {item['openSource']}")
        if local_hash != open_hash:
            file_errors.append(f"local/Open-Source mismatch: {item['local']} <-> {item['openSource']}")
        if item["localSha256"] != item["openSourceSha256"]:
            file_errors.append(f"baseline itself records a mismatched pair: {item['local']}")
    errors.extend(file_errors)
    return {
        "schemaVersion": 1,
        "baselineId": baseline.get("baselineId"),
        "status": "PASS" if not errors else "FAIL",
        "expectedOpenSourceCommit": manifest["openSource"].get("commit"),
        "fileCount": len(baseline.get("files", [])),
        "errors": errors,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-root", type=Path, default=ROOT)
    parser.add_argument("--open-source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--write", action="store_true", help="Write a new shared-file hash baseline.")
    parser.add_argument("--out", type=Path, help="Optional check report path.")
    parser.add_argument("--allow-open-source-commit-change", action="store_true")
    args = parser.parse_args()
    local_root = args.local_root.resolve()
    open_root = args.open_source_root.resolve()
    manifest = load(args.manifest.resolve())
    baseline_path = local_root / manifest["sharedBaseline"]["path"]
    if args.write:
        baseline = build_baseline(local_root, open_root, manifest)
        save(baseline_path, baseline)
        print(json.dumps({"status": "WRITTEN", "baselineId": baseline["baselineId"], "files": baseline["fileCount"], "mismatches": baseline["mismatchCount"], "out": str(baseline_path)}, ensure_ascii=False))
        return 0
    if not baseline_path.is_file():
        print(json.dumps({"status": "FAIL", "error": f"baseline missing: {baseline_path}"}, ensure_ascii=False))
        return 1
    baseline = load(baseline_path)
    report = check_baseline(local_root, open_root, manifest, baseline, args.allow_open_source_commit_change)
    if args.out:
        save(args.out.resolve(), report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
