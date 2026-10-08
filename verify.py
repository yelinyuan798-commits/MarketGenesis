"""Read-only integrity and numerical comparison of MarketGenesis artifacts.

Run after installing requirements.txt. No simulation is performed by this script.
Use --reproduced after reproduce.py and --multiseed after robustness_reproduce.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "code"))

from marketgenesis_v2 import validate_existing  # noqa: E402


RTOL = 1e-10
ATOL = 1e-12


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_manifest(directory: Path) -> None:
    manifest = directory / "data" / "artifact_hashes.sha256"
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise AssertionError(f"Empty manifest: {manifest}")
    for line in lines:
        expected, relative = line.split("  ", 1)
        artifact = (directory / relative).resolve()
        if not artifact.is_relative_to(directory.resolve()):
            raise AssertionError(f"Manifest path leaves artifact directory: {relative}")
        actual = sha256(artifact)
        if actual != expected:
            raise AssertionError(f"SHA-256 mismatch: {directory.name}/{relative}")
    print(f"PASS | {directory.name} manifest | {len(lines)}/{len(lines)} SHA-256 hashes")


def compare_json(expected: object, actual: object, location: str) -> None:
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        equal = type(actual) is type(expected) and actual == expected
    elif isinstance(expected, int):
        equal = type(actual) is int and actual == expected
    elif isinstance(expected, float):
        equal = (
            isinstance(actual, (int, float))
            and not isinstance(actual, bool)
            and math.isclose(expected, actual, rel_tol=RTOL, abs_tol=ATOL)
        )
    elif isinstance(expected, dict):
        if not isinstance(actual, dict) or expected.keys() != actual.keys():
            raise AssertionError(f"JSON keys differ: {location}")
        for key in expected:
            compare_json(expected[key], actual[key], f"{location}.{key}")
        return
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            raise AssertionError(f"JSON list shape differs: {location}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            compare_json(left, right, f"{location}[{index}]")
        return
    else:
        raise TypeError(f"Unexpected JSON value: {location}")
    if not equal:
        raise AssertionError(f"JSON value differs: {location}: {expected!r} != {actual!r}")


def compare_data(reference: Path, reproduced: Path) -> None:
    reference_files = {path.name for path in (reference / "data").iterdir()
                       if path.suffix in {".csv", ".json"}}
    reproduced_files = {path.name for path in (reproduced / "data").iterdir()
                        if path.suffix in {".csv", ".json"}}
    if reference_files != reproduced_files:
        raise AssertionError(f"Data file sets differ: {reference.name}, {reproduced.name}")
    exact = 0
    for name in sorted(reference_files):
        left, right = reference / "data" / name, reproduced / "data" / name
        exact += int(sha256(left) == sha256(right))
        if left.suffix == ".csv":
            pd.testing.assert_frame_equal(
                pd.read_csv(left), pd.read_csv(right), check_exact=False,
                rtol=RTOL, atol=ATOL, obj=name,
            )
        else:
            compare_json(json.loads(left.read_text(encoding="utf-8")),
                         json.loads(right.read_text(encoding="utf-8")), name)
    print(f"PASS | {reproduced.name} vs {reference.name} | "
          f"{len(reference_files)} data files numerically equivalent "
          f"(rtol={RTOL:g}, atol={ATOL:g}); {exact}/{len(reference_files)} byte-identical")


def verify_fixed(directory: Path) -> None:
    report = validate_existing(directory)
    if not report["passed"]:
        raise AssertionError(f"Fixed-seed invariants failed: {directory.name}: {report}")
    print(f"PASS | {directory.name} | {len(report['checks'])} recomputed integrity checks")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reproduced", action="store_true",
                        help="Also verify reproduced/ and compare its data with reference/")
    parser.add_argument("--multiseed", action="store_true",
                        help="Also verify robustness_reproduced/ against reference_robustness/")
    args = parser.parse_args()
    for name in ("reference", "reference_robustness"):
        verify_manifest(ROOT / name)
    verify_fixed(ROOT / "reference")
    if args.reproduced:
        output = ROOT / "reproduced"
        verify_manifest(output)
        verify_fixed(output)
        compare_data(ROOT / "reference", output)
    if args.multiseed:
        output = ROOT / "robustness_reproduced"
        verify_manifest(output)
        compare_data(ROOT / "reference_robustness", output)
        validation = json.loads((output / "validation_report.json").read_text(encoding="utf-8"))
        report = json.loads((output / "data" / "multiseed_report.json").read_text(encoding="utf-8"))
        if not validation["passed"] or not report["passed_all_predeclared_gates"]:
            raise AssertionError("Multi-seed pipeline checks or scientific gates failed")
        print(f"PASS | multi-seed saved run reports | {len(validation['checks'])} integrity checks; "
              f"{len(report['predeclared_gates'])} scientific gates")
    print("Figures are integrity-checked within each artifact set; cross-platform font pixels are not compared.")


if __name__ == "__main__":
    main()
