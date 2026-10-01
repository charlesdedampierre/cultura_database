"""Build data/cultura/humans_clean_sample_v2.duckdb from humans_clean_v2.duckdb.

Keeps only the individuals shown in annotations/interfaces/polity_window_review.html, so the
enrichment scripts can be rerun on them in seconds:

    CULTURA_DB=data/cultura/humans_clean_sample_v2.duckdb .venv/bin/python scripts/database_enrichment/06_peak_productivity.py

Reference tables (places, polities, cohort statistics, ...) are copied whole: they are small,
and cohort_age_stats must stay measured on the full database. The sample file is rewritten
on every run.
"""

import re
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "cultura" / "humans_clean_v2.duckdb"
SAMPLE = ROOT / "data" / "cultura" / "humans_clean_sample_v2.duckdb"
ANNOTATION = ROOT / "annotations" / "interfaces" / "polity_window_review.html"

WHOLE_TABLES = ("place", "polity", "cohort_age_stats", "occupation_stats", "occupation", "identifier", "sitelink", "wikidata_property")

INDIVIDUAL_TABLES = {
    "individual": "SELECT * FROM source.individual WHERE entity.qid IN (SELECT qid FROM picked)",
    "individual_enriched": "SELECT * FROM source.individual_enriched WHERE entity.qid IN (SELECT qid FROM picked)",
    "individual_identifier": "SELECT * FROM source.individual_identifier WHERE qid IN (SELECT qid FROM picked)",
    "individual_sitelink": "SELECT * FROM source.individual_sitelink WHERE qid IN (SELECT qid FROM picked)",
    "individual_work": "SELECT * FROM source.individual_work WHERE qid IN (SELECT qid FROM picked)",
    "work": "SELECT * FROM source.work WHERE entity.qid IN (SELECT work_qid FROM individual_work)",
}


def annotated_qids():
    page = ANNOTATION.read_text(encoding="utf-8")
    return re.findall(r'<th>Wikidata</th><td><a href="https://www\.wikidata\.org/wiki/(Q\d+)"', page)


def main():
    qids = annotated_qids()
    print(f"{len(qids)} individuals in {ANNOTATION.name}")
    SAMPLE.unlink(missing_ok=True)
    connection = duckdb.connect(str(SAMPLE))
    connection.execute(f"ATTACH '{SOURCE}' AS source (READ_ONLY)")
    connection.execute("CREATE TEMP TABLE picked AS SELECT unnest(?) AS qid", [qids])

    for table in tqdm(WHOLE_TABLES, desc="reference tables"):
        connection.execute(f"CREATE TABLE {table} AS SELECT * FROM source.{table}")
    for table, query in tqdm(INDIVIDUAL_TABLES.items(), desc="individual tables"):
        connection.execute(f"CREATE TABLE {table} AS {query}")

    for (table,) in connection.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog = current_database() ORDER BY 1").fetchall():
        print(f"   {table:24} {connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0]:>10,}")
    missing = connection.execute("SELECT count(*) FROM picked WHERE qid NOT IN (SELECT entity.qid FROM individual)").fetchone()[0]
    assert missing == 0, f"{missing} annotated individuals are not in {SOURCE.name}"
    connection.close()
    print(f"wrote {SAMPLE} ({SAMPLE.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
