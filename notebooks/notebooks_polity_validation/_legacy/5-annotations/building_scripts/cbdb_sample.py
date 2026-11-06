"""Sample of Cultura individuals that CBDB can be compared with, spread across centuries.

Reads every Wikidata CBDB id (P497) from QLever, keeps the Cultura individuals with a productivity
window known to the year and at least one polity, and draws up to --per-century of them in each
century of their window start. Saved to scripts/5-annotations/cbdb_validation/cbdb_sample.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/cbdb_sample.py [--per-century 60]
"""

import argparse
import csv
import io
from pathlib import Path

import duckdb
import requests

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "cultura" / "humans_clean_enriched_v3.duckdb"
OUT = ROOT / "scripts" / "5-annotations" / "cbdb_validation" / "cbdb_sample.json"
QLEVER = "https://qlever.dev/api/wikidata"
QUERY = "PREFIX wdt: <http://www.wikidata.org/prop/direct/> SELECT ?h ?c WHERE { ?h wdt:P497 ?c }"
FIRST_CENTURY, LAST_CENTURY = 3, 20
SEED = 0.42


def cbdb_ids():
    response = requests.post(QLEVER, data={"query": QUERY}, headers={"Accept": "text/tab-separated-values"}, timeout=300)
    response.raise_for_status()
    rows = list(csv.reader(io.StringIO(response.text), delimiter="\t"))[1:]
    return [(row[0].rsplit("/", 1)[-1].rstrip(">"), row[1].strip('"')) for row in rows]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-century", type=int, default=60)
    args = parser.parse_args()

    ids = cbdb_ids()
    print(f"{len(ids)} Wikidata items with a CBDB id")
    connection = duckdb.connect(str(DB), read_only=True)
    connection.execute("CREATE TEMP TABLE cbdb (qid VARCHAR, cbdb_id VARCHAR)")
    connection.executemany("INSERT INTO cbdb VALUES (?, ?)", ids)
    connection.execute(f"SELECT setseed({SEED})")
    sample = connection.execute("""
        WITH judged AS (
            SELECT individual_enriched.entity.qid AS qid,
                   individual_enriched.entity.label_en AS name,
                   min(cbdb.cbdb_id) AS cbdb_id,
                   CAST(floor(individual_enriched.peak_productivity.start_year / 100) + 1 AS INTEGER) AS century
            FROM cbdb JOIN individual_enriched ON individual_enriched.entity.qid = cbdb.qid
            WHERE individual_enriched.peak_productivity.start_year IS NOT NULL
              AND individual_enriched.peak_productivity.assignation_method NOT LIKE '%century%'
              AND individual_enriched.polity_count > 0
            GROUP BY ALL
        )
        SELECT qid, name, cbdb_id, century, row_number() OVER (PARTITION BY century ORDER BY random()) AS draw
        FROM judged
        WHERE century BETWEEN ? AND ?
        QUALIFY draw <= ?
        ORDER BY century, draw
    """, [FIRST_CENTURY, LAST_CENTURY, args.per_century]).df()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(sample.to_json(orient="records", force_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(sample)} individuals saved to {OUT.relative_to(ROOT)}")
    print(sample.groupby("century").size().to_string())


if __name__ == "__main__":
    main()
