"""Independent validator for generated MarketGenesis v2 artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


OUTPUT_DIR = Path(__file__).resolve().parent
ROOT = OUTPUT_DIR.parent
sys.path.insert(0, str(ROOT / "code"))

from marketgenesis_v2 import json_ready, validate_existing  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_DIR,
                        help="Artifact directory to validate (default: public reference)")
    parser.add_argument("--write-report", action="store_true",
                        help="Also replace validation_report.json; default is read-only")
    args = parser.parse_args()
    report = validate_existing(args.output)
    if args.write_report:
        (args.output / "validation_report.json").write_text(
            json.dumps(json_ready(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(json_ready(report), ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
