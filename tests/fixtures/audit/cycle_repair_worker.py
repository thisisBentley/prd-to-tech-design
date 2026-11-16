#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--bundle", type=Path, required=True)
parser.add_argument("--findings", type=Path, required=True)
parser.add_argument("--revision", required=True)
parser.add_argument("--out", type=Path, required=True)
args = parser.parse_args()
prd = args.bundle / "PRD_DELIVERY.md"
text = prd.read_text(encoding="utf-8")
if "# repaired" not in text:
    prd.write_text(text.rstrip() + "\n\n# repaired\n", encoding="utf-8")
result = {"schemaVersion": 1, "status": "PASS", "revision": args.revision, "changedArtifacts": ["PRD_DELIVERY.md"], "repairedRootCauses": ["F-REPAIR-ME"], "repairTranscript": "cycle fixture repaired PRD"}
args.out.parent.mkdir(parents=True, exist_ok=True)
args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
