"""17 — Build the `individuals_impact_date` table.

Mirrors `enhance_db/src/bin/17_create_impact_date.rs`.

For each individual:
  * `min(birthdate + 35 years, deathdate)` if both dates are present
  * `birthdate + 35 years` if only birthdate is present
  * `deathdate` if only deathdate is present
  * skipped if neither

  Inputs : individuals (wikidata_id, name_en, birthdate*, deathdate*)
  Output : individuals_impact_date (wikidata_id PK, name_en, impact_date,
           impact_date_precision, date_source)

Usage
-----
    python3 17_create_impact_date.py
    python3 17_create_impact_date.py --full
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


def _is_leap(year: int) -> bool:
    y = (1 - year) if year <= 0 else year
    return (y % 4 == 0) and ((y % 100 != 0) or (y % 400 == 0))


def _parse_date(s: str | None):
    if not s:
        return None
    s = s.strip()
    if not s or s.startswith("_:"):
        return None
    negative = s.startswith("-")
    rest = s[1:] if negative else s
    parts = rest.split("-", 2)
    if len(parts) < 3:
        return None
    try:
        y = int(parts[0])
        m = int(parts[1])
        d = int(parts[2].split("T", 1)[0])
    except ValueError:
        return None
    return (-y if negative else y, m, d)


def _add_35_years(y: int, m: int, d: int) -> tuple[int, int, int]:
    new_y = y + 35
    new_d = 28 if (m == 2 and d == 29 and not _is_leap(new_y)) else d
    return (new_y, m, new_d)


def _format_date(y: int, m: int, d: int) -> str:
    if y < 0:
        return f"-{-y:04d}-{m:02d}-{d:02d}"
    return f"{y:04d}-{m:02d}-{d:02d}"


def _date_gt(a, b) -> bool:
    return a > b


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 17: Creating individuals_impact_date...")

    conn.execute("DROP TABLE IF EXISTS individuals_impact_date")
    conn.execute(
        """
        CREATE TABLE individuals_impact_date (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            impact_date TEXT,
            impact_date_precision INTEGER,
            date_source TEXT
        )
        """
    )

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[17] Total individuals: {total}")

    cur = conn.execute(
        "SELECT wikidata_id, name_en, birthdate, birthdate_precision, "
        "deathdate, deathdate_precision FROM individuals"
    )

    try:
        from tqdm import tqdm
        iterator = tqdm(cur, total=total, desc="impact_date", unit="row")
    except ImportError:
        iterator = cur

    rows_processed = 0
    rows_inserted = 0
    from_birth = 0
    from_death = 0
    skipped_no_date = 0

    insert_sql = (
        "INSERT INTO individuals_impact_date "
        "(wikidata_id, name_en, impact_date, impact_date_precision, date_source) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    BATCH = 100_000
    buf: list[tuple] = []

    with transaction(conn):
        ins = conn.cursor()
        for wid, name_en, birthdate, birth_prec, deathdate, death_prec in iterator:
            rows_processed += 1
            bp = _parse_date(birthdate)
            dp = _parse_date(deathdate)

            if bp is not None and dp is not None:
                impact = _add_35_years(*bp)
                if _date_gt(impact, dp):
                    buf.append((wid, name_en, _format_date(*dp), death_prec, "deathdate"))
                    from_death += 1
                else:
                    buf.append((wid, name_en, _format_date(*impact), birth_prec, "birthdate"))
                    from_birth += 1
                rows_inserted += 1
            elif bp is not None:
                impact = _add_35_years(*bp)
                buf.append((wid, name_en, _format_date(*impact), birth_prec, "birthdate"))
                from_birth += 1
                rows_inserted += 1
            elif dp is not None:
                buf.append((wid, name_en, _format_date(*dp), death_prec, "deathdate"))
                from_death += 1
                rows_inserted += 1
            else:
                skipped_no_date += 1

            if len(buf) >= BATCH:
                ins.executemany(insert_sql, buf)
                buf.clear()
        if buf:
            ins.executemany(insert_sql, buf)
            buf.clear()

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_impact_date ON individuals_impact_date(impact_date)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_impact_wid ON individuals_impact_date(wikidata_id)"
    )
    conn.commit()

    log("[17] === Summary ===")
    log(f"[17]   Total processed: {rows_processed}")
    log(f"[17]   Inserted: {rows_inserted}")
    log(f"[17]   From birthdate+35: {from_birth}")
    log(f"[17]   From deathdate: {from_death}")
    log(f"[17]   Skipped (no dates): {skipped_no_date}")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db) as seed:
            seed.execute(
                """
                CREATE TABLE individuals (
                    wikidata_id TEXT PRIMARY KEY,
                    name_en TEXT,
                    birthdate TEXT,
                    birthdate_precision INTEGER,
                    deathdate TEXT,
                    deathdate_precision INTEGER
                )
                """
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Long Lived", "birthdate": "1800-01-01",
                 "birthdate_precision": 11, "deathdate": "1900-01-01", "deathdate_precision": 11},
                {"wikidata_id": "Q2", "name_en": "Short Lived", "birthdate": "1850-06-15",
                 "birthdate_precision": 11, "deathdate": "1860-01-01", "deathdate_precision": 11},
                {"wikidata_id": "Q3", "name_en": "Only Birth", "birthdate": "1900-03-10",
                 "birthdate_precision": 11, "deathdate": None, "deathdate_precision": None},
                {"wikidata_id": "Q4", "name_en": "Only Death", "birthdate": None,
                 "birthdate_precision": None, "deathdate": "0500-12-25", "deathdate_precision": 11},
                {"wikidata_id": "Q5", "name_en": "BCE", "birthdate": "-0050-03-15",
                 "birthdate_precision": 9, "deathdate": "0014-08-19", "deathdate_precision": 11},
                {"wikidata_id": "Q6", "name_en": "Empty", "birthdate": None,
                 "birthdate_precision": None, "deathdate": None, "deathdate_precision": None},
            ])

        with open_db(db) as conn:
            run(conn)
            for row in conn.execute(
                "SELECT wikidata_id, name_en, impact_date, impact_date_precision, date_source "
                "FROM individuals_impact_date ORDER BY wikidata_id"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
