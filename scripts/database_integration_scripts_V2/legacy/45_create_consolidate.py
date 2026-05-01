"""45 - Build the consolidate table + CSV.

Mirrors `enhance_db/src/bin/45_create_consolidate.rs`.

  Inputs : individuals_cliopatria (wikidata_id, name_en, polity_name, impact_date),
           individuals (occupations_en, gender, identifiers_count),
           individuals_keys (occupations_ids), occupations (id, meta_occupation).
  Output : consolidate (wikidata_id PK, name_en, impact_year, polity_name,
           occupations, gender, references_count, is_scientist, is_artist)
           + 4 indexes; CSV at data/consolidate.csv (full mode) or in the
           temp dir (sample mode).

Usage
-----
    python3 45_create_consolidate.py            # synthetic
    python3 45_create_consolidate.py --full     # real DB + data/consolidate.csv
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import DATA_DIR, insert_rows, log, open_db, parse_run_mode

BATCH_SIZE = 50_000


def run(conn: sqlite3.Connection, csv_path: Path) -> int:
    log("[DB] 45: Building consolidate...")

    occ_meta: dict[str, str] = {}
    for oid, meta in conn.execute(
        "SELECT id, meta_occupation FROM occupations WHERE meta_occupation IS NOT NULL"
    ):
        occ_meta[oid] = meta
    log(f"[45] occupation meta: {len(occ_meta)}")

    conn.execute("DROP TABLE IF EXISTS consolidate")
    conn.execute(
        """
        CREATE TABLE consolidate (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_year INTEGER,
            polity_name TEXT,
            occupations TEXT,
            gender TEXT,
            references_count INTEGER,
            is_scientist INTEGER DEFAULT 0,
            is_artist INTEGER DEFAULT 0
        )
        """
    )
    inserted = conn.execute(
        """
        INSERT INTO consolidate
            (wikidata_id, name_en, impact_year, polity_name, occupations, gender, references_count)
        SELECT ic.wikidata_id, ic.name_en, ic.impact_date, ic.polity_name,
               i.occupations_en, i.gender, i.identifiers_count
        FROM individuals_cliopatria ic
        JOIN individuals i ON ic.wikidata_id = i.wikidata_id
        """
    ).rowcount
    conn.commit()
    log(f"[45] inserted {inserted}")

    sci_count = art_count = updated = 0
    rows = conn.execute(
        "SELECT c.wikidata_id, k.occupations_ids "
        "FROM consolidate c LEFT JOIN individuals_keys k ON c.wikidata_id = k.wikidata_id"
    ).fetchall()
    buf: list[tuple] = []
    for wid, occ_ids in tqdm(rows, desc="45_flags"):
        if not occ_ids:
            continue
        is_sci = 0
        is_art = 0
        for oid in occ_ids.split(";"):
            meta = occ_meta.get(oid.strip())
            if meta == "scientist":
                is_sci = 1
            elif meta == "artist":
                is_art = 1
            if is_sci and is_art:
                break
        if is_sci or is_art:
            buf.append((is_sci, is_art, wid))
            sci_count += is_sci
            art_count += is_art
            updated += 1
            if len(buf) >= BATCH_SIZE:
                conn.executemany(
                    "UPDATE consolidate SET is_scientist = ?, is_artist = ? WHERE wikidata_id = ?",
                    buf,
                )
                conn.commit()
                buf.clear()
    if buf:
        conn.executemany(
            "UPDATE consolidate SET is_scientist = ?, is_artist = ? WHERE wikidata_id = ?",
            buf,
        )
        conn.commit()
    log(f"[45] flagged sci={sci_count} art={art_count} (updated {updated})")

    for ddl in (
        "CREATE INDEX IF NOT EXISTS idx_consolidate_polity ON consolidate(polity_name)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_year ON consolidate(impact_year)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_scientist ON consolidate(is_scientist)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_artist ON consolidate(is_artist)",
    ):
        conn.execute(ddl)
    conn.commit()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    cur = conn.execute(
        "SELECT wikidata_id, name_en, impact_year, polity_name, occupations, "
        "gender, references_count, is_scientist, is_artist FROM consolidate ORDER BY rowid"
    )
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "wikidata_id", "name_en", "impact_year", "polity_name",
            "occupations", "gender", "references_count", "is_scientist", "is_artist",
        ])
        n_csv = 0
        for row in tqdm(cur, total=inserted, desc="45_csv"):
            w.writerow(row)
            n_csv += 1
    log(f"[45] wrote {n_csv} rows to {csv_path}")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        csv_path = Path(tmp) / "consolidate.csv"
        with sqlite3.connect(db) as seed:
            seed.executescript(
                """
                CREATE TABLE individuals_cliopatria (wikidata_id TEXT PRIMARY KEY,
                    name_en TEXT, polity_name TEXT, impact_date INTEGER);
                CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT,
                    occupations_en TEXT, gender TEXT, identifiers_count INTEGER);
                CREATE TABLE individuals_keys (wikidata_id TEXT PRIMARY KEY,
                    occupations_ids TEXT);
                CREATE TABLE occupations (id TEXT PRIMARY KEY, meta_occupation TEXT);
                """
            )
            insert_rows(seed, "individuals_cliopatria", [
                {"wikidata_id": "Q1", "name_en": "Alice", "polity_name": "France", "impact_date": 1850},
                {"wikidata_id": "Q2", "name_en": "Bob", "polity_name": "USA", "impact_date": 1900},
                {"wikidata_id": "Q3", "name_en": "Cleo", "polity_name": "Egypt", "impact_date": -50},
            ])
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "occupations_en": "physicist",
                 "gender": "female", "identifiers_count": 5},
                {"wikidata_id": "Q2", "name_en": "Bob", "occupations_en": "painter",
                 "gender": "male", "identifiers_count": 12},
                {"wikidata_id": "Q3", "name_en": "Cleo", "occupations_en": "monarch",
                 "gender": "female", "identifiers_count": 99},
            ])
            insert_rows(seed, "individuals_keys", [
                {"wikidata_id": "Q1", "occupations_ids": "Q169470"},
                {"wikidata_id": "Q2", "occupations_ids": "Q1028181"},
                {"wikidata_id": "Q3", "occupations_ids": "Q116"},
            ])
            insert_rows(seed, "occupations", [
                {"id": "Q169470", "meta_occupation": "scientist"},
                {"id": "Q1028181", "meta_occupation": "artist"},
                {"id": "Q116", "meta_occupation": "ruler"},
            ])
        with open_db(db) as conn:
            n = run(conn, csv_path=csv_path)
            rows = conn.execute(
                "SELECT wikidata_id, polity_name, is_scientist, is_artist FROM consolidate"
            ).fetchall()
        log(f"[sample] {n} rows")
        for r in rows:
            log(f"  {r}")
        log(f"  csv at {csv_path} ({csv_path.stat().st_size} bytes)")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn, csv_path=DATA_DIR / "consolidate.csv")
    else:
        _sample_main()
