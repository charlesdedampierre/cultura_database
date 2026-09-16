"""02 — Create the `polities_cliopatria` reference table from the V3 GeoJSON.

(Was sourced from cliopatria_data/processing/data/cliopatria.db; switched
to cliopatria_data/cliopatria_V2/cliopatria_polities_only_v3.geojson in
2026-05.)

Inputs : cliopatria_data/cliopatria_V2/cliopatria_polities_only_v3.geojson
         FeatureCollection of polity-periods. Properties used:
           Name, FromYear, ToYear, Type, Wikipedia, Wikidata
Output : polities_cliopatria
           id INTEGER PRIMARY KEY (assigned sequentially per distinct
                                  (Name, Wikidata) pair)
           name TEXT
           type TEXT
           wikipedia_url TEXT       ("https://en.wikipedia.org/wiki/<Wikipedia>"
                                     when Wikipedia is non-empty)
           wikidata_id TEXT
           number_individuals INTEGER DEFAULT 0
                                    (filled later by 04_individuals_cliopatria)

Usage
-----
    python3 02_create_polities_cliopatria.py            # synthetic
    python3 02_create_polities_cliopatria.py --full     # real DB
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import duckdb

from common import PROJECT_ROOT, log, parse_run_mode

GEOJSON_PATH = (
    PROJECT_ROOT
    / "cliopatria_data"
    / "cliopatria_V2"
    / "cliopatria_polities_only_v3.geojson"
)
DUCKDB_PATH = PROJECT_ROOT / "data" / "humans_clean.duckdb"


def _wikipedia_url(title: str | None) -> str | None:
    if not title:
        return None
    return f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


def _strip_parens(name: str) -> str:
    s = (name or "").strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1]
    return s


def collect_polities(geojson_path: Path | str) -> list[tuple]:
    """Return [(id, name, type, wikipedia_url, wikidata_id)] from the GeoJSON.

    Distinct polities are keyed on (Name, Wikidata) — Wikidata may be
    empty, in which case Name alone keys it. IDs are assigned in the
    order distinct keys are first seen.
    """
    with open(geojson_path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)
    seen: dict[tuple[str, str], int] = {}
    polities: list[tuple] = []
    for feat in gj.get("features") or []:
        props = feat.get("properties") or {}
        name = _strip_parens(props.get("Name") or "")
        if not name:
            continue
        wikidata = (props.get("Wikidata") or "").strip()
        ptype = (props.get("Type") or "").strip() or None
        wiki_title = (props.get("Wikipedia") or "").strip()
        wikipedia_url = _wikipedia_url(wiki_title)
        key = (name, wikidata)
        if key in seen:
            continue
        seen[key] = len(seen) + 1
        polities.append((seen[key], name, ptype, wikipedia_url, wikidata or None))
    return polities


def run(
    conn: duckdb.DuckDBPyConnection, geojson_path: Path | str = GEOJSON_PATH
) -> int:
    log("[DB] 02: Creating polities_cliopatria from V3 GeoJSON...")
    polities = collect_polities(geojson_path)
    log(f"[02] distinct polities: {len(polities)}")

    conn.execute("DROP TABLE IF EXISTS polities_cliopatria")
    conn.execute("""
        CREATE TABLE polities_cliopatria (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT,
            wikipedia_url TEXT,
            wikidata_id TEXT,
            number_individuals INTEGER DEFAULT 0
        )
        """)
    conn.executemany(
        "INSERT INTO polities_cliopatria "
        "(id, name, type, wikipedia_url, wikidata_id, number_individuals) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        polities,
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pc_name ON polities_cliopatria(name)")
    log(f"[02] inserted {len(polities)} polities")
    return len(polities)


def _sample_main() -> None:
    fake = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "Name": "France",
                    "Type": "kingdom",
                    "Wikipedia": "France",
                    "Wikidata": "Q142",
                    "FromYear": 1000,
                    "ToYear": 1500,
                }
            },
            {
                "properties": {
                    "Name": "France",
                    "Type": "kingdom",
                    "Wikipedia": "France",
                    "Wikidata": "Q142",
                    "FromYear": 1500,
                    "ToYear": 1789,
                }
            },
            {
                "properties": {
                    "Name": "(British Empire)",
                    "Type": "empire",
                    "Wikipedia": "British_Empire",
                    "Wikidata": "Q8680",
                    "FromYear": 1700,
                    "ToYear": 1947,
                }
            },
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fake.geojson"
        path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.duckdb"
        conn = duckdb.connect(str(db))
        try:
            n = run(conn, geojson_path=path)
            for r in conn.execute("SELECT * FROM polities_cliopatria").fetchall():
                log(f"  {r}")
        finally:
            conn.close()
        log(f"[sample] {n} polities")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        if not DUCKDB_PATH.exists():
            sys.exit(f"DuckDB not found at {DUCKDB_PATH}")
        conn = duckdb.connect(str(DUCKDB_PATH))
        try:
            run(conn)
        finally:
            conn.close()
    else:
        _sample_main()
