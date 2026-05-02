"""09 — Create the `wikimedia_links` long table from v2 sitelinks.

(Was `sitelinks` before the 2026-05 schema change. The extraction-pass
JSON file is still called `sitelinks.json` because re-running the
multi-hour Wikidata pull just to rename the file would be wasteful;
only the database table name changed.)

Inputs : data/all_humans/wikidata_extraction_scripts_v2/sitelinks.json
         {human_qid: ["https://en.wikipedia.org/wiki/...", ...]}
Output : wikimedia_links (id PK, wikidata_id, individual_name, site, title, url)
         - site  = host (e.g. "en.wikipedia.org")
         - title = last URL path segment, decoded

Usage
-----
    python3 09_create_wikimedia_links.py
    python3 09_create_wikimedia_links.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

from common import WIKIDATA_V2_DIR, log, load_json, open_db, parse_run_mode


JSON_PATH = WIKIDATA_V2_DIR / "sitelinks.json"


def _parse(url: str) -> tuple[str | None, str | None]:
    try:
        parsed = urlparse(url)
    except Exception:
        return None, None
    site = parsed.netloc or None
    title = parsed.path.rsplit("/", 1)[-1] if parsed.path else None
    if title:
        title = unquote(title).replace("_", " ")
    return site, title


def run(conn: sqlite3.Connection, json_path: Path = JSON_PATH) -> int:
    log("[DB] 09: Creating wikimedia_links table...")
    data = load_json(json_path)

    name_lookup = {}
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='individuals'"
    ).fetchone():
        name_lookup = dict(
            conn.execute("SELECT wikidata_id, name_en FROM individuals")
        )

    conn.execute("DROP TABLE IF EXISTS wikimedia_links")
    conn.execute(
        """
        CREATE TABLE wikimedia_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wikidata_id TEXT NOT NULL,
            individual_name TEXT,
            site TEXT,
            title TEXT,
            url TEXT
        )
        """
    )

    rows = []
    for qid, urls in data.items():
        person = name_lookup.get(qid)
        for url in urls or []:
            site, title = _parse(url)
            rows.append((qid, person, site, title, url))

    conn.executemany(
        "INSERT INTO wikimedia_links (wikidata_id, individual_name, site, title, url) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_wikimedia_links_wikidata "
        "ON wikimedia_links(wikidata_id)"
    )
    conn.commit()
    log(f"[DB] 09: Inserted {len(rows)} wikimedia_links.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    fake = {
        "Q937": [
            "https://en.wikipedia.org/wiki/Albert_Einstein",
            "https://fr.wikipedia.org/wiki/Albert_Einstein",
        ],
        "Q42": ["https://en.wikipedia.org/wiki/Douglas_Adams"],
    }
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "sitelinks.json"
        p.write_text(_json.dumps(fake))
        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            conn.executescript(
                "CREATE TABLE individuals (wikidata_id TEXT PRIMARY KEY, name_en TEXT);"
                "INSERT INTO individuals VALUES "
                "('Q937','Albert Einstein'),('Q42','Douglas Adams');"
            )
            n = run(conn, json_path=p)
            for r in conn.execute(
                "SELECT wikidata_id, individual_name, site, title "
                "FROM wikimedia_links ORDER BY id"
            ):
                log(f"  wikimedia_links: {r}")
        log(f"[sample] inserted {n} wikimedia_links")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
