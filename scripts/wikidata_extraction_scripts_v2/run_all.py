"""Run every wikidata_extraction_scripts_v2/NN_extract_*.py in order.

Usage:
    python wikidata_extraction_scripts_v2/run_all.py --test     # ~1 minute end-to-end
    python wikidata_extraction_scripts_v2/run_all.py            # full extraction (hours)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path


HERE = Path(__file__).resolve().parent

SCRIPTS = [
    # Per-human extracts
    "01_extract_main_info.py",
    "02_extract_places.py",
    "03_extract_occupations.py",
    "04_extract_nationalities.py",
    "05_extract_sitelinks.py",
    "06_extract_catalogs.py",
    "07_extract_works.py",
    "08_extract_writing_languages.py",
    "09_extract_date_precisions.py",
    # Entity-level metadata (must run after the per-human extracts because
    # 14 reads catalog_properties.json produced by 06)
    "10_extract_place_metadata.py",
    "11_extract_nationality_metadata.py",
    "12_extract_occupation_metadata.py",
    "13_extract_modern_countries.py",
    "14_extract_catalog_metadata.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Pass --test to every step (tiny LIMIT 100 sample).")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  wikidata_extraction_scripts_v2/run_all  ({'TEST' if args.test else 'FULL'} mode)")
    print("=" * 70)

    failures: list[str] = []
    t_start = time.time()
    for name in SCRIPTS:
        path = HERE / name
        cmd = [sys.executable, str(path)]
        if args.test:
            cmd.append("--test")
        print(f"\n>>> {' '.join(cmd)}")
        t0 = time.time()
        result = subprocess.run(cmd)
        dt = time.time() - t0
        status = "ok" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
        print(f"<<< {name}: {status} in {dt:.1f}s")
        if result.returncode != 0:
            failures.append(name)

    total = time.time() - t_start
    print("\n" + "=" * 70)
    print(f"  done in {total/60:.1f} min — {len(SCRIPTS) - len(failures)}/{len(SCRIPTS)} ok")
    if failures:
        print(f"  failures: {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
