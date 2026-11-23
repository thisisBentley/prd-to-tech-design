#!/usr/bin/env python3
"""Validate a Project Episode and its provenance hashes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_episode import digest, load
from trust_kernel import validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode", type=Path, required=True)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    episode = load(args.episode.resolve(), {})
    errors = validate_schema_value(episode, "project-episode.schema.json")
    if episode.get("status") == "BLOCKED":
        errors.append("episode status is BLOCKED")
    if (episode.get("trainingEligibility") or {}).get("eligible") is not False:
        errors.append("Project Episode v0 trainingEligibility must remain false")
    if args.verify_source_hashes:
        for item in episode.get("provenance") or []:
            path = Path(str(item.get("path", "")))
            if not path.is_file():
                errors.append(f"source missing: {path}")
            elif digest(path) != item.get("sha256"):
                errors.append(f"source hash drift: {path}")
    report = {
        "schemaVersion": 1,
        "episodeId": episode.get("episodeId"),
        "status": "PASS" if not errors else "BLOCKED",
        "errors": errors,
        "metrics": episode.get("metrics", {}),
        "trainingEligible": (episode.get("trainingEligibility") or {}).get("eligible", None),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
