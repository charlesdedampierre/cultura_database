"""06 — Tag fictional connections in `individuals_cliopatria`.

Excludes individuals whose country of citizenship, birthplace, or deathplace
is itself a fictional polity / fictional place (e.g. fictional country
Q1378024, fictional state Q1145276). A `non_human` column is added (or
reset) on `individuals_cliopatria` and set to 1 for any individual with at
least one fictional connection.

Detection (DuckDB, server-side):
    - fictional CoC = `country_of_citizenship.instance_labels` matching
      fiction|myth|legend|imaginary|hypothetical.
    - fictional place = `places.entity_type` matching the same vocabulary.

Outputs (printed; the user pastes the X into the paper):
    - count of fictional CoC polities
    - count of fictional place entries
    - X = individuals in `individuals_cliopatria` with fictional CoC
    - total flagged in `individuals_cliopatria`

Usage
-----
    python scripts/database_consolidation/06_flag_non_human_cliopatria.py
    python scripts/database_consolidation/06_flag_non_human_cliopatria.py \\
        --db data/humans_clean.duckdb --table individuals_cliopatria
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb
import polars as pl

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DB = REPO / "data" / "humans_clean.duckdb"

FICTIONAL_COC_FILTER = """(
    instance_labels ILIKE '%fiction%'
 OR instance_labels ILIKE '%myth%'
 OR instance_labels ILIKE '%legend%'
 OR instance_labels ILIKE '%imaginary%'
 OR instance_labels ILIKE '%hypothetical%')"""

FICTIONAL_PLACE_FILTER = """(
    entity_type ILIKE '%fiction%'
 OR entity_type ILIKE '%myth%'
 OR entity_type ILIKE '%legend%'
 OR entity_type ILIKE '%imaginary%'
 OR entity_type ILIKE '%hypothetical%')"""


def run(db_path: Path, table: str) -> None:
    t_total = time.perf_counter()
    print(f"db: {db_path}")
    print(f"target table: {table}\n", flush=True)

    con = duckdb.connect(str(db_path))

    # ----- 1. fictional CoC + place sets ------------------------------
    t = time.perf_counter()
    fict_coc = con.execute(
        f"SELECT wikidata_id AS id, name_en, instance_labels "
        f"FROM country_of_citizenship WHERE {FICTIONAL_COC_FILTER}"
    ).pl()
    fict_place = con.execute(
        f"SELECT id, name_en, entity_type FROM places "
        f"WHERE {FICTIONAL_PLACE_FILTER}"
    ).pl()
    print(
        f"  fictional CoC entities  = {fict_coc.height} "
        f"[{time.perf_counter()-t:.2f}s]"
    )
    print(f"  fictional place entries = {fict_place.height}\n", flush=True)

    # Stage them as DuckDB tables for the joins below.
    con.execute("DROP TABLE IF EXISTS _fictional_coc")
    con.register("_tmp_fict_coc", fict_coc.to_pandas())
    con.execute("CREATE TEMP TABLE _fictional_coc AS SELECT * FROM _tmp_fict_coc")
    con.unregister("_tmp_fict_coc")

    con.execute("DROP TABLE IF EXISTS _fictional_place")
    con.register("_tmp_fict_place", fict_place.to_pandas())
    con.execute("CREATE TEMP TABLE _fictional_place AS SELECT * FROM _tmp_fict_place")
    con.unregister("_tmp_fict_place")

    # ----- 2. individuals connected to a fictional CoC / place --------
    t = time.perf_counter()
    con.execute(
        """
        DROP TABLE IF EXISTS _indiv_fict_coc;
        CREATE TEMP TABLE _indiv_fict_coc AS
        WITH coc_long AS (
            SELECT k.wikidata_id, TRIM(t.cid) AS coc_id
            FROM individuals_keys k,
                 UNNEST(string_split(k.country_of_citizenship_ids, ';')) AS t(cid)
            WHERE k.country_of_citizenship_ids IS NOT NULL
              AND TRIM(t.cid) <> ''
        )
        SELECT DISTINCT cl.wikidata_id
        FROM coc_long cl
        JOIN _fictional_coc fc ON fc.id = cl.coc_id;
        """
    )
    con.execute(
        """
        DROP TABLE IF EXISTS _indiv_fict_birth;
        CREATE TEMP TABLE _indiv_fict_birth AS
        SELECT DISTINCT k.wikidata_id
        FROM individuals_keys k
        JOIN _fictional_place fp ON fp.id = k.birthcity_id;
        """
    )
    con.execute(
        """
        DROP TABLE IF EXISTS _indiv_fict_death;
        CREATE TEMP TABLE _indiv_fict_death AS
        SELECT DISTINCT k.wikidata_id
        FROM individuals_keys k
        JOIN _fictional_place fp ON fp.id = k.deathcity_id;
        """
    )
    con.execute(
        """
        DROP TABLE IF EXISTS _indiv_fict_any;
        CREATE TEMP TABLE _indiv_fict_any AS
        SELECT wikidata_id FROM _indiv_fict_coc
        UNION SELECT wikidata_id FROM _indiv_fict_birth
        UNION SELECT wikidata_id FROM _indiv_fict_death;
        """
    )

    n_coc = con.execute("SELECT COUNT(*) FROM _indiv_fict_coc").fetchone()[0]
    n_birth = con.execute("SELECT COUNT(*) FROM _indiv_fict_birth").fetchone()[0]
    n_death = con.execute("SELECT COUNT(*) FROM _indiv_fict_death").fetchone()[0]
    n_any = con.execute("SELECT COUNT(*) FROM _indiv_fict_any").fetchone()[0]
    print(
        f"  individuals (whole DB) with fictional CoC        = {n_coc:,}"
    )
    print(
        f"  individuals (whole DB) with fictional birthplace = {n_birth:,}"
    )
    print(
        f"  individuals (whole DB) with fictional deathplace = {n_death:,}"
    )
    print(
        f"  individuals (whole DB) with ANY fictional link   = {n_any:,} "
        f"[{time.perf_counter()-t:.2f}s]\n",
        flush=True,
    )

    # ----- 3. add / reset non_human and flag rows ---------------------
    t = time.perf_counter()
    cols = {
        r[1]
        for r in con.execute(f"PRAGMA table_info('{table}')").fetchall()
    }
    if "non_human" not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN non_human INTEGER")
        con.execute(f"UPDATE {table} SET non_human = 0")
        print(f"  added column {table}.non_human")
    else:
        con.execute(f"UPDATE {table} SET non_human = 0")
        print(f"  reset {table}.non_human")

    con.execute(
        f"UPDATE {table} SET non_human = 1 "
        f"WHERE wikidata_id IN (SELECT wikidata_id FROM _indiv_fict_any)"
    )
    con.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{table}_non_human "
        f"ON {table}(non_human)"
    )

    n_total = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    n_flagged = con.execute(
        f"SELECT COUNT(*) FROM {table} WHERE non_human = 1"
    ).fetchone()[0]
    n_flagged_coc = con.execute(
        f"SELECT COUNT(*) FROM {table} "
        f"WHERE wikidata_id IN (SELECT wikidata_id FROM _indiv_fict_coc)"
    ).fetchone()[0]
    print(
        f"  flagged in {table}: {n_flagged:,} / {n_total:,} "
        f"({n_flagged/n_total*100:.2f}%) [{time.perf_counter()-t:.2f}s]"
    )

    # ----- 4. paper-friendly summary ----------------------------------
    print()
    print("============== summary for paper ==============")
    print(f"  fictional CoC polities identified         : {fict_coc.height}")
    print(f"  fictional place entries identified        : {fict_place.height}")
    print(f"  individuals (whole DB) with fictional CoC : {n_coc:,}")
    print(
        f"  individuals in {table} with fictional CoC : {n_flagged_coc:,}"
        "   <- X (CoC-only filter)"
    )
    print(
        f"  individuals in {table} flagged non_human  : {n_flagged:,} "
        f"({n_flagged/n_total*100:.2f}%)"
    )
    print()
    print(f"DONE in {time.perf_counter()-t_total:.2f}s -> {db_path}::{table}")
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--table", default="individuals_cliopatria")
    args = ap.parse_args()
    run(Path(args.db), args.table)


if __name__ == "__main__":
    main()
