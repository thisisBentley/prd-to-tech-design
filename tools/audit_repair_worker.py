#!/usr/bin/env python3
"""Codex adapter for one bounded Audit finding repair cycle."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--findings", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--codex", default=shutil.which("codex") or "codex")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=300)
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    findings_path = args.findings.resolve()
    out_path = args.out.resolve()
    _ = load(findings_path)
    prompt = "\n".join([
        "You are an independent Audit Repair Agent.",
        "Repair the active candidate artifacts in the supplied bundle according to the frozen Audit findings.",
        "Read the findings first. Preserve all business facts that are not implicated by a finding.",
        "Do not modify .delivery/candidate-revisions, .delivery/candidate-seal.json or .delivery/final-seal.json.",
        "Modify only the active candidate artifacts under the bundle root.",
        "Return exactly one JSON object with schemaVersion=1, status=PASS or BLOCKED, revision, changedArtifacts, repairedRootCauses, and repairTranscript.",
        "status=PASS requires at least one changedArtifacts path. If the finding cannot be repaired safely, return BLOCKED with errors.",
        f"AI_NATIVE_BUNDLE={bundle}",
        f"AI_NATIVE_FINDINGS={findings_path}",
        f"AI_NATIVE_TARGET_REVISION={args.revision}",
        f"AI_NATIVE_RESULT_PATH={out_path}",
    ])
    argv = [args.codex, "exec", "--ephemeral", "--skip-git-repo-check", "--ignore-rules", "--sandbox", "workspace-write", "--output-last-message", str(out_path), "-C", str(bundle)]
    if args.model:
        argv += ["--model", args.model]
    argv.append(prompt)
    try:
        process = subprocess.run(argv, cwd=bundle, text=True, capture_output=True, timeout=args.timeout, check=False)
    except Exception as exc:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"schemaVersion": 1, "status": "BLOCKED", "revision": args.revision, "changedArtifacts": [], "repairedRootCauses": [], "errors": [str(exc)], "repairTranscript": ""}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 1
    transcript_path = out_path.with_suffix(".log")
    transcript_path.write_text((process.stdout or "") + (process.stderr or ""), encoding="utf-8")
    if process.returncode != 0:
        return process.returncode
    try:
        result = load(out_path)
    except Exception:
        return 2
    result.setdefault("checkedAt", now())
    result.setdefault("repairTranscript", str(transcript_path))
    result["revision"] = args.revision
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("status") == "PASS" and result.get("changedArtifacts") else 1


if __name__ == "__main__":
    raise SystemExit(main())
