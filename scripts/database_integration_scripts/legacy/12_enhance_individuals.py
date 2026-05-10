"""12 - Enhance individuals; fix writing_languages count + order.

Mirrors `enhance_db/src/bin/12_enhance_individuals.rs`.

  Inputs : individuals, individual_writing_languages, writing_languages
  Output : individuals rebuilt with new column order
             ..., birthdate, birthdate_precision, deathdate,
                  deathdate_precision, ..., writing_language_name_en
           writing_languages.count refreshed and table reordered by
           count DESC. Recovers from a half-finished previous run if it
           sees an `individuals_backup` table.

Usage
-----
    python3 12_enhance_individuals.py
    python3 12_enhance_individuals.py --full
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    insert_rows,
    log,
    open_db,
    parse_run_mode,
    table_exists,
)


def _recover(conn: sqlite3.Connection) -> None:
    """If `individuals_backup` survived a previous failed run, decide
    whether to restore from it or drop it as stale."""
    if not table_exists(conn, "individuals_backup"):
        return
    log("[12] RECOVERY: Found individuals_backup from previous failed run")
    backup_count = conn.execute("SELECT COUNT(*) FROM individuals_backup").fetchone()[0]
    cur_count = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[12]   individuals: {cur_count} rows, individuals_backup: {backup_count} rows")
    if backup_count > cur_count:
        log("[12]   Backup has more data, dropping empty individuals and restoring...")
        conn.executescript(
            "DROP TABLE individuals; ALTER TABLE individuals_backup RENAME TO individuals;"
        )
        log("[12]   Restored individuals from backup")
    else:
        log("[12]   Dropping stale backup...")
        conn.execute("DROP TABLE individuals_backup")
    conn.commit()


def run(conn: sqlite3.Connection) -> None:
    log("=== Step 12: Enhance individuals + fix writing_languages ===")
    _recover(conn)

    log("[12] Part A: Aggregating writing languages per individual...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS lang_agg;
        CREATE TEMP TABLE lang_agg AS
            SELECT wikidata_id, GROUP_CONCAT(language_name, ', ') AS langs
            FROM individual_writing_languages
            GROUP BY wikidata_id;
        CREATE INDEX idx_lang_agg_wid ON lang_agg(wikidata_id);
        """
    )
    n_langs = conn.execute("SELECT COUNT(*) FROM lang_agg").fetchone()[0]
    log(f"[12]   {n_langs} individuals with writing language data")

    total = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[12] Part B: Restructuring individuals table ({total} rows)...")

    conn.execute("ALTER TABLE individuals RENAME TO individuals_backup")
    conn.execute(
        """
        CREATE TABLE individuals (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            description_en TEXT,
            birthdate TEXT,
            birthdate_precision INTEGER,
            deathdate TEXT,
            deathdate_precision INTEGER,
            nationalities_en TEXT,
            birthcity_en TEXT,
            deathcity_en TEXT,
            occupations_en TEXT,
            sitelinks_count INTEGER DEFAULT 0,
            gender TEXT,
            identifiers_count INTEGER DEFAULT 0,
            writing_language_name_en TEXT
        )
        """
    )
    log("[12]   Inserting rows with LEFT JOIN for writing_language_name_en...")
    conn.execute(
        """
        INSERT INTO individuals
        SELECT
            i.wikidata_id, i.name_en, i.description_en,
            i.birthdate, i.birthdate_precision,
            i.deathdate, i.deathdate_precision,
            i.nationalities_en, i.birthcity_en, i.deathcity_en,
            i.occupations_en, i.sitelinks_count, i.gender, i.identifiers_count,
            la.langs
        FROM individuals_backup i
        LEFT JOIN lang_agg la ON la.wikidata_id = i.wikidata_id
        """
    )
    conn.execute("DROP TABLE individuals_backup")
    conn.commit()

    log("[12]   Creating indexes...")
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_name_en ON individuals(name_en);
        CREATE INDEX IF NOT EXISTS idx_birthcity_en ON individuals(birthcity_en);
        CREATE INDEX IF NOT EXISTS idx_sitelinks_count ON individuals(sitelinks_count);
        CREATE INDEX IF NOT EXISTS idx_birthdate_precision ON individuals(birthdate_precision);
        CREATE INDEX IF NOT EXISTS idx_deathdate_precision ON individuals(deathdate_precision);
        """
    )

    verify = conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    with_lang = conn.execute(
        "SELECT COUNT(*) FROM individuals WHERE writing_language_name_en IS NOT NULL"
    ).fetchone()[0]
    log(f"[12]   Result: {verify} rows, {with_lang} with writing_language_name_en")

    cols = [r[1] for r in conn.execute("PRAGMA table_info(individuals)").fetchall()]
    log(f"[12]   Columns: {', '.join(cols)}")

    log("[12] Part C: Updating writing_languages count...")
    conn.execute(
        """
        UPDATE writing_languages SET count = COALESCE(
            (SELECT COUNT(*) FROM individual_writing_languages
             WHERE language_id = writing_languages.id), 0
        )
        """
    )
    conn.commit()

    nonzero = conn.execute(
        "SELECT COUNT(*) FROM writing_languages WHERE count > 0"
    ).fetchone()[0]
    log(f"[12]   {nonzero} languages with non-zero count")

    log("[12]   Reordering writing_languages by count DESC...")
    conn.executescript(
        """
        DROP TABLE IF EXISTS writing_languages_backup;
        ALTER TABLE writing_languages RENAME TO writing_languages_backup;

        CREATE TABLE writing_languages (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            count INTEGER DEFAULT 0
        );

        INSERT INTO writing_languages (id, name, count)
        SELECT id, name, count FROM writing_languages_backup
        ORDER BY count DESC;

        DROP TABLE writing_languages_backup;
        """
    )
    conn.commit()

    wl_total = conn.execute("SELECT COUNT(*) FROM writing_languages").fetchone()[0]
    log(f"[12]   Writing languages: {wl_total} total")
    rows = conn.execute("SELECT name, count FROM writing_languages LIMIT 5").fetchall()
    for name, count in rows:
        log(f"[12]     {name} ({count})")
    log("=== Step 12 complete ===")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute(
                "CREATE TABLE individuals ("
                "wikidata_id TEXT PRIMARY KEY, name_en TEXT, description_en TEXT, "
                "birthdate TEXT, birthdate_precision INTEGER, "
                "deathdate TEXT, deathdate_precision INTEGER, "
                "nationalities_en TEXT, birthcity_en TEXT, deathcity_en TEXT, "
                "occupations_en TEXT, sitelinks_count INTEGER, gender TEXT, identifiers_count INTEGER)"
            )
            seed.execute(
                "CREATE TABLE writing_languages ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, count INTEGER DEFAULT 0)"
            )
            seed.execute(
                "CREATE TABLE individual_writing_languages ("
                "wikidata_id TEXT, individual_name TEXT, "
                "language_id TEXT, language_name TEXT, "
                "PRIMARY KEY (wikidata_id, language_id))"
            )
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice", "description_en": None,
                 "birthdate": "1900", "birthdate_precision": 9,
                 "deathdate": "1980", "deathdate_precision": 9,
                 "nationalities_en": "French", "birthcity_en": "Paris",
                 "deathcity_en": None, "occupations_en": "writer",
                 "sitelinks_count": 5, "gender": "female", "identifiers_count": 3},
                {"wikidata_id": "Q2", "name_en": "Bob", "description_en": None,
                 "birthdate": "1850", "birthdate_precision": 9,
                 "deathdate": None, "deathdate_precision": None,
                 "nationalities_en": "English", "birthcity_en": "London",
                 "deathcity_en": None, "occupations_en": "scientist",
                 "sitelinks_count": 2, "gender": "male", "identifiers_count": 1},
            ])
            insert_rows(seed, "writing_languages", [
                {"id": "Q1860", "name": "English", "count": 0},
                {"id": "Q150", "name": "French", "count": 0},
                {"id": "Q9999", "name": "Lojban", "count": 0},
            ])
            insert_rows(seed, "individual_writing_languages", [
                {"wikidata_id": "Q1", "individual_name": "Alice",
                 "language_id": "Q1860", "language_name": "English"},
                {"wikidata_id": "Q1", "individual_name": "Alice",
                 "language_id": "Q150", "language_name": "French"},
                {"wikidata_id": "Q2", "individual_name": "Bob",
                 "language_id": "Q1860", "language_name": "English"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            run(conn)
            inds = conn.execute(
                "SELECT wikidata_id, name_en, writing_language_name_en FROM individuals"
            ).fetchall()
            wl = conn.execute("SELECT id, name, count FROM writing_languages").fetchall()
        for r in inds:
            log(f"  individuals: {r}")
        for r in wl:
            log(f"  writing_languages: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
