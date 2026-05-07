"""Export the wikidata_codes that exist in the Cross-Verified database but
are missing from Cultura's individuals table. Output is a JSON list of QIDs
suitable for use as WIKIDATA_TEST_COHORT_FILE with the v2 extractor.
"""

from pathlib import Path
import json
import duckdb

ROOT = Path(__file__).resolve().parents[1]
CV_CSV = ROOT / "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"
DB = ROOT / "data/humans_clean.sqlite3"
OUT = ROOT / "data/cv_missing_from_cultura/missing_qids.json"

OUT.parent.mkdir(parents=True, exist_ok=True)

con = duckdb.connect()
con.execute("INSTALL sqlite; LOAD sqlite;")
con.execute(f"ATTACH '{DB}' AS cult (TYPE sqlite, READ_ONLY);")
con.execute(f"""
    CREATE TEMP TABLE cv AS
    SELECT wikidata_code AS qid
    FROM read_csv_auto('{CV_CSV}', header=true, ignore_errors=true)
    WHERE wikidata_code IS NOT NULL AND wikidata_code <> '';
""")
rows = con.execute("""
    SELECT qid FROM cv
    WHERE qid NOT IN (SELECT wikidata_id FROM cult.individuals)
    ORDER BY qid;
""").fetchall()

qids = [r[0] for r in rows]
OUT.write_text(json.dumps(qids), encoding="utf-8")
print(f"Wrote {len(qids):,} QIDs to {OUT}")
print(f"Sample: {qids[:5]}")
