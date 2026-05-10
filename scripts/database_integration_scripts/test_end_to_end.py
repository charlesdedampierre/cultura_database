"""End-to-end test: build a tiny DuckDB from the v2 `.test.json` files,
then verify schema & basic row counts.

What it does
------------
1. Confirms the canonical `data/humans_clean.duckdb` is **never** opened.
2. Runs each of the 10 build scripts in order, pointing every JSON path
   at the corresponding `*.test.json` produced by
   `scripts/wikidata_extraction_scripts_v2/run_all.py --test`.
3. Writes everything into `data/humans_v2.sample.duckdb` (overwritten on
   each run, so you can re-test repeatedly).
4. Asserts each table exists and has at least one row (where applicable).

Usage
-----
    # First populate the test JSONs:
    python scripts/wikidata_extraction_scripts/run_all.py --test

    # Then run this:
    python scripts/database_integration_scripts/test_end_to_end.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import (
    LEGACY_DB_PATH,
    SAMPLE_DB_PATH,
    WIKIDATA_TEST_DIR,
    log,
    open_db,
    row_count,
    table_exists,
)

J = WIKIDATA_TEST_DIR
TEST_INPUTS = {
    "02_create_places":         {"json_path": J / "place_metadata.test.json",
                                 "countries_path": J / "modern_countries.test.json"},
    "03_create_country_of_citizenship": {
        "meta_path":  J / "nationality_metadata.test.json",
        "label_path": J / "nationality_labels.test.json",
    },
    "04_create_occupations":    {"label_path": J / "occupation_labels.test.json",
                                 "meta_path": J / "occupation_metadata.test.json"},
    "05_create_writing_languages": {"label_path": J / "writing_language_labels.test.json"},
    "06_create_identifier_types": {"props_path": J / "catalog_properties.json",
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
    "09_create_wikimedia_links":  {"json_path": J / "sitelinks.test.json"},
    "10_create_works":         {"works_path": J / "works.test.json",
                                "labels_path": J / "work_labels.test.json"},
    "11_create_individual_writing_languages": {"json_path": J / "writing_languages.test.json"},
}

ORDER = [
    "02_create_places",
    "03_create_country_of_citizenship",
    "04_create_occupations",
    "05_create_writing_languages",
    "06_create_identifier_types",
    "07_create_individuals",
    "08_create_identifiers",
    "09_create_wikimedia_links",
    "10_create_works",
    "11_create_individual_writing_languages",
]

EXPECTED = {
    "places":                        1,
    "country_of_citizenship":        1,
    "occupations":                   1,
    "writing_languages":             1,
    "identifier_types":              1,
    "individuals":                   1,
    "identifiers":                   0,
    "wikimedia_links":                1,
    "works":                         0,
    "individual_writing_languages":  0,
}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _purge(path: Path) -> None:
    """Delete a DuckDB file (and its WAL/lock siblings) so we start fresh."""
    if path.exists():
        path.unlink()
    for ext in (".wal", ".tmp"):
        side = Path(str(path) + ext)
        if side.exists():
            side.unlink()


def main() -> int:
    log("=" * 70)
    log("  V2 integration end-to-end test (DuckDB)")
    log("=" * 70)

    legacy_mtime_before = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None
    log(f"[guard] canonical DB {LEGACY_DB_PATH} (mtime before: {legacy_mtime_before})")

    _purge(SAMPLE_DB_PATH)
    log(f"[setup] writing to fresh {SAMPLE_DB_PATH}")

    missing = []
    for name, paths in TEST_INPUTS.items():
        for arg, path in paths.items():
            if not path.exists() and path.name.endswith(".test.json"):
                missing.append(f"{name}.{arg}: {path}")
    if missing:
        log("[ERROR] missing test inputs — run the v2 extraction with --test first:")
        for m in missing:
            log(f"        {m}")
        log("\n  python scripts/wikidata_extraction_scripts/run_all.py --test")
        return 1

    with open_db(SAMPLE_DB_PATH) as conn:
        for name in ORDER:
            log(f"\n>>> {name}.run(conn, ...)")
            mod = _load(name)
            mod.run(conn, **TEST_INPUTS[name])

    log("\n=== row count check ===")
    failures = []
    with duckdb.connect(str(SAMPLE_DB_PATH), read_only=True) as conn:
        for table, min_rows in EXPECTED.items():
            if not table_exists(conn, table):
                failures.append(f"  table missing: {table}")
                continue
            n = row_count(conn, table)
            ok = n >= min_rows
            log(f"  {table:34s} rows={n:>6}  (min {min_rows})  {'ok' if ok else 'FAIL'}")
            if not ok:
                failures.append(f"  {table}: {n} < {min_rows}")

    legacy_mtime_after = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None
    if legacy_mtime_before != legacy_mtime_after:
        failures.append(
            f"  canonical DB {LEGACY_DB_PATH} mtime changed: "
            f"{legacy_mtime_before} -> {legacy_mtime_after}"
        )
    else:
        log(f"\n[guard] canonical DB untouched (mtime unchanged)")

    if failures:
        log("\nFAILED:")
        for f in failures:
            log(f)
        return 1

    log(f"\nOK — sample DB at {SAMPLE_DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
