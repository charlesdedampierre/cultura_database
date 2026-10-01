"""26 — Fill nationality countries from QLEVER parent-country data, then
rebuild individuals_countries.

Mirrors `enhance_db/src/bin/26_fill_nationality_countries.rs`.

  Inputs : data/all_humans/nationality_parent_countries.json
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    DB_PATH,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
    transaction,
)

PARENT_COUNTRIES_PATH = ALL_HUMANS_DIR / "nationality_parent_countries.json"
BATCH_SIZE = 50_000


def _rebuild(conn: sqlite3.Connection) -> None:
    nat_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup[n] = (c, i)
    city_lookup: dict[str, tuple[str, str]] = {}
    for n, c, i in conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities "
        "WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        if n not in city_lookup:
            city_lookup[n] = (c, i)
    log(f"[26] Lookups: nat={len(nat_lookup)} city={len(city_lookup)}")

    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute(
        """
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY, name_en TEXT,
            iso_country_name TEXT NOT NULL, iso_a3_code TEXT NOT NULL,
            origins TEXT NOT NULL
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cur = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en FROM individuals"
    )
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="26_rebuild", unit="row")
    except ImportError:
        iterator = cur

    matched_nat = matched_death = matched_birth = unmatched = 0
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_countries "
        "(wikidata_id, name_en, iso_country_name, iso_a3_code, origins) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    buf: list[tuple] = []
    with transaction(conn):
        ins = conn.cursor()
        for wid, name, nats, death, birth in iterator:
            row = None
            if nats:
                for nm in nats.split("; "):
                    hit = nat_lookup.get(nm.strip())
                    if hit:
                        row = (wid, name, hit[0], hit[1], "nationality")
                        matched_nat += 1
                        break
            if row is None and death:
                hit = city_lookup.get(death.strip())
                if hit:
                    row = (wid, name, hit[0], hit[1], "deathplace")
                    matched_death += 1
            if row is None and birth:
                hit = city_lookup.get(birth.strip())
                if hit:
                    row = (wid, name, hit[0], hit[1], "birthplace")
                    matched_birth += 1
            if row is None:
                unmatched += 1
            else:
                buf.append(row)
                if len(buf) >= BATCH_SIZE:
                    ins.executemany(insert_sql, buf)
                    buf.clear()
        if buf:
            ins.executemany(insert_sql, buf)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso_country ON individuals_countries(iso_country_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)")
    conn.commit()
    final = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    log(f"[26] Final: {final} (nat:{matched_nat} death:{matched_death} birth:{matched_birth} unmatched:{unmatched})")


def run(conn: sqlite3.Connection, parent_countries_path: Path = PARENT_COUNTRIES_PATH) -> None:
    log("[DB] 26: Fill nationality countries from QLEVER...")
    parents = load_json(parent_countries_path)
    log(f"[26] Loaded {len(parents)} parent country mappings")

    null_before = conn.execute(
        "SELECT COUNT(*) FROM nationalities WHERE iso_country_name IS NULL"
    ).fetchone()[0]
    log(f"[26] Nationalities NULL iso_country: {null_before}")

    updated = 0
    with transaction(conn):
        cur = conn.cursor()
        for qid, val in parents.items():
            if not isinstance(val, dict):
                continue
            cn = val.get("country_name")
            iso = val.get("iso_a3_code")
            if cn and iso:
                rc = cur.execute(
                    "UPDATE nationalities SET iso_country_name = ?, iso_a3_code = ? "
                    "WHERE wikidata_id = ? AND iso_country_name IS NULL",
                    (cn, iso, qid),
                ).rowcount
                if rc > 0:
                    updated += 1

    null_after = conn.execute(
        "SELECT COUNT(*) FROM nationalities WHERE iso_country_name IS NULL"
    ).fetchone()[0]
    log(f"[26] Updated {updated} nationalities. Still NULL: {null_after}")

    _rebuild(conn)


def _sample_main() -> None:
    parents = {
        "Q9999": {"country_name": "France", "iso_a3_code": "FRA"},
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "nationality_parent_countries.json"
        path.write_text(json.dumps(parents))
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE nationalities (wikidata_id TEXT PRIMARY KEY, name_en TEXT, "
                "iso_country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE cities (name_en TEXT, iso_country_name TEXT, iso_a3_code TEXT)"
            )
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT, name_en TEXT, "
                "nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"wikidata_id": "Q142", "name_en": "French", "iso_country_name": "France", "iso_a3_code": "FRA"},
                {"wikidata_id": "Q9999", "name_en": "Gauls", "iso_country_name": None, "iso_a3_code": None},
            ])
            insert_rows(seed, "cities", [
                {"name_en": "Paris", "iso_country_name": "France", "iso_a3_code": "FRA"},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "P1", "name_en": "Asterix", "nationalities_en": "Gauls",
                 "deathcity_en": None, "birthcity_en": None},
            ])
        with open_db(db) as conn:
            run(conn, parent_countries_path=path)
            for row in conn.execute("SELECT * FROM nationalities"):
                log(f"  nat: {row}")
            for row in conn.execute("SELECT * FROM individuals_countries"):
                log(f"  ind: {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
