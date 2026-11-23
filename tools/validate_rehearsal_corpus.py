#!/usr/bin/env python3
"""Validate Rehearsal Corpus boundaries, coverage and source hashes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from rehearsal_corpus import digest, load
from trust_kernel import validate_schema_value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--verify-source-hashes", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    corpus = load(args.corpus.resolve(), {})
    errors = validate_schema_value(corpus, "rehearsal-corpus.schema.json")
    authority = corpus.get("authority") or {}
    if authority.get("releaseEligible") is not False or authority.get("trainingEligible") is not False:
        errors.append("Rehearsal Corpus cannot grant release or training eligibility")
    if authority.get("resultAuthority") != "NONE":
        errors.append("Rehearsal Corpus cannot be a result authority")
    if corpus.get("status") == "BLOCKED":
        errors.append("Rehearsal Corpus status is BLOCKED")
    for scenario in corpus.get("scenarios") or []:
        if scenario.get("replay", {}).get("frozen") is not True:
            errors.append(f"scenario is not frozen: {scenario.get('scenarioId')}")
        forbidden = set(scenario.get("forbiddenOutcomes") or [])
        if not {"RELEASE_EVIDENCE_PROMOTION", "TRAINING_PROMOTION"} <= forbidden:
            errors.append(f"scenario permits release/training promotion: {scenario.get('scenarioId')}")
    if args.verify_source_hashes:
        for item in corpus.get("sources") or []:
            path = Path(str(item.get("path", "")))
            if not path.is_file():
                errors.append(f"source missing: {path}")
            elif digest(path) != item.get("sha256"):
                errors.append(f"source hash drift: {path}")
    report = {
        "schemaVersion": 1,
        "corpusId": corpus.get("corpusId"),
        "status": "PASS" if not errors else "BLOCKED",
        "corpusStatus": corpus.get("status"),
        "errors": errors,
        "metrics": corpus.get("metrics", {}),
    }
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
