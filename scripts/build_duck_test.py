"""Build a small DuckDB test database from a cohort of individuals.

Subsets `data/humans_clean.duckdb` to the QIDs listed in
`data/test_cohort/cohort_100k.json`, drops the consolidation phase
(polities, cliopatria, floruit_period) and the downstream enrichment
columns on `individuals`, and writes the result to
`data/duck_test.duckdb`.

The output mirrors the *pre-consolidation* schema produced by
`scripts/database_integration_scripts/` — i.e. what you'd have right
after the integration step and before
`scripts/database_consolidation/`. Use it for fast local iteration on
notebooks and figures without loading the 13 M-row canonical DB.

Usage
-----
    python scripts/build_duck_test.py
    python scripts/build_duck_test.py --cohort path/to/qids.json --out data/duck_test.duckdb
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
from tqdm import tqdm


REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "data" / "humans_clean.duckdb"
COHORT = REPO / "data" / "test_cohort" / "cohort_100k.json"
DST = REPO / "data" / "duck_test.duckdb"

INDIVIDUALS_BASE_COLS = [
    "wikidata_id",
    "name_en",
    "description_en",
    "birthdate",
    "birthdate_precision",
    "deathdate",
    "deathdate_precision",
    "floruit_date",
    "floruit_precision",
    "floruit_year",
    "gender",
    "birthcity_en",
    "deathcity_en",
    "country_of_citizenship_en",
    "occupations_en",
    "writing_language_name_en",
    "wikimedia_links_count",
    "identifiers_count",
    "number_of_works",
]

REFERENCE_TABLES_FULL_COPY = [
    "occupations",
    "country_of_citizenship",
    "writing_languages",
    "identifier_types",
    "wikidata_properties_definition",
]

CONSOLIDATION_TABLES_TO_SKIP = {
    "individuals_floruit_period",
    "individuals_cliopatria",
    "individuals_cliopatria_url",
    "polities_cliopatria",
    "polities_modern_countries_cliopatria",
    "polities_periods_cliopatria",
}


def load_cohort(path: Path) -> list[str]:
    qids = json.loads(path.read_text())
    if not isinstance(qids, list):
        sys.exit(f"cohort file {path} must contain a JSON array of QIDs")
    seen, out = set(), []
    for q in qids:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def build(src: Path, dst: Path, cohort_path: Path) -> None:
    if not src.exists():
        sys.exit(f"missing source: {src}")
    if not cohort_path.exists():
        sys.exit(f"missing cohort: {cohort_path}")
    if dst.exists():
        sys.exit(f"refusing to overwrite existing {dst}")

    cohort = load_cohort(cohort_path)
    print(f"src   : {src} ({src.stat().st_size / 1e9:.2f} GB)")
    print(f"cohort: {cohort_path} ({len(cohort):,} QIDs)")
    print(f"dst   : {dst}")

    con = duckdb.connect(str(dst))
    con.execute(f"ATTACH '{src}' AS src (READ_ONLY)")
    con.execute(
        "CREATE TEMP TABLE cohort_qid (wikidata_id VARCHAR PRIMARY KEY)"
    )
    con.executemany(
        "INSERT INTO cohort_qid VALUES (?)", [(q,) for q in cohort]
    )

    t0 = time.perf_counter()
    pbar = tqdm(total=11, unit="step", desc="building duck_test")

    pbar.set_postfix_str("individuals")
    cols_csv = ", ".join(f"i.{c}" for c in INDIVIDUALS_BASE_COLS)
    con.execute(
        f"CREATE TABLE individuals AS "
        f"SELECT {cols_csv} FROM src.individuals i "
        f"JOIN cohort_qid c USING (wikidata_id)"
    )
    con.execute(
        "CREATE INDEX idx_indiv_name ON individuals(name_en)"
    )
    con.execute(
        "CREATE INDEX idx_indiv_floruit_year ON individuals(floruit_year)"
    )
    pbar.update(1)

    pbar.set_postfix_str("individuals_keys")
    con.execute(
        "CREATE TABLE individuals_keys AS "
        "SELECT k.* FROM src.individuals_keys k "
        "JOIN cohort_qid c USING (wikidata_id)"
    )
    pbar.update(1)

    pbar.set_postfix_str("works")
    con.execute(
        "CREATE TABLE works AS "
        "SELECT w.* FROM src.works w "
        "JOIN cohort_qid c ON w.individual_id = c.wikidata_id"
    )
    con.execute("CREATE INDEX idx_works_individual ON works(individual_id)")
    pbar.update(1)

    pbar.set_postfix_str("individual_writing_languages")
    con.execute(
        "CREATE TABLE individual_writing_languages AS "
        "SELECT iwl.* FROM src.individual_writing_languages iwl "
        "JOIN cohort_qid c USING (wikidata_id)"
    )
    pbar.update(1)

    pbar.set_postfix_str("wikimedia_links")
    con.execute(
        "CREATE TABLE wikimedia_links AS "
        "SELECT wl.* FROM src.wikimedia_links wl "
        "JOIN cohort_qid c USING (wikidata_id)"
    )
    con.execute("CREATE INDEX idx_wml_qid ON wikimedia_links(wikidata_id)")
    pbar.update(1)

    pbar.set_postfix_str("identifiers")
    con.execute(
        "CREATE TABLE identifiers AS "
        "SELECT ids.* FROM src.identifiers ids "
        "JOIN cohort_qid c USING (wikidata_id)"
    )
    con.execute("CREATE INDEX idx_ids_qid ON identifiers(wikidata_id)")
    pbar.update(1)

    pbar.set_postfix_str("places (used by cohort)")
    con.execute(
        """
        CREATE TABLE places AS
        SELECT p.* FROM src.places p
        WHERE p.id IN (
            SELECT birthcity_id FROM individuals_keys WHERE birthcity_id IS NOT NULL
            UNION
            SELECT deathcity_id FROM individuals_keys WHERE deathcity_id IS NOT NULL
        )
        """
    )
    con.execute("CREATE INDEX idx_places_name ON places(name_en)")
    pbar.update(1)

    for ref in REFERENCE_TABLES_FULL_COPY:
        pbar.set_postfix_str(f"{ref} (full copy)")
        con.execute(f'CREATE TABLE "{ref}" AS SELECT * FROM src."{ref}"')
        pbar.update(1)

    pbar.close()

    con.execute("DETACH src")

    print()
    rows = con.execute("SHOW TABLES").fetchall()
    for (name,) in rows:
        n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name:38s} {n:>12,} rows")

    con.close()
    sz = dst.stat().st_size
    print(f"\ndone in {time.perf_counter() - t0:.1f}s — {dst.name} = {sz/1e6:.1f} MB")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--src", default=str(SRC), help=f"source DuckDB (default: {SRC})")
    p.add_argument("--cohort", default=str(COHORT), help=f"cohort JSON list of QIDs (default: {COHORT})")
    p.add_argument("--out", default=str(DST), help=f"destination DuckDB (default: {DST})")
    args = p.parse_args()
    build(Path(args.src), Path(args.out), Path(args.cohort))


if __name__ == "__main__":
    main()
