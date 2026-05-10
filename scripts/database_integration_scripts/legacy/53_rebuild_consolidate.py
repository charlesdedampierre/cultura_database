"""53 — Rebuild consolidate table from individuals_cliopatria.

Mirrors `enhance_db/src/bin/53_rebuild_consolidate.rs`.

  Inputs : individuals_cliopatria, individuals, individuals_keys,
           occupations, polities_cliopatria
  Output : consolidate (wikidata_id, name_en, impact_year, polity_id,
                          polity_name, occupations, gender,
                          references_count, is_scientist, is_artist)
           CSV at data/consolidate.csv (or temp file in sample mode)
           polities_cliopatria.number_individuals refreshed.

Usage
-----
    python3 53_rebuild_consolidate.py
    python3 53_rebuild_consolidate.py --full
"""

from __future__ import annotations

import csv
import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import DATA_DIR, insert_rows, log, open_db, parse_run_mode

CSV_PATH = DATA_DIR / "consolidate.csv"


def run(conn: sqlite3.Connection, csv_path: Path = CSV_PATH) -> int:
    log("[DB] 53: Rebuild consolidate...")
    occ_lookup = dict(conn.execute(
        "SELECT id, meta_occupation FROM occupations "
        "WHERE meta_occupation IS NOT NULL"
    ))
    polity_id_to_name = dict(
        conn.execute("SELECT id, name FROM polities_cliopatria")
    )

    conn.execute("DROP TABLE IF EXISTS consolidate")
    conn.execute(
        """
        CREATE TABLE consolidate (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_year INTEGER,
            polity_id TEXT,
            polity_name TEXT,
            occupations TEXT,
            gender TEXT,
            references_count INTEGER,
            is_scientist INTEGER DEFAULT 0,
            is_artist INTEGER DEFAULT 0
        )
        """
    )

    total = conn.execute(
        "SELECT COUNT(*) FROM individuals_cliopatria ic "
        "JOIN individuals i ON ic.wikidata_id = i.wikidata_id"
    ).fetchone()[0]

    inserted = 0
    cur = conn.cursor()
    cur.execute("BEGIN")
    rows = conn.execute(
        "SELECT ic.wikidata_id, ic.name_en, ic.impact_date, ic.polity_id, "
        "i.occupations_en, i.gender, i.identifiers_count "
        "FROM individuals_cliopatria ic "
        "JOIN individuals i ON ic.wikidata_id = i.wikidata_id"
    )
    for wid, name_en, impact, pid_str, occs, gender, refs in tqdm(
        rows, total=total, desc="53", unit="row"
    ):
        if not pid_str:
            continue
        ids = []
        names = []
        for pid in pid_str.split(";"):
            pid = pid.strip()
            if not pid:
                continue
            try:
                pid_i = int(pid)
            except ValueError:
                continue
            n = polity_id_to_name.get(pid_i)
            if n:
                ids.append(pid)
                names.append(n)
        if not ids:
            continue
        cur.execute(
            "INSERT OR IGNORE INTO consolidate "
            "(wikidata_id, name_en, impact_year, polity_id, polity_name, "
            "occupations, gender, references_count) VALUES (?,?,?,?,?,?,?,?)",
            (wid, name_en, impact, ";".join(ids), ";".join(names),
             occs, gender, refs),
        )
        inserted += 1
        if inserted % 50_000 == 0:
            conn.commit()
            cur.execute("BEGIN")
    conn.commit()
    log(f"[DB] consolidate rows: {inserted}")

    # is_scientist / is_artist
    for wid, in tqdm(
        conn.execute("SELECT wikidata_id FROM consolidate").fetchall(),
        desc="53-flags", unit="row",
    ):
        row = conn.execute(
            "SELECT occupations_ids FROM individuals_keys WHERE wikidata_id = ?",
            (wid,),
        ).fetchone()
        if not row or not row[0]:
            continue
        is_sci = 0
        is_art = 0
        for occ_id in row[0].split(";"):
            meta = occ_lookup.get(occ_id.strip())
            if meta == "scientist":
                is_sci = 1
            elif meta == "artist":
                is_art = 1
            if is_sci and is_art:
                break
        if is_sci or is_art:
            conn.execute(
                "UPDATE consolidate SET is_scientist=?, is_artist=? WHERE wikidata_id=?",
                (is_sci, is_art, wid),
            )
    conn.commit()

    for sql in (
        "CREATE INDEX IF NOT EXISTS idx_consolidate_polity_id ON consolidate(polity_id)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_polity ON consolidate(polity_name)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_year ON consolidate(impact_year)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_scientist ON consolidate(is_scientist)",
        "CREATE INDEX IF NOT EXISTS idx_consolidate_artist ON consolidate(is_artist)",
    ):
        conn.execute(sql)
    conn.commit()

    # Update polities_cliopatria.number_individuals
    counts: dict[int, int] = {}
    for (pid_str,) in conn.execute(
        "SELECT polity_id FROM consolidate WHERE polity_id IS NOT NULL"
    ):
        for p in pid_str.split(";"):
            p = p.strip()
            try:
                counts[int(p)] = counts.get(int(p), 0) + 1
            except ValueError:
                continue
    conn.execute("UPDATE polities_cliopatria SET number_individuals = 0")
    conn.executemany(
        "UPDATE polities_cliopatria SET number_individuals = ? WHERE id = ?",
        [(c, pid) for pid, c in counts.items()],
    )
    conn.commit()

    # CSV export
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "wikidata_id", "name_en", "impact_year", "polity_id",
            "polity_name", "occupations", "gender", "references_count",
            "is_scientist", "is_artist",
        ])
        for r in conn.execute(
            "SELECT wikidata_id, name_en, impact_year, polity_id, polity_name, "
            "occupations, gender, references_count, is_scientist, is_artist "
            "FROM consolidate"
        ):
            w.writerow(["" if v is None else v for v in r])
    log(f"[DB] CSV exported to {csv_path}")
    return inserted


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        csv_path = Path(tmp) / "consolidate.csv"
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE polities_cliopatria (id INTEGER PRIMARY KEY, "
                "name TEXT, number_individuals INTEGER DEFAULT 0)"
            )
            insert_rows(seed, "polities_cliopatria", [
                {"id": 1, "name": "Han", "number_individuals": 0},
            ])
            seed.execute(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, occupations_en TEXT, gender TEXT, "
                "identifiers_count INTEGER)"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice",
                 "occupations_en": "scientist", "gender": "F",
                 "identifiers_count": 5},
            ])
            seed.execute(
                "CREATE TABLE individuals_cliopatria (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, polity_id TEXT, impact_date INTEGER)"
            )
            insert_rows(seed, "individuals_cliopatria", [
                {"wikidata_id": "Q1", "name_en": "Alice",
                 "polity_id": "1", "impact_date": 100},
            ])
            seed.execute(
                "CREATE TABLE individuals_keys (wikidata_id TEXT, "
                "occupations_ids TEXT)"
            )
            insert_rows(seed, "individuals_keys", [
                {"wikidata_id": "Q1", "occupations_ids": "Q170790"},
            ])
            seed.execute("CREATE TABLE occupations (id TEXT, meta_occupation TEXT)")
            insert_rows(seed, "occupations", [
                {"id": "Q170790", "meta_occupation": "scientist"},
            ])
        with open_db(db) as conn:
            run(conn, csv_path=csv_path)
            for r in conn.execute("SELECT * FROM consolidate"):
                log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
