"""End-to-end test: build a tiny SQLite from the v2 Wikidata `.test.json`
files, then verify schema & basic row counts.

What it does
------------
1. Confirms the legacy `data/humans_clean.sqlite3` is **never** opened.
2. Runs each of the 12 build scripts in order, pointing every JSON path
   at the corresponding `*.test.json` produced by
   `scripts/wikidata_extraction_scripts_v2/run_all.py --test`.
3. Writes everything into `data/humans_v2.sample.sqlite3` (overwritten on
   each run, so you can re-test repeatedly).
4. Asserts each table exists and has at least one row (where applicable).

Usage
-----
    # First populate the test JSONs:
    python scripts/wikidata_extraction_scripts_v2/run_all.py --test

    # Then run this:
    python scripts/database_integration_scripts_V2/test_end_to_end.py
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import (
    LEGACY_DB_PATH,
    SAMPLE_DB_PATH,
    WIKIDATA_V2_DIR,
    log,
    open_db,
    row_count,
)

# JSON file overrides — point each build script at *.test.json.
J = WIKIDATA_V2_DIR
TEST_INPUTS = {
    "01_create_modern_country": {"json_path": J / "modern_countries.test.json"},
    "02_create_cities":         {"json_path": J / "place_metadata.test.json"},
    "03_create_nationalities":  {"meta_path": J / "nationality_metadata.test.json",
                                 "label_path": J / "nationality_labels.test.json"},
    "04_create_occupations":    {"label_path": J / "occupation_labels.test.json",
                                 "meta_path": J / "occupation_metadata.test.json"},
    "05_create_writing_languages": {"label_path": J / "writing_language_labels.test.json"},
    "06_create_identifier_types": {"props_path": J / "catalog_properties.json",  # full-mode artefact (no .test variant)
                                   "meta_path":  J / "catalog_metadata.test.json"},
    "07_create_individuals": {
        "main_info_path":              J / "main_info.test.json",
        "places_path":                 J / "places.test.json",
        "precisions_path":             J / "date_precisions.test.json",
        "occupations_path":            J / "occupations.test.json",
        "nationalities_path":          J / "nationalities.test.json",
        "sitelinks_path":              J / "sitelinks.test.json",
        "catalogs_path":               J / "catalogs.test.json",
        "works_path":                  J / "works.test.json",
        "writing_languages_path":      J / "writing_languages.test.json",
        "writing_language_labels_path": J / "writing_language_labels.test.json",
    },
    "08_create_identifiers":   {"catalogs_path": J / "catalogs.test.json"},
    "09_create_sitelinks":     {"json_path": J / "sitelinks.test.json"},
    "10_create_works":         {"works_path": J / "works.test.json",
                                "labels_path": J / "work_labels.test.json"},
    "11_create_individual_writing_languages": {"json_path": J / "writing_languages.test.json"},
    "12_create_individuals_floruit": {"main_path": J / "main_info.test.json",
                                      "prec_path": J / "date_precisions.test.json"},
}

ORDER = [
    "01_create_modern_country",
    "02_create_cities",
    "03_create_nationalities",
    "04_create_occupations",
    "05_create_writing_languages",
    "06_create_identifier_types",
    "07_create_individuals",
    "08_create_identifiers",
    "09_create_sitelinks",
    "10_create_works",
    "11_create_individual_writing_languages",
    "12_create_individuals_floruit",
]

# Tables we expect to exist after the build, with a minimum row threshold.
EXPECTED = {
    "modern_country":                1,
    "cities":                        1,
    "nationalities":                 1,
    "occupations":                   1,
    "writing_languages":             1,
    "identifier_types":              1,
    "individuals":                   1,
    "identifiers":                   0,  # may be 0 if test data lacks IDs
    "sitelinks":                     1,
    "works":                         0,  # works.test.json: only P50 in test mode
    "individual_writing_languages":  0,
    "individuals_floruit":           0,  # not all test humans have P1317
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    log("=" * 70)
    log("  V2 integration end-to-end test")
    log("=" * 70)

    # 1. legacy DB protection
    legacy_mtime_before = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None
    log(f"[guard] legacy DB {LEGACY_DB_PATH} (mtime before: {legacy_mtime_before})")

    # 2. fresh sample DB
    if SAMPLE_DB_PATH.exists():
        SAMPLE_DB_PATH.unlink()
    for ext in ("-wal", "-shm"):
        side = Path(str(SAMPLE_DB_PATH) + ext)
        if side.exists():
            side.unlink()
    log(f"[setup] writing to fresh {SAMPLE_DB_PATH}")

    # 3. check inputs are present.
    # We only fail on missing *.test.json files — full-mode-only artefacts
    # (e.g. catalog_properties.json) are optional; the build scripts skip
    # them if absent.
    missing = []
    for name, paths in TEST_INPUTS.items():
        for arg, path in paths.items():
            if not path.exists() and path.name.endswith(".test.json"):
                missing.append(f"{name}.{arg}: {path}")
    if missing:
        log("[ERROR] missing test inputs — run the v2 extraction with --test first:")
        for m in missing:
            log(f"        {m}")
        log("\n  python scripts/wikidata_extraction_scripts_v2/run_all.py --test")
        return 1

    # 4. run each script
    with open_db(SAMPLE_DB_PATH) as conn:
        for name in ORDER:
            log(f"\n>>> {name}.run(conn, ...)")
            mod = _load(name)
            mod.run(conn, **TEST_INPUTS[name])

    # 5. assertions
    log("\n=== row count check ===")
    failures = []
    with sqlite3.connect(SAMPLE_DB_PATH) as conn:
        for table, min_rows in EXPECTED.items():
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not row:
                failures.append(f"  table missing: {table}")
                continue
            n = row_count(conn, table)
            ok = n >= min_rows
            log(f"  {table:34s} rows={n:>6}  (min {min_rows})  {'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"  {table}: {n} < {min_rows}")

    # 6. legacy DB integrity
    legacy_mtime_after = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None
    if legacy_mtime_before != legacy_mtime_after:
        failures.append(
            f"  legacy DB {LEGACY_DB_PATH} mtime changed: "
            f"{legacy_mtime_before} -> {legacy_mtime_after}"
        )
    else:
        log(f"\n[guard] legacy DB untouched (mtime unchanged)")

    if failures:
        log("\nFAILED:")
        for f in failures:
            log(f)
        return 1

    log(f"\nOK — sample DB at {SAMPLE_DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
