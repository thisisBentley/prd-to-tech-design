#!/usr/bin/env python3
"""Collect 1..5 Delivery runs into a P0.5 benchmark and evaluate production eligibility."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from collect_delivery_sample import collect
from evaluate_delivery_quality import evaluate


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    batch_path = args.samples.resolve()
    batch = load(batch_path)
    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    errors: list[str] = []
    for index, spec in enumerate(batch.get("samples", [])):
        try:
            sample = collect(spec, batch_path)
            samples.append(sample)
            sample_path = out_dir / "samples" / f"{sample['sampleId']}.json"
            sample_path.parent.mkdir(parents=True, exist_ok=True)
            sample_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            errors.append(f"samples[{index}] {spec.get('sampleId', 'UNKNOWN')}: {exc}")
    benchmark = {
        "schemaVersion": 1,
        "benchmarkId": batch["benchmarkId"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "dataClassification": batch["dataClassification"],
        "thresholds": batch.get("thresholds") or {},
        "samples": samples,
    }
    benchmark_path = out_dir / "benchmark.json"
    benchmark_path.write_text(json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = evaluate(benchmark, benchmark_path)
    result["collectionErrors"] = errors
    if errors:
        result["status"] = "FAIL"
        result["productionEligible"] = False
        result["blockingCount"] = int(result.get("blockingCount", 0)) + len(errors)
    result_path = out_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = f"""# Delivery Quality Benchmark

- Benchmark: `{batch['benchmarkId']}`
- Classification: `{batch['dataClassification']}`
- Status: `{result['status']}`
- Production eligible: `{str(result['productionEligible']).lower()}`
- Samples: {result['sampleCount']} (production-eligible: {result['productionSampleCount']})
- Finding recall: {result['metrics'].get('findingRecall')}
- False-positive rate: {result['metrics'].get('falsePositiveRate')}
- Replay consistency: {result['metrics'].get('replayConsistency')}
- Collection errors: {len(errors)}

The result is production eligible only when the dataset is REAL, 3..5 real samples are eligible, and every benchmark check passes.
"""
    (out_dir / "REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps({"status": result["status"], "productionEligible": result["productionEligible"], "samples": len(samples), "errors": len(errors), "out": str(result_path)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
