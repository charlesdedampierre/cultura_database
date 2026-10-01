"""36 - Add polity_cliopatria + count columns to individuals_regions_cliopatria.

Mirrors `enhance_db/src/bin/36_add_polities_cliopatria.rs`.

  Inputs : individuals_regions_cliopatria (created by 35)
           cliopatria.db / polities (name, wikipedia_url)
  Output : two new columns on individuals_regions_cliopatria:
           polity_cliopatria (matched name, parens stripped) and count.

Usage
-----
    python3 36_add_polities_cliopatria.py            # synthetic
    python3 36_add_polities_cliopatria.py --full     # real DB + cliopatria
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from tqdm import tqdm

from common import (
    DB_PATH,
    PROJECT_ROOT,
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)

CLIO_DB_PATH = PROJECT_ROOT / "cliopatria_data" / "processing" / "data" / "cliopatria.db"
BATCH_SIZE = 50_000


def _strip_parens(name: str) -> str:
    s = name.strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1]
    return s


def run(conn: sqlite3.Connection, clio_db_path: Path | str = CLIO_DB_PATH) -> int:
    log("[DB] 36: Adding polity_cliopatria column...")

    url_to_polity: dict[str, str] = {}
    with sqlite3.connect(str(clio_db_path)) as clio:
        for name, url in clio.execute(
            "SELECT name, wikipedia_url FROM polities WHERE wikipedia_url IS NOT NULL"
        ):
            url_to_polity[url] = _strip_parens(name)
    log(f"[36] url->polity: {len(url_to_polity)}")

    if add_column_if_missing(conn, "individuals_regions_cliopatria", "polity_cliopatria", "TEXT"):
        log("[36] added polity_cliopatria column")
    else:
        conn.execute("UPDATE individuals_regions_cliopatria SET polity_cliopatria = NULL")
    if add_column_if_missing(conn, "individuals_regions_cliopatria", "count", "INTEGER"):
        log("[36] added count column")
    else:
        conn.execute("UPDATE individuals_regions_cliopatria SET count = NULL")
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM individuals_regions_cliopatria").fetchone()[0]
    cursor = conn.execute(
        "SELECT wikidata_id, url FROM individuals_regions_cliopatria ORDER BY rowid"
    )
    matched = 0
    buf: list[tuple] = []
    for wid, url in tqdm(cursor, total=total, desc="36_match"):
        polity = url_to_polity.get(url)
        if polity is None:
            continue
        buf.append((polity, wid))
        if len(buf) >= BATCH_SIZE:
            conn.executemany(
                "UPDATE individuals_regions_cliopatria SET polity_cliopatria = ? WHERE wikidata_id = ?",
                buf,
            )
            conn.commit()
            matched += len(buf)
            buf.clear()
    if buf:
        conn.executemany(
            "UPDATE individuals_regions_cliopatria SET polity_cliopatria = ? WHERE wikidata_id = ?",
            buf,
        )
        conn.commit()
        matched += len(buf)
    log(f"[36] matched {matched}")

    counts: dict[str, int] = {}
    for p, c in conn.execute(
        "SELECT polity_cliopatria, COUNT(*) FROM individuals_regions_cliopatria "
        "WHERE polity_cliopatria IS NOT NULL GROUP BY polity_cliopatria"
    ):
        counts[p] = c
    conn.executemany(
        "UPDATE individuals_regions_cliopatria SET count = ? WHERE polity_cliopatria = ?",
        [(c, p) for p, c in counts.items()],
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_irc_polity ON individuals_regions_cliopatria(polity_cliopatria)"
    )
    conn.commit()
    return matched


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        clio = Path(tmp) / "clio.db"
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(clio) as c:
            c.execute("CREATE TABLE polities (id INTEGER, name TEXT, wikipedia_url TEXT)")
            insert_rows(c, "polities", [
                {"id": 1, "name": "(British Empire)", "wikipedia_url": "https://en.wikipedia.org/wiki/British_Empire"},
                {"id": 2, "name": "France", "wikipedia_url": "https://en.wikipedia.org/wiki/France"},
            ])
        with sqlite3.connect(db) as seed:
            seed.execute(
                "CREATE TABLE individuals_regions_cliopatria (wikidata_id TEXT PRIMARY KEY, "
                "name_en TEXT, url TEXT, origin TEXT)"
            )
            insert_rows(seed, "individuals_regions_cliopatria", [
                {"wikidata_id": "Q1", "name_en": "A", "url": "https://en.wikipedia.org/wiki/France", "origin": "nationality"},
                {"wikidata_id": "Q2", "name_en": "B", "url": "https://en.wikipedia.org/wiki/British_Empire", "origin": "nationality"},
                {"wikidata_id": "Q3", "name_en": "C", "url": "https://en.wikipedia.org/wiki/Nowhere", "origin": "deathplace"},
            ])
        with open_db(db) as conn:
            n = run(conn, clio_db_path=clio)
            rows = conn.execute(
                "SELECT wikidata_id, polity_cliopatria, count FROM individuals_regions_cliopatria"
            ).fetchall()
        log(f"[sample] matched={n}")
        for r in rows:
            log(f"  {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
