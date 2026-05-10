"""30 — Build `individuals_regions_cliopatria`: each individual gets one
English Wikipedia URL chosen by priority (nationality -> deathcity -> birthcity).

Mirrors `enhance_db/src/bin/30_create_individuals_regions_cliopatria.rs`.

  Inputs : nationalities (name_en, en_wikipedia_url)
           cities (name_en, en_wikipedia_url_original_country_name)
           individuals (wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en)
  Output : individuals_regions_cliopatria (wikidata_id PK, name_en,
                                            en_wikipedia_url, origin)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    DB_PATH,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    transaction,
)

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 30: Creating individuals_regions_cliopatria...")

    nat_url: dict[str, str] = {}
    for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL"
    ):
        nat_url[n] = u
    log(f"[30] Nationality URL lookup: {len(nat_url)}")

    city_url: dict[str, str] = {}
    for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url_original_country_name FROM cities "
        "WHERE en_wikipedia_url_original_country_name IS NOT NULL"
    ):
        if n not in city_url:
            city_url[n] = u
    log(f"[30] City URL lookup: {len(city_url)}")

    conn.execute("DROP TABLE IF EXISTS individuals_regions_cliopatria")
    conn.execute(
        """
        CREATE TABLE individuals_regions_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            en_wikipedia_url TEXT,
            origin TEXT NOT NULL
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cur = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en FROM individuals"
    )
    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="30_cliopatria", unit="row")
    except ImportError:
        iterator = cur

    from_nat = from_death = from_birth = no_url = 0
    insert_sql = (
        "INSERT OR IGNORE INTO individuals_regions_cliopatria "
        "(wikidata_id, name_en, en_wikipedia_url, origin) VALUES (?, ?, ?, ?)"
    )
    buf: list[tuple] = []
    with transaction(conn):
        ins = conn.cursor()
        for wid, name, nats, death, birth in iterator:
            row = None
            if nats:
                for nm in nats.split("; "):
                    u = nat_url.get(nm.strip())
                    if u:
                        row = (wid, name, u, "nationality")
                        from_nat += 1
                        break
            if row is None and death:
                u = city_url.get(death.strip())
                if u:
                    row = (wid, name, u, "deathcity")
                    from_death += 1
            if row is None and birth:
                u = city_url.get(birth.strip())
                if u:
                    row = (wid, name, u, "birthcity")
                    from_birth += 1
            if row is None:
                no_url += 1
            else:
                buf.append(row)
                if len(buf) >= BATCH_SIZE:
                    ins.executemany(insert_sql, buf)
                    buf.clear()
        if buf:
            ins.executemany(insert_sql, buf)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cliopatria_url ON individuals_regions_cliopatria(en_wikipedia_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cliopatria_origin ON individuals_regions_cliopatria(origin)")
    conn.commit()
    final = conn.execute("SELECT COUNT(*) FROM individuals_regions_cliopatria").fetchone()[0]
    log(f"[30] Inserted {final} (nat:{from_nat} death:{from_death} birth:{from_birth} no_url:{no_url})")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT, "
                "nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT)"
            )
            seed.execute(
                "CREATE TABLE nationalities (name_en TEXT, en_wikipedia_url TEXT)"
            )
            seed.execute(
                "CREATE TABLE cities (name_en TEXT, en_wikipedia_url_original_country_name TEXT)"
            )
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "en_wikipedia_url": "https://en.wikipedia.org/wiki/France"},
            ])
            insert_rows(seed, "cities", [
                {"name_en": "Paris", "en_wikipedia_url_original_country_name": "https://en.wikipedia.org/wiki/Kingdom_of_France"},
                {"name_en": "Constantinople", "en_wikipedia_url_original_country_name": "https://en.wikipedia.org/wiki/Byzantine_Empire"},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "P1", "name_en": "Hugo", "nationalities_en": "French",
                 "deathcity_en": None, "birthcity_en": None},
                {"wikidata_id": "P2", "name_en": "Y", "nationalities_en": None,
                 "deathcity_en": "Constantinople", "birthcity_en": None},
                {"wikidata_id": "P3", "name_en": "Z", "nationalities_en": None,
                 "deathcity_en": None, "birthcity_en": "Paris"},
                {"wikidata_id": "P4", "name_en": "Nobody", "nationalities_en": None,
                 "deathcity_en": None, "birthcity_en": None},
            ])

        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT wikidata_id, name_en, en_wikipedia_url, origin "
                "FROM individuals_regions_cliopatria ORDER BY wikidata_id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
