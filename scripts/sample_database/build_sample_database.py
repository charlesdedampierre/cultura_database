"""Build data/cultura/humans_clean_v3_sample.duckdb from humans_clean_enriched_v3.duckdb.

Keeps only the individuals of an annotation set — by default those shown in
annotations/legacy/interfaces/polity_window_review.html, or the wikidata_id column of a TSV — so the
enrichment scripts can be rerun on them in seconds:

    CULTURA_DB=data/cultura/humans_clean_v3_sample.duckdb .venv/bin/python scripts/4-database_enrichment/06_individual_peak_activity_window.py

Reference tables (places, polities, cohort statistics, ...) are copied whole: they are small,
and cohort_age_stats must stay measured on the full database. The sample file is rewritten
on every run.

Usage: build_sample_database.py [--from-tsv path/to/sample.tsv-or.parquet --name humans_clean_v3_sample_x]
"""

import argparse
import re
from pathlib import Path

import duckdb
import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "cultura" / "humans_clean_enriched_v3.duckdb"
DEFAULT_NAME = "humans_clean_v3_sample"
ANNOTATION = ROOT / "scripts" / "5-annotations" / "legacy" / "interfaces" / "polity_window_review.html"

WHOLE_TABLES = ("place", "polity", "cohort_age_stats", "occupation", "identifier", "sitelink", "wikidata_property")

INDIVIDUAL_TABLES = {
    "individual": "SELECT * FROM source.individual WHERE entity.qid IN (SELECT qid FROM picked)",
    "individual_enriched": "SELECT * FROM source.individual_enriched WHERE entity.qid IN (SELECT qid FROM picked)",
    "individual_identifier": "SELECT * FROM source.individual_identifier WHERE qid IN (SELECT qid FROM picked)",
    "individual_sitelink": "SELECT * FROM source.individual_sitelink WHERE qid IN (SELECT qid FROM picked)",
    "individual_work": "SELECT * FROM source.individual_work WHERE qid IN (SELECT qid FROM picked)",
    "work": "SELECT * FROM source.work WHERE entity.qid IN (SELECT work_qid FROM individual_work)",
}


def annotated_qids(tsv):
    if tsv and tsv.suffix == ".parquet":
        return list(pd.read_parquet(tsv)["wikidata_id"])
    if tsv:
        return list(pd.read_csv(tsv, sep="\t")["wikidata_id"])
    page = ANNOTATION.read_text(encoding="utf-8")
    return re.findall(r'<th>Wikidata</th><td><a href="https://www\.wikidata\.org/wiki/(Q\d+)"', page)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-tsv", type=Path)
    parser.add_argument("--name", default=DEFAULT_NAME)
    args = parser.parse_args()
    SAMPLE = ROOT / "data" / "cultura" / f"{args.name}.duckdb"
    qids = annotated_qids(args.from_tsv)
    print(f"{len(qids)} individuals in {(args.from_tsv or ANNOTATION).name}")
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
