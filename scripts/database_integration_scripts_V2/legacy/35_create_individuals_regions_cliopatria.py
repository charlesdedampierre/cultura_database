"""35 - Create individuals_regions_cliopatria.

Mirrors `enhance_db/src/bin/35_create_individuals_regions_cliopatria.rs`.

Associates each individual with a Wikipedia URL using priority:
  1. nationality.en_wikipedia_url
  2. cities.en_wikipedia_url_original_country_name (deathcity)
  3. cities.en_wikipedia_url_original_country_name (birthcity)

  Output : individuals_regions_cliopatria (wikidata_id PK, name_en, url, origin)

Usage
-----
    python3 35_create_individuals_regions_cliopatria.py            # synthetic
    python3 35_create_individuals_regions_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import insert_rows, log, open_db, parse_run_mode

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection) -> int:
    log("[DB] 35: Creating individuals_regions_cliopatria...")

    nat_url = {}
    for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL"
    ):
        nat_url[n] = u
    city_url = {}
    for n, u in conn.execute(
        "SELECT name_en, en_wikipedia_url_original_country_name FROM cities "
        "WHERE en_wikipedia_url_original_country_name IS NOT NULL"
    ):
        city_url.setdefault(n, u)
    log(f"[35] nat_url={len(nat_url)} city_url={len(city_url)}")

    conn.execute("DROP TABLE IF EXISTS individuals_regions_cliopatria")
    conn.execute(
        """
        CREATE TABLE individuals_regions_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            url TEXT,
            origin TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    cursor = conn.execute(
        "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en "
        "FROM individuals ORDER BY rowid"
    )
    sql = (
        "INSERT OR IGNORE INTO individuals_regions_cliopatria "
        "(wikidata_id, name_en, url, origin) VALUES (?, ?, ?, ?)"
    )
    inserted = 0
    buf: list[tuple] = []
    for wid, name_en, nats, dc, bc in tqdm(cursor, total=total, desc="35_irc"):
        found = None
        if nats:
            for n in nats.split("; "):
                u = nat_url.get(n.strip())
                if u:
                    found = (u, "nationality")
                    break
        if found is None and dc:
            u = city_url.get(dc.strip())
            if u:
                found = (u, "deathplace")
        if found is None and bc:
            u = city_url.get(bc.strip())
            if u:
                found = (u, "birthplace")
        if found is None:
            continue
        url, origin = found
        buf.append((wid, name_en, url, origin))
        if len(buf) >= BATCH_SIZE:
            conn.executemany(sql, buf)
            conn.commit()
            inserted += len(buf)
            buf.clear()
    if buf:
        conn.executemany(sql, buf)
        conn.commit()
        inserted += len(buf)

    conn.execute("CREATE INDEX IF NOT EXISTS idx_irc_origin ON individuals_regions_cliopatria(origin)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_irc_url ON individuals_regions_cliopatria(url)")
    conn.commit()
    log(f"[35] inserted {inserted}")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    nationalities_en TEXT, deathcity_en TEXT, birthcity_en TEXT);
                CREATE TABLE nationalities (name_en TEXT, en_wikipedia_url TEXT);
                CREATE TABLE cities (name_en TEXT, en_wikipedia_url_original_country_name TEXT);
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "nationalities_en": "French",
                 "deathcity_en": None, "birthcity_en": None},
                {"wikidata_id": "Q2", "name_en": "Bob", "nationalities_en": None,
                 "deathcity_en": "Lyon", "birthcity_en": None},
            ])
            insert_rows(seed, "nationalities", [
                {"name_en": "French", "en_wikipedia_url": "https://en.wikipedia.org/wiki/France"}])
            insert_rows(seed, "cities", [
                {"name_en": "Lyon", "en_wikipedia_url_original_country_name": "https://en.wikipedia.org/wiki/France"}])
        with open_db(db) as conn:
            n = run(conn)
            rows = conn.execute("SELECT * FROM individuals_regions_cliopatria").fetchall()
        log(f"[sample] {n}: {rows}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
