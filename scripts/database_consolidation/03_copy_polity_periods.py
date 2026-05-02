"""03 — Build `polities_periods_cliopatria` (per-period geometries) from the V3 GeoJSON.

(Was sourced from cliopatria_data/processing/data/cliopatria.db; switched
to cliopatria_data/cliopatria_V2/cliopatria_polities_only_v3.geojson in
2026-05.)

  Inputs : cliopatria_data/cliopatria_V2/cliopatria_polities_only_v3.geojson
  Output : polities_periods_cliopatria
              (id PK, polity_id, polity_name, from_year, to_year, area, geometry)
           polity_id is the int assigned by 02_create_polities_cliopatria
           (matched on (Name, Wikidata)). geometry is stored as a GeoJSON
           string for downstream shapely use.

Usage
-----
    python3 03_copy_polity_periods.py            # synthetic
    python3 03_copy_polity_periods.py --full     # real DB
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from common import PROJECT_ROOT, log, open_db, parse_run_mode

GEOJSON_PATH = (
    PROJECT_ROOT / "cliopatria_data" / "cliopatria_V2"
    / "cliopatria_polities_only_v3.geojson"
)


def _strip_parens(name: str) -> str:
    s = (name or "").strip()
    if s.startswith("(") and s.endswith(")"):
        return s[1:-1]
    return s


def _load_polity_id_map(conn: sqlite3.Connection) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for pid, name, qid in conn.execute(
        "SELECT id, name, wikidata_id FROM polities_cliopatria"
    ):
        out[(name, qid or "")] = pid
    return out


def run(conn: sqlite3.Connection, geojson_path: Path | str = GEOJSON_PATH) -> int:
    log("[DB] 03: Building polities_periods_cliopatria from V3 GeoJSON...")

    polity_id_map = _load_polity_id_map(conn)
    if not polity_id_map:
        raise RuntimeError(
            "polities_cliopatria is empty — run 02_create_polities_cliopatria "
            "first so polity_ids exist."
        )

    with open(geojson_path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)

    conn.execute("DROP TABLE IF EXISTS polities_periods_cliopatria")
    conn.execute(
        """
        CREATE TABLE polities_periods_cliopatria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polity_id INTEGER NOT NULL,
            polity_name TEXT,
            from_year INTEGER,
            to_year INTEGER,
            area REAL,
            geometry TEXT
        )
        """
    )

    rows: list[tuple] = []
    skipped = 0
    for feat in gj.get("features") or []:
        props = feat.get("properties") or {}
        name = _strip_parens(props.get("Name") or "")
        wikidata = (props.get("Wikidata") or "").strip()
        pid = polity_id_map.get((name, wikidata))
        if pid is None:
            skipped += 1
            continue
        try:
            from_year = int(props.get("FromYear"))
            to_year = int(props.get("ToYear"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        area = props.get("Area")
        try:
            area = float(area) if area is not None else None
        except (TypeError, ValueError):
            area = None
        geom = feat.get("geometry")
        geom_str = json.dumps(geom) if geom else None
        rows.append((pid, name, from_year, to_year, area, geom_str))

    conn.executemany(
        "INSERT INTO polities_periods_cliopatria "
        "(polity_id, polity_name, from_year, to_year, area, geometry) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppc_polity_id "
        "ON polities_periods_cliopatria(polity_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ppc_years "
        "ON polities_periods_cliopatria(from_year, to_year)"
    )
    conn.commit()
    log(f"[03] inserted {len(rows)} period rows (skipped {skipped})")
    return len(rows)


def _sample_main() -> None:
    fake = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "Name": "France", "Wikidata": "Q142", "Type": "kingdom",
                    "Wikipedia": "France",
                    "FromYear": 1500, "ToYear": 1789, "Area": 500000.0,
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            {
                "properties": {
                    "Name": "British Empire", "Wikidata": "Q8680",
                    "Type": "empire", "Wikipedia": "British_Empire",
                    "FromYear": 1700, "ToYear": 1947, "Area": 35000000.0,
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            },
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fake.geojson"
        path.write_text(json.dumps(fake))
        db = Path(tmp) / "sample.sqlite3"
        with open_db(db) as conn:
            conn.execute(
                "CREATE TABLE polities_cliopatria "
                "(id INTEGER PRIMARY KEY, name TEXT, type TEXT, "
                "wikipedia_url TEXT, wikidata_id TEXT, "
                "number_individuals INTEGER DEFAULT 0)"
            )
            conn.executemany(
                "INSERT INTO polities_cliopatria "
                "(id, name, type, wikipedia_url, wikidata_id) VALUES (?,?,?,?,?)",
                [(1, "France", "kingdom",
                  "https://en.wikipedia.org/wiki/France", "Q142"),
                 (2, "British Empire", "empire",
                  "https://en.wikipedia.org/wiki/British_Empire", "Q8680")],
            )
            n = run(conn, geojson_path=path)
            for r in conn.execute(
                "SELECT id, polity_id, polity_name, from_year, to_year "
                "FROM polities_periods_cliopatria"
            ):
                log(f"  {r}")
        log(f"[sample] {n} period rows")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
