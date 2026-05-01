"""08 - Build writing_languages and individual_writing_languages tables.

Mirrors `enhance_db/src/bin/08_create_writing_languages.rs`.

  Inputs : data/all_humans/all_human_writing_languages.json
            { wikidata_id: [ {id, name}, ... ] }
           individuals (for individual_name backfill)
  Output : writing_languages              (id PK, name, count)
           individual_writing_languages   (wikidata_id, language_id, ...)
           Two indexes on the mapping table.

Usage
-----
    python3 08_create_writing_languages.py
    python3 08_create_writing_languages.py --full
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import (
    ALL_HUMANS_DIR,
    executemany_batched,
    insert_rows,
    load_json,
    log,
    open_db,
    parse_run_mode,
)

JSON_PATH = ALL_HUMANS_DIR / "all_human_writing_languages.json"


def clean_label(s: str) -> str:
    s = s.strip().strip('"')
    if s.endswith("@en"):
        s = s[:-3]
    return s


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> tuple[int, int]:
    log("[DB] 08: Creating writing_languages table...")
    human_langs = load_json(json_path)
    log(f"[DB] Loaded writing languages for {len(human_langs)} individuals")

    conn.execute("DROP TABLE IF EXISTS writing_languages")
    conn.execute("DROP TABLE IF EXISTS individual_writing_languages")
    conn.execute(
        """
        CREATE TABLE writing_languages (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            count INTEGER DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE individual_writing_languages (
            wikidata_id TEXT NOT NULL,
            individual_name TEXT,
            language_id TEXT NOT NULL,
            language_name TEXT,
            PRIMARY KEY (wikidata_id, language_id)
        )
        """
    )

    lang_counts: dict[str, list] = {}  # id -> [name, count]
    mappings: list[tuple[str, str, str]] = []

    try:
        from tqdm import tqdm
        items = tqdm(human_langs.items(), total=len(human_langs), desc="Processing languages")
    except ImportError:
        items = human_langs.items()

    for human_id, langs in items:
        if not isinstance(langs, list):
            continue
        for lang in langs:
            if not isinstance(lang, dict):
                continue
            lang_id = (lang.get("id") or "").strip()
            lang_name = clean_label(lang.get("name") or "")
            if not lang_id or not lang_name:
                continue
            entry = lang_counts.setdefault(lang_id, [lang_name, 0])
            entry[1] += 1
            mappings.append((human_id, lang_id, lang_name))

    log(f"[DB] Found {len(lang_counts)} unique languages, {len(mappings)} mappings")

    conn.executemany(
        "INSERT OR IGNORE INTO writing_languages (id, name, count) VALUES (?, ?, ?)",
        [(lid, name, count) for lid, (name, count) in lang_counts.items()],
    )
    conn.commit()

    log("[DB] Inserting individual-language mappings...")
    executemany_batched(
        conn,
        "INSERT OR IGNORE INTO individual_writing_languages "
        "(wikidata_id, language_id, language_name) VALUES (?, ?, ?)",
        mappings,
        batch_size=100_000,
        desc="Inserting mappings",
        total=len(mappings),
    )

    log("[DB] Updating individual names in writing_languages mapping...")
    conn.execute(
        """
        UPDATE individual_writing_languages SET individual_name = (
            SELECT individuals.name_en FROM individuals
            WHERE individuals.wikidata_id = individual_writing_languages.wikidata_id
        )
        """
    )
    conn.commit()

    conn.execute("CREATE INDEX IF NOT EXISTS idx_iwl_wikidata ON individual_writing_languages(wikidata_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_iwl_lang ON individual_writing_languages(language_id)")
    conn.commit()
    log("[DB] 08: Done. Created writing_languages tables.")
    return len(lang_counts), len(mappings)


def _sample_main() -> None:
    fake = {
        "Q1": [{"id": "Q1860", "name": "English"}, {"id": "Q150", "name": "French"}],
        "Q2": [{"id": "Q1860", "name": "English"}],
        "Q3": [{"id": "Q150", "name": "French@en"}],
    }
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "wl.json"
        json_path.write_text(json.dumps(fake))
        db_path = Path(tmp) / "sample.sqlite3"
        with sqlite3.connect(db_path) as seed:
            seed.execute("CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT)")
            insert_rows(seed, "individuals", [
                {"wikidata_id": "Q1", "name_en": "Alice"},
                {"wikidata_id": "Q2", "name_en": "Bob"},
                {"wikidata_id": "Q3", "name_en": "Cleo"},
            ])
            seed.commit()

        with open_db(db_path) as conn:
            n_langs, n_maps = run(conn, json_path=json_path)
            wl = conn.execute(
                "SELECT id, name, count FROM writing_languages ORDER BY count DESC"
            ).fetchall()
            iwl = conn.execute(
                "SELECT wikidata_id, individual_name, language_id, language_name "
                "FROM individual_writing_languages ORDER BY wikidata_id, language_id"
            ).fetchall()
        log(f"[sample] {n_langs} languages, {n_maps} mappings")
        for r in wl:
            log(f"  writing_languages: {r}")
        for r in iwl:
            log(f"  individual_writing_languages: {r}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
