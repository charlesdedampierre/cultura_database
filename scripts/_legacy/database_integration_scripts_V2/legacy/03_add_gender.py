"""03 - Add `gender` column to individuals from a TSV side-file.

Mirrors `enhance_db/src/bin/03_add_gender.rs`.

  Inputs : data/all_humans/all_human_genders.tsv  (wikidata_id\tgender)
           individuals  (PK = wikidata_id)
  Output : individuals.gender populated for every row found in the TSV.

The TSV is multi-GB; we stream it line-by-line rather than loading it
into memory. tqdm uses the file size in bytes for the progress bar.

Usage
-----
    python3 03_add_gender.py            # tiny synthetic TSV + DB
    python3 03_add_gender.py --full     # data/humans_clean.sqlite3
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    add_column_if_missing,
    insert_rows,
    log,
    open_db,
    parse_run_mode,
)

TSV_PATH = ALL_HUMANS_DIR / "all_human_genders.tsv"
COMMIT_EVERY = 500_000


def run(conn: sqlite3.Connection, tsv_path: Path = TSV_PATH) -> int:
    log("[DB] 03: Adding gender column to individuals...")
    if add_column_if_missing(conn, "individuals", "gender", "TEXT"):
        log("[DB] Added gender column to individuals")
    else:
        log("[DB] gender column already exists")

    file_size = os.path.getsize(tsv_path)
    cur = conn.cursor()
    cur.execute("BEGIN")
    updated = 0

    try:
        from tqdm import tqdm
        bar = tqdm(total=file_size, unit="B", unit_scale=True, desc="Setting gender")
    except ImportError:
        bar = None

    with open(tsv_path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if bar is not None:
                bar.update(len(line.encode("utf-8")))
            if line.startswith("wikidata_id"):
                continue
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            wid, gender = parts[0], parts[1]
            if not gender:
                continue
            cur.execute(
                "UPDATE individuals SET gender = ? WHERE wikidata_id = ?",
                (gender, wid),
            )
            updated += 1
            if updated % COMMIT_EVERY == 0:
                conn.commit()
                cur.execute("BEGIN")
                log(f"[DB]   Processed {updated} entries...")

    conn.commit()
    if bar is not None:
        bar.close()
    log(f"[DB] 03: Done. Updated {updated} individuals with gender.")
    return updated


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tsv_path = Path(tmp) / "genders.tsv"
        tsv_path.write_text(
            "wikidata_id\tgender\n"
            "Q1\tmale\n"
            "Q2\tfemale\n"
            "Q3\tmale\n"
            "Q4\t\n"  # blank gender, should be skipped
            "Q5\tnon-binary\n",
            encoding="utf-8",
        )
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
                {"wikidata_id": "Q3", "name_en": "Cleo"},
                {"wikidata_id": "Q4", "name_en": "Dax"},
                {"wikidata_id": "Q5", "name_en": "Eve"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            n = run(conn, tsv_path=tsv_path)
            rows = conn.execute(
                "SELECT wikidata_id, name_en, gender FROM individuals ORDER BY wikidata_id"
            ).fetchall()

        log(f"[sample] updated {n} rows")
        for r in rows:
            log(f"  individuals: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
