"""Build a fresh `data/humans_test.sqlite3` end-to-end from the
1000-human extraction (data/all_humans/test_1000/*.test.json), then run
consolidation (floruit_period + cliopatria from the V3 GeoJSON).

`humans_clean.sqlite3` is never opened. Re-runnable: drops + recreates
the test DB on every invocation.

Run:
    python scripts/_one_off/build_humans_test.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
TEST_DB = DATA_DIR / "humans_test.sqlite3"
TEST_JSON = DATA_DIR / "all_humans" / "test_1000"

INTEGRATION = PROJECT_ROOT / "scripts" / "database_integration_scripts_V2"
CONSOLIDATION = PROJECT_ROOT / "scripts" / "database_consolidation"

INTEGRATION_INPUTS = {
    "02_create_places": {
        "json_path":      TEST_JSON / "place_metadata.test.json",
        "countries_path": TEST_JSON / "modern_countries.test.json",
    },
    "03_create_country_of_citizenship": {
        "meta_path":  TEST_JSON / "nationality_metadata.test.json",
        "label_path": TEST_JSON / "nationality_labels.test.json",
    },
    "04_create_occupations": {
        "label_path": TEST_JSON / "occupation_labels.test.json",
        "meta_path":  TEST_JSON / "occupation_metadata.test.json",
    },
    "05_create_writing_languages": {
        "label_path": TEST_JSON / "writing_language_labels.test.json",
    },
    "06_create_identifier_types": {
        "props_path": TEST_JSON / "catalog_properties.json",
        "meta_path":  TEST_JSON / "catalog_metadata.test.json",
    },
    "07_create_individuals": {
        "main_info_path":               TEST_JSON / "main_info.test.json",
        "places_path":                  TEST_JSON / "places.test.json",
        "precisions_path":              TEST_JSON / "date_precisions.test.json",
        "occupations_path":             TEST_JSON / "occupations.test.json",
        "nationalities_path":           TEST_JSON / "nationalities.test.json",
        "sitelinks_path":               TEST_JSON / "sitelinks.test.json",
        "catalogs_path":                TEST_JSON / "catalogs.test.json",
        "works_path":                   TEST_JSON / "works.test.json",
        "writing_languages_path":       TEST_JSON / "writing_languages.test.json",
        "writing_language_labels_path": TEST_JSON / "writing_language_labels.test.json",
    },
    "08_create_identifiers":   {"catalogs_path": TEST_JSON / "catalogs.test.json"},
    "09_create_wikimedia_links": {"json_path":   TEST_JSON / "sitelinks.test.json"},
    "10_create_works":         {"works_path":  TEST_JSON / "works.test.json",
                                "labels_path": TEST_JSON / "work_labels.test.json"},
    "11_create_individual_writing_languages": {
        "json_path": TEST_JSON / "writing_languages.test.json",
    },
}

CONSOLIDATION_ORDER = [
    "01_individuals_floruit_period",
    "02_create_polities_cliopatria",
    "03_copy_polity_periods",
    "04_individuals_cliopatria",
]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    # Force every script to write to humans_test.sqlite3
    os.environ["CULTURA_DB_PATH"] = str(TEST_DB)

    for ext in ("", "-wal", "-shm"):
        side = Path(str(TEST_DB) + ext)
        if side.exists():
            side.unlink()
    print(f"[test-pipeline] writing fresh {TEST_DB}")

    # Stage 1: integration
    sys.path.insert(0, str(INTEGRATION))
    from common import open_db  # noqa: WPS433
    with open_db(TEST_DB) as conn:
        for name, kw in INTEGRATION_INPUTS.items():
            print(f"\n>>> integration/{name}")
            mod = _load(INTEGRATION / f"{name}.py")
            mod.run(conn, **kw)
    sys.path.pop(0)

    # Stage 2: consolidation
    sys.path.insert(0, str(CONSOLIDATION))
    # reload `common` so DB_PATH resolves to TEST_DB inside consolidation
    for k in [k for k in sys.modules if k == "common"]:
        del sys.modules[k]
    from common import open_db as open_db_cons  # noqa: WPS433
    with open_db_cons(TEST_DB) as conn:
        for name in CONSOLIDATION_ORDER:
            print(f"\n>>> consolidation/{name}")
            mod = _load(CONSOLIDATION / f"{name}.py")
            mod.run(conn)
    sys.path.pop(0)

    print(f"\n[test-pipeline] DONE -> {TEST_DB}")


if __name__ == "__main__":
    main()
