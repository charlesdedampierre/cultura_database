"""The 300 benchmark individuals with what Cultura says about them, to be compared later with their biography.

Reads the individuals drawn by 2_sample.py ("quota") and those added by 3_fill.py so that
every region and century has at least three individuals ("century fill"), and adds, from the enriched Cultura database,
the fields that BiographyData (datamodel_annotations.py) will extract from the biography: birth and
death dates, first and last work dates (start and end of active life), with their source, and the
early, active and late stage polities (empty until the polity step of the enrichment has run).
Saved to data/benchmark_cultura.tsv.

Usage: .venv/bin/python notebooks/notebooks_polity_validation/scripts/4_cultura.py
"""

from pathlib import Path

import duckdb
import polars as pl

from dictionaries import DATA, NAMES, URLS

ROOT = Path(__file__).resolve().parents[3]
ENRICHED_DB = ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"
SAMPLE = DATA / "sample.parquet"
ADDITIONS = DATA / "additions.parquet"
OUT = DATA / "benchmark_cultura.tsv"


def date_columns(field):
    return f"""individual_enriched.{field}.year AS cultura_{field}_year, individual_enriched.{field}.source AS cultura_{field}_source"""


def stage_columns(stage):
    return f"""array_to_string(list_transform(individual_enriched.{stage}, match -> match.polity.name), '; ') AS cultura_{stage}"""


def cultura_values(qids):
    connection = duckdb.connect(str(ENRICHED_DB), read_only=True)
    return connection.execute(f"""
        SELECT individual_enriched.entity.qid AS qid,
               {date_columns('birth_date')}, {date_columns('death_date')},
               {date_columns('first_work_date')}, {date_columns('last_work_date')},
               {stage_columns('early_stage_polity')}, {stage_columns('active_stage_polity')}, {stage_columns('late_stage_polity')}
        FROM individual_enriched
        WHERE individual_enriched.entity.qid IN (SELECT unnest(?))
    """, [qids]).pl()


def main():
    benchmark = pl.read_parquet(SAMPLE).filter(pl.col("in_benchmark")).with_columns(draw=pl.lit("quota"))
    if ADDITIONS.exists():
        additions = pl.read_parquet(ADDITIONS).with_columns(draw=pl.lit("century fill"))
        benchmark = pl.concat([benchmark, additions.select(benchmark.columns)])
    values = cultura_values(benchmark["qid"].to_list())
    table = (benchmark
        .with_columns(
            wikidata_url="https://www.wikidata.org/wiki/" + pl.col("qid"),
            dictionary_name=pl.col("dictionary").replace_strict(NAMES),
            biography_url=pl.struct("dictionary", "dictionary_id").map_elements(lambda row: URLS[row["dictionary"]].format(row["dictionary_id"]), return_dtype=pl.Utf8))
        .join(values, on="qid", how="left")
        .select("qid", "label", "wikidata_url", pl.col("region").alias("claude_estimated_region"), pl.col("country").alias("claude_estimated_country"),
                pl.col("period").alias("claude_estimated_period"), "draw", "wikipedia_editions", "notability", "dictionary_name", "dictionary_id", "biography_url", *[column for column in values.columns if column != "qid"])
        .sort("claude_estimated_region", "cultura_birth_date_year"))
    assert table["qid"].is_unique().all()
    table.write_csv(OUT, separator="\t")
    print(f"{len(table)} individuals saved to {OUT.relative_to(ROOT)}")
    print(table["draw"].value_counts())
    for field in ("birth_date", "death_date", "first_work_date", "last_work_date", "early_stage_polity", "active_stage_polity", "late_stage_polity"):
        column = table[f"cultura_{field}_year" if field.endswith("date") else f"cultura_{field}"]
        filled = column.drop_nulls().filter(column.drop_nulls() != "") if column.dtype == pl.Utf8 else column.drop_nulls()
        print(f"  {field:20} {len(filled):3} / {len(table)}")


if __name__ == "__main__":
    main()
