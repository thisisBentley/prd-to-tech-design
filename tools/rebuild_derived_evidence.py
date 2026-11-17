#!/usr/bin/env python3
"""Rebuild one candidate revision's derived evidence against its own frozen artifacts.

The tool is intentionally conservative: it copies the source candidate to a new
revision, rewrites only evidence references whose target artifacts exist, and
fails if any active evidence still points at another revision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REVISION_KEYS = {"revision", "targetRevision", "candidateRevision", "prototypeRevision", "prdRevision", "overviewRevision"}
PRESERVED_REVISION_KEYS = {"sourceRevision"}
HISTORICAL_PREFIXES = ("historical", "archived", "superseded")
CANDIDATE_RE = re.compile(r"candidate-revisions[/\\](r\d+)[/\\]([^#]+)(#L\d+(?:-L\d+)?)?$")
RUNTIME_RE = re.compile(r"runtime-evidence[/\\](r\d+)[/\\]([^#]+)(#L\d+(?:-L\d+)?)?$")
FRAGMENT_RE = re.compile(r"#L(\d+)(?:-L(\d+))?$")
EXCLUDED_FROM_SEAL = {
    ".delivery/bundle.json",
    ".delivery/candidate-seal.json",
    ".delivery/policy-lock.json",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_fragment(value: str) -> tuple[str, str]:
    if "#" not in value:
        return value, ""
    path, fragment = value.rsplit("#", 1)
    return path, f"#{fragment}"


def map_fragment(old_path: Path, new_path: Path, fragment: str) -> tuple[str, bool]:
    match = FRAGMENT_RE.fullmatch(fragment)
    if not match or not old_path.is_file() or not new_path.is_file():
        return fragment, True
    start = int(match.group(1))
    end = int(match.group(2) or start)
    old_lines = old_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = new_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if start < 1 or end < start or end > len(old_lines):
        return fragment, False
    needle = [line.strip() for line in old_lines[start - 1:end] if line.strip()]
    if not needle:
        return fragment, False
    candidates: list[tuple[int, int]] = []
    width = end - start + 1
    for index in range(0, max(0, len(new_lines) - width + 1)):
        window = [line.strip() for line in new_lines[index:index + width] if line.strip()]
        if window == needle:
            candidates.append((index + 1, index + width))
    if len(candidates) == 1:
        new_start, new_end = candidates[0]
        return f"#L{new_start}" if new_start == new_end else f"#L{new_start}-L{new_end}", True

    # Content changed between revisions; map through a stable structural anchor
    # while preserving the original range width.
    width = end - start + 1
    for pattern in (r'data-ai-id="[^"]+"', r'\bid="[^"]+"', r'\bclass="[^"]+"'):
        for offset, line in enumerate(old_lines[start - 1:end]):
            anchor = re.search(pattern, line)
            if not anchor:
                continue
            matches = [index for index, target_line in enumerate(new_lines) if anchor.group(0) in target_line]
            if len(matches) == 1:
                new_start = matches[0] + 1 - offset
                new_end = new_start + width - 1
                if new_start >= 1 and new_end <= len(new_lines):
                    return f"#L{new_start}" if new_start == new_end else f"#L{new_start}-L{new_end}", True
    for offset, line in enumerate(old_lines[start - 1:end]):
        needle_line = line.strip()
        if len(needle_line) < 12:
            continue
        matches = [index for index, target_line in enumerate(new_lines) if target_line.strip() == needle_line]
        if len(matches) == 1:
            new_start = matches[0] + 1 - offset
            new_end = new_start + width - 1
            if new_start >= 1 and new_end <= len(new_lines):
                return f"#L{new_start}" if new_start == new_end else f"#L{new_start}-L{new_end}", True
    return fragment, False


def rewrite_reference(value: str, source_root: Path, target_root: Path, source_revision: str, target_revision: str) -> tuple[str, bool, str | None]:
    path_text, fragment = split_fragment(value)
    normalized = path_text.replace("\\", "/")
    replacement: Path | None = None
    old_path: Path | None = None

    candidate_match = CANDIDATE_RE.search(normalized)
    if candidate_match:
        old_revision = candidate_match.group(1)
        relative = candidate_match.group(2)
        relative = re.sub(r"(\.delivery/runtime-evidence/)r\d+/", rf"\1{target_revision}/", relative)
        old_path = source_root.parent / old_revision / relative
        candidate = target_root / relative
        if candidate.exists():
            replacement = candidate
    else:
        runtime_match = RUNTIME_RE.search(normalized)
        if runtime_match:
            relative = runtime_match.group(2)
            old_path = source_root / ".delivery" / "runtime-evidence" / source_revision / relative
            candidate = target_root / ".delivery" / "runtime-evidence" / target_revision / relative
            if candidate.exists():
                replacement = candidate
        elif "browser-evidence" in normalized:
            basename = Path(normalized).name
            candidate = target_root / ".delivery" / "runtime-evidence" / target_revision / basename
            if candidate.exists():
                replacement = candidate
                old_path = Path(normalized)

    if replacement is None:
        return value, True, None
    if fragment:
        new_fragment, ok = map_fragment(old_path, replacement, fragment)
        if not ok:
            return value, False, f"line fragment could not be mapped: {fragment}"
        fragment = new_fragment
    return str(replacement.resolve()) + fragment, True, None


def rewrite_payload(value: Any, source_root: Path, target_root: Path, source_revision: str, target_revision: str, field: str = "$", unresolved: list[dict[str, str]] | None = None, evidence_file: str = "") -> Any:
    if unresolved is None:
        unresolved = []
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            child = f"{field}.{key_text}"
            if key_text in PRESERVED_REVISION_KEYS or key_text.startswith(HISTORICAL_PREFIXES):
                result[key] = item
                continue
            rewritten = rewrite_payload(item, source_root, target_root, source_revision, target_revision, child, unresolved, evidence_file)
            if key_text in REVISION_KEYS and isinstance(rewritten, str) and re.fullmatch(r"r\d+", rewritten):
                rewritten = target_revision
            elif key_text == "bundleId" and isinstance(rewritten, str):
                rewritten = re.sub(r"-r\d+$", f"-{target_revision}", rewritten)
            elif key_text == "frozenCopy" and isinstance(rewritten, str):
                rewritten = f".delivery/candidate-revisions/{target_revision}"
            elif key_text == "targetHandoffId" and isinstance(rewritten, str):
                rewritten = re.sub(r"-r\d+$", f"-{target_revision}", rewritten)
            result[key] = rewritten
        return result
    if isinstance(value, list):
        return [rewrite_payload(item, source_root, target_root, source_revision, target_revision, f"{field}[{index}]", unresolved, evidence_file) for index, item in enumerate(value)]
    if isinstance(value, str):
        rewritten, valid, reason = rewrite_reference(value, source_root, target_root, source_revision, target_revision)
        if not valid and reason:
            unresolved.append({"file": evidence_file, "field": field, "value": value, "reason": reason})
        return rewritten
    return value


def scan_stale(target_root: Path, revision: str) -> tuple[list[str], list[dict[str, str]]]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_delivery_bundle_integrity import active_evidence_files, stale_revision_refs
    dd = target_root / ".delivery"
    files = active_evidence_files(dd, revision, None)
    findings: list[dict[str, str]] = []
    for path in files:
        try:
            payload = load(path)
        except Exception as exc:
            findings.append({"file": str(path), "field": "$", "value": "", "reason": f"invalid JSON: {exc}"})
            continue
        for item in stale_revision_refs(payload, revision):
            findings.append({"file": str(path), **item})
    return [str(path) for path in files], findings


def candidate_seal_files(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in EXCLUDED_FROM_SEAL or relative.startswith(".delivery/reviews/candidate-"):
            continue
        hashes[relative] = sha256(path)
    return hashes


def rebuild(bundle: Path, source_revision: str, target_revision: str, manifest_out: Path, force: bool = False) -> dict[str, Any]:
    dd = bundle / ".delivery"
    source_root = dd / "candidate-revisions" / source_revision
    target_root = dd / "candidate-revisions" / target_revision
    if not source_root.is_dir():
        return {"schemaVersion": 1, "rebuildId": f"derived-{source_revision}-{target_revision}", "workflowId": "UNKNOWN", "sourceRevision": source_revision, "targetRevision": target_revision, "status": "BLOCKED", "sourceRoot": str(source_root), "targetRoot": str(target_root), "rebuiltArtifacts": [], "archivedArtifacts": [], "unresolvedEvidenceRefs": [{"file": str(source_root), "field": "$", "value": "", "reason": "source revision missing"}], "activeEvidenceScan": {"checkedFiles": 0, "staleFindingCount": 0, "findings": []}, "generatedAt": now()}
    if target_root.exists():
        if not force:
            raise SystemExit(f"target revision already exists: {target_root}")
        shutil.rmtree(target_root)

    source_seal = load(source_root / ".delivery" / "candidate-seal.json")
    workflow_id = str(source_seal.get("workflowId") or load(dd / "state.json").get("workflowId") or "UNKNOWN")
    shutil.copytree(source_root, target_root)

    old_runtime = target_root / ".delivery" / "runtime-evidence" / source_revision
    new_runtime = target_root / ".delivery" / "runtime-evidence" / target_revision
    if old_runtime.is_dir() and not new_runtime.exists():
        old_runtime.rename(new_runtime)

    unresolved: list[dict[str, str]] = []
    rebuilt: list[dict[str, str]] = []
    for path in sorted(target_root.rglob("*.json")):
        if "archive" in path.parts:
            continue
        original = load(path)
        rewritten = rewrite_payload(original, source_root, target_root, source_revision, target_revision, unresolved=unresolved, evidence_file=str(path))
        if rewritten != original:
            save(path, rewritten)
            rebuilt.append({"path": path.relative_to(target_root).as_posix(), "sha256": sha256(path), "operation": "rewrite_revision_refs"})

    # Consumer artifacts and deterministic review projections are deliverables too.
    # Replace standalone revision tokens and frozen source paths without touching binary bytes.
    consumer_rebind: list[dict[str, str]] = []
    text_suffixes = {".md", ".html", ".htm", ".csv", ".xml", ".txt", ".log", ".yaml", ".yml"}
    source_path_text = str(source_root.resolve())
    target_path_text = str(target_root.resolve())
    for path in sorted(target_root.rglob("*")):
        relative_parts = path.relative_to(target_root).parts if path != target_root else ()
        if not path.is_file() or "archive" in relative_parts or ".delivery" in relative_parts:
            continue
        suffix = path.suffix.lower()
        kind = "XMind" if suffix == ".xmind" else ("TEST_PLAN" if "测试方案" in path.name or "test-plan" in path.name.lower() else ("TECH_SOLUTION" if "技术方案" in path.name or "tech-solution" in path.name.lower() else "CONSUMER_ARTIFACT"))
        operation = "UNCHANGED"
        if suffix in text_suffixes:
            text = path.read_text(encoding="utf-8", errors="replace")
            rewritten_text = text.replace(source_path_text, target_path_text)
            rewritten_text = re.sub(rf"\b{re.escape(source_revision)}\b", target_revision, rewritten_text)
            if rewritten_text != text:
                path.write_text(rewritten_text, encoding="utf-8")
                operation = "REWRITE_TEXT_REFS"
        elif suffix == ".xmind" and zipfile.is_zipfile(path):
            rewritten = False
            entries: list[tuple[zipfile.ZipInfo, bytes]] = []
            with zipfile.ZipFile(path, "r") as archive:
                for info in archive.infolist():
                    data = archive.read(info.filename)
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        entries.append((info, data)); continue
                    updated = text.replace(source_path_text, target_path_text)
                    updated = re.sub(rf"\b{re.escape(source_revision)}\b", target_revision, updated)
                    entries.append((info, updated.encode("utf-8")))
                    rewritten = rewritten or updated != text
            if rewritten:
                temp_zip = path.with_suffix(path.suffix + ".tmp")
                with zipfile.ZipFile(temp_zip, "w") as archive:
                    for info, data in entries:
                        archive.writestr(info, data)
                temp_zip.replace(path)
                operation = "REWRITE_XMIND_REFS"
        if operation != "UNCHANGED":
            rebuilt.append({"path": path.relative_to(target_root).as_posix(), "sha256": sha256(path), "operation": operation})
            consumer_rebind.append({"path": path.relative_to(target_root).as_posix(), "kind": kind, "operation": operation, "sha256": sha256(path)})

    # Recompute hashes that directly bind rebuilt artifacts. These are derived
    # values, not business facts. Full artifact-quality and consistency reviews
    # still run in formal review.
    semantic_input = target_root / ".delivery" / "semantic-consistency-input.json"
    if semantic_input.is_file():
        semantic_payload = load(semantic_input)
        for artifact in semantic_payload.get("artifacts", []):
            artifact_path = Path(str(artifact.get("path", "")))
            if artifact_path.is_file():
                artifact["sha256"] = sha256(artifact_path)
        save(semantic_input, semantic_payload)

    artifact_pair = target_root / ".delivery" / "artifact-pair.json"
    if artifact_pair.is_file():
        pair = load(artifact_pair)
        for path_key, hash_key in (("prdPath", "prdHash"), ("prototypePath", "prototypeHash"), ("overviewPath", "overviewHash")):
            value = pair.get(path_key)
            if value:
                path = Path(str(value))
                if path.is_file():
                    pair[hash_key] = sha256(path)
        pair["updatedAt"] = now()
        save(artifact_pair, pair)

    semantic_review = target_root / ".delivery" / "semantic-consistency-review.json"
    transcript = target_root / ".delivery" / "semantic-review-transcript.log"
    if semantic_input.is_file():
        review_tool = Path(__file__).resolve().parent / "semantic_consistency_review.py"
        semantic_review.parent.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable, str(review_tool), "--input", str(semantic_input), "--out", str(semantic_review),
            "--transcript", str(transcript), "--review-plan-id", f"derived-semantic-{target_revision}",
            "--target-handoff-id", f"{workflow_id}-delivery-{target_revision}",
        ]
        process = subprocess.run(command, text=True, capture_output=True, cwd=str(bundle))
        if process.returncode != 0:
            unresolved.append({"file": str(semantic_input), "field": "$", "value": "", "reason": f"semantic review regeneration failed: {process.stdout} {process.stderr}"})
        else:
            rebuilt.append({"path": semantic_review.relative_to(target_root).as_posix(), "sha256": sha256(semantic_review), "operation": "regenerate_semantic_review"})
            if transcript.is_file():
                rebuilt.append({"path": transcript.relative_to(target_root).as_posix(), "sha256": sha256(transcript), "operation": "regenerate_semantic_transcript"})

    checked_files, stale = scan_stale(target_root, target_revision)
    seal_hashes = candidate_seal_files(target_root)
    target_seal = {
        "schemaVersion": 1,
        "bundleId": f"{workflow_id}-{target_revision}",
        "workflowId": workflow_id,
        "revision": target_revision,
        "status": "CANDIDATE_SEALED",
        "frozenCopy": f".delivery/candidate-revisions/{target_revision}",
        "prototypeStatus": source_seal.get("prototypeStatus"),
        "artifactProfile": source_seal.get("artifactProfile"),
        "artifactHashes": seal_hashes,
        "rebuildSourceRevision": source_revision,
        "createdAt": now(),
    }
    save(target_root / ".delivery" / "candidate-seal.json", target_seal)

    bundle_payload = load(target_root / ".delivery" / "bundle.json") if (target_root / ".delivery" / "bundle.json").is_file() else {}
    bundle_payload.update({
        "status": "CANDIDATE_SEALED",
        "revision": target_revision,
        "candidateRevision": target_revision,
        "bundleId": target_seal["bundleId"],
        "candidateSeal": str((bundle / target_seal["frozenCopy"] / ".delivery" / "candidate-seal.json")),
        "rebuildSourceRevision": source_revision,
    })
    for key in ("finalRevision", "finalSeal", "reviewEvidence", "reviewRunId"):
        bundle_payload.pop(key, None)
    save(target_root / ".delivery" / "bundle.json", bundle_payload)

    status = "PASS" if not unresolved and not stale else "BLOCKED"
    manifest = {
        "schemaVersion": 1,
        "rebuildId": f"derived-{workflow_id}-{source_revision}-{target_revision}",
        "workflowId": workflow_id,
        "sourceRevision": source_revision,
        "targetRevision": target_revision,
        "status": status,
        "sourceRoot": str(source_root),
        "targetRoot": str(target_root),
        "rebuiltArtifacts": rebuilt,
        "archivedArtifacts": [],
        "consumerRebind": consumer_rebind,
        "unresolvedEvidenceRefs": unresolved,
        "activeEvidenceScan": {"checkedFiles": len(checked_files), "staleFindingCount": len(stale), "findings": stale[:100]},
        "candidateSealPath": str(target_root / ".delivery" / "candidate-seal.json"),
        "candidateSealSha256": sha256(target_root / ".delivery" / "candidate-seal.json"),
        "generatedAt": now(),
    }
    save(manifest_out, manifest)
    return manifest


def activate(bundle: Path, target_revision: str, manifest: dict[str, Any]) -> dict[str, Any]:
    """Promote a clean rebuilt candidate into the active delivery evidence root.

    The prior active evidence and final seal are archived, not deleted. Activation
    intentionally removes the old final seal: changed evidence invalidates the
    prior final review and requires a new formal review cycle.
    """
    dd = bundle / ".delivery"
    target_root = dd / "candidate-revisions" / target_revision
    target_dd = target_root / ".delivery"
    if manifest.get("status") != "PASS":
        raise SystemExit("cannot activate a blocked derived rebuild")
    archive_dir = dd / "archive" / f"pre-{target_revision}-activation-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archived: list[dict[str, str]] = []
    for path in sorted(dd.glob("*.json")):
        destination = archive_dir / path.name
        shutil.copy2(path, destination)
        archived.append({"sourcePath": path.relative_to(bundle).as_posix(), "archivePath": destination.relative_to(bundle).as_posix(), "reason": "superseded by derived evidence rebuild"})
        path.unlink()

    # Copy the rebuilt candidate (main artifacts plus derived evidence) into the
    # active root. Existing historical review and runtime directories stay in
    # place as immutable history.
    for path in sorted(target_root.rglob("*")):
        if not path.is_file():
            continue
        destination = bundle / path.relative_to(target_root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)

    seal = load(dd / "candidate-seal.json")
    workflow_id = str(seal.get("workflowId") or manifest.get("workflowId") or "UNKNOWN")
    state = {
        "schemaVersion": 1,
        "workflowId": workflow_id,
        "phase2": {
            "status": "CANDIDATE_SEALED",
            "revision": target_revision,
            "candidateRevision": target_revision,
            "bundleId": seal.get("bundleId"),
            "candidateSeal": "01-delivery/.delivery/candidate-seal.json",
            "openBlockingCount": 0,
            "openFindingBlockingCount": 0,
        },
    }
    save(dd / "state.json", state)
    manifest["archivedArtifacts"] = archived
    manifest["activation"] = {
        "activeRevision": target_revision,
        "activeCandidateSeal": str(dd / "candidate-seal.json"),
        "priorFinalSealArchived": any(item["sourcePath"].endswith("/final-seal.json") for item in archived) or any((dd / "archive").glob("pre-*-activation*/final-seal.json")),
        "formalReviewRequired": True,
    }
    save(Path(manifest["manifestPath"]), manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--target-revision", required=True)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--activate", action="store_true", help="Promote the rebuilt candidate into the active evidence root and archive the prior final seal.")
    args = parser.parse_args()
    manifest = rebuild(args.bundle.resolve(), args.source_revision, args.target_revision, args.manifest_out.resolve(), args.force)
    manifest["manifestPath"] = str(args.manifest_out.resolve())
    save(args.manifest_out.resolve(), manifest)
    if args.activate and manifest["status"] == "PASS":
        manifest = activate(args.bundle.resolve(), args.target_revision, manifest)
    print(json.dumps({"status": manifest["status"], "targetRevision": manifest["targetRevision"], "rebuilt": len(manifest["rebuiltArtifacts"]), "unresolved": len(manifest["unresolvedEvidenceRefs"]), "stale": manifest["activeEvidenceScan"]["staleFindingCount"], "activated": bool(args.activate and manifest["status"] == "PASS"), "manifest": str(args.manifest_out.resolve())}, ensure_ascii=False))
    return 0 if manifest["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
