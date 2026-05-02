"""Build a fresh `data/humans_v2.sqlite3` from the v2 Wikidata JSONs.

Order matters because some scripts back-fill columns from earlier tables:
    02 places                   (looks up country names from
                                 modern_countries.json directly — there
                                 is no longer a `modern_country` table)
    03 country_of_citizenship   (referenced by 07 for the human's
                                 country_of_citizenship_en)
    04 occupations              (referenced by 07.individuals.occupations_en)
    05 writing_languages
    06 identifier_types
    07 individuals              (master row per Q5; floruit_date /
                                 floruit_precision / floruit_year live
                                 here since 2026-05 — no separate
                                 `individuals_floruit` table)
    08 identifiers              (joins to identifier_types.formatter_url)
    09 wikimedia_links          (formerly `sitelinks`)
    10 works
    11 individual_writing_languages

The legacy `data/humans_clean.sqlite3` is never touched.

Usage
-----
    python build_all.py            # writes to data/humans_v2.sqlite3
    python build_all.py --sample   # tiny end-to-end (just runs each script's
                                   # _sample_main, no real DB written)

For the *real* end-to-end test against the LIMIT-100 .test.json files
produced by `scripts/wikidata_extraction_scripts_v2/run_all.py --test`,
use `test_end_to_end.py`.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

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


def _load(name: str):
    path = HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sample", action="store_true",
                        help="Run each script's synthetic _sample_main "
                             "instead of writing to the real DB.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  database_integration_scripts_V2/build_all  "
          f"({'SAMPLE' if args.sample else 'FULL'} mode)")
    print("=" * 70)

    if args.sample:
        for name in ORDER:
            print(f"\n>>> {name}._sample_main()")
            mod = _load(name)
            t0 = time.time()
            try:
                mod._sample_main()
                print(f"<<< {name} ok in {time.time() - t0:.1f}s")
            except Exception as exc:
                print(f"<<< {name} FAILED: {exc}")
                raise
        return

    from common import open_db
    t_total = time.time()
    with open_db() as conn:
        for name in ORDER:
            print(f"\n>>> {name}.run(conn)")
            mod = _load(name)
            t0 = time.time()
            mod.run(conn)
            print(f"<<< {name} ok in {time.time() - t0:.1f}s")
    print(f"\nbuild_all done in {(time.time() - t_total) / 60:.1f} min")


if __name__ == "__main__":
    main()
