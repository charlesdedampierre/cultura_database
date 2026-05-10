"""One-shot helper: build `data/humans_clean_test.sqlite3` from the v2
LIMIT-100 .test.json files so the result can be browsed in a SQLite client.

Identical pipeline to test_end_to_end.py, but writes to a stable filename
and skips the row-count assertions. The legacy `humans_clean.sqlite3` is
NOT touched.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from common import DATA_DIR, LEGACY_DB_PATH, WIKIDATA_V2_DIR, log, open_db

OUT_DB = DATA_DIR / "humans_clean_test.sqlite3"
J = WIKIDATA_V2_DIR

INPUTS = {
    "02_create_places":          {"json_path": J / "place_metadata.test.json",
                                  "countries_path": J / "modern_countries.test.json"},
    "03_create_country_of_citizenship": {
        "meta_path":  J / "nationality_metadata.test.json",
        "label_path": J / "nationality_labels.test.json",
    },
    "04_create_occupations":     {"label_path": J / "occupation_labels.test.json",
                                  "meta_path": J / "occupation_metadata.test.json"},
    "05_create_writing_languages": {"label_path": J / "writing_language_labels.test.json"},
    "06_create_identifier_types":  {"props_path": J / "catalog_properties.json",
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

ORDER = list(INPUTS.keys())


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    log("=" * 70)
    log(f"  building {OUT_DB.name} from v2 test JSONs (legacy DB untouched)")
    log("=" * 70)

    legacy_mtime = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None

    for ext in ("", "-wal", "-shm"):
        p = Path(str(OUT_DB) + ext)
        if p.exists():
            p.unlink()

    with open_db(OUT_DB) as conn:
        for name in ORDER:
            log(f"\n>>> {name}")
            mod = _load(name)
            mod.run(conn, **INPUTS[name])

    legacy_mtime_after = LEGACY_DB_PATH.stat().st_mtime if LEGACY_DB_PATH.exists() else None
    if legacy_mtime != legacy_mtime_after:
        log(f"[guard] WARNING: legacy DB mtime changed ({legacy_mtime} -> {legacy_mtime_after})")
        return 1

    log(f"\n[guard] legacy DB untouched")
    log(f"\nDONE. Open {OUT_DB} in your SQLite client of choice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
