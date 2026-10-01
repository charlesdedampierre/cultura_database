"""Export one row per individual of the enriched database to a CSV shaped by ExportedIndividualCSV: identity, dates, period of activity, polities and occupations."""

import argparse
import sys
import tempfile
import time
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
sys.path.insert(0, str(ROOT / "scripts" / "3-raw_to_db" / "helpers"))

from datamodel_export import ExportedIndividualCSV
from pydantic_to_duckdb_schema import columns_of

DATABASE = ROOT / "data" / "cultura" / "humans_clean_enriched_v3.duckdb"
OUTPUT = ROOT / "data" / "exports" / "individuals_v3.csv"
SEPARATOR = " | "
CHUNKS = 16
FINE_PRECISIONS = ("day", "month", "year", "decade")

MACROS = f"""
CREATE TEMP MACRO preferred(dates) AS coalesce(list_filter(dates, d -> list_contains({list(FINE_PRECISIONS)}, d.precision))[1], dates[1]);
CREATE TEMP MACRO shown(d) AS CASE WHEN d.precision IN ('day', 'month') AND d.iso IS NOT NULL THEN d.iso ELSE CAST(d.year AS VARCHAR) END;
CREATE TEMP MACRO joined(items) AS nullif(array_to_string(items, '{SEPARATOR}'), '');
CREATE TEMP TABLE occupation_label AS SELECT map(list(entity.qid), list(coalesce(entity.label_en, entity.label_non_en))) AS labels FROM occupation;
"""

QUERY = """
SELECT
    person.entity.qid AS individual_id,
    coalesce(person.entity.label_en, person.entity.label_non_en) AS label,
    shown(preferred(person.birth_date)) AS birth_date,
    preferred(person.birth_date).precision AS birth_precision,
    shown(preferred(person.death_date)) AS death_date,
    preferred(person.death_date).precision AS death_precision,
    enriched.peak_productivity.start_year AS activity_start,
    enriched.peak_productivity.end_year AS activity_end,
    joined(list_transform(enriched.polity, match -> match.polity.name)) AS polities,
    joined(list_transform(enriched.polity, match -> CAST(match.polity.cliopatria_id AS VARCHAR))) AS polity_ids,
    joined(list_transform(enriched.polity, match -> CAST(match.years_spent_in_polity AS VARCHAR))) AS time_spent_in_polity,
    joined(list_transform(meta_polities(enriched.polity, enriched.peak_productivity), meta -> meta.name)) AS meta_polities,
    joined(list_transform(meta_polities(enriched.polity, enriched.peak_productivity), meta -> CAST(meta.cliopatria_id AS VARCHAR))) AS meta_polity_ids,
    joined(list_transform(person.occupation, one_occupation -> occupation_label.labels[one_occupation.entity.qid])) AS occupations
FROM (SELECT entity, birth_date, death_date, occupation FROM individual WHERE hash(entity.qid) % {chunks} = {chunk}) AS person
CROSS JOIN occupation_label
LEFT JOIN (SELECT entity, peak_productivity, polity FROM individual_enriched WHERE hash(entity.qid) % {chunks} = {chunk}) AS enriched
    ON enriched.entity.qid = person.entity.qid
"""

META_POLITIES = """
CREATE TEMP MACRO meta_polities(matches, peak) AS list_distinct(flatten(list_transform(matches, match ->
    list_transform(
        list_filter(match.polity.meta_polities, meta -> meta.start_year <= peak.end_year AND meta.end_year >= peak.start_year),
        meta -> {'cliopatria_id': meta.cliopatria_id, 'name': meta.name}
    )
)));
"""


COLUMNS = columns_of(ExportedIndividualCSV)


def read_typed(path):
    """A CSV read with the columns and types ExportedIndividualCSV gives it, so a column or value that does not fit stops the export."""
    return f"read_csv('{path}', header = true, delim = ',', quote = '\"', escape = '\"', columns = {COLUMNS!r})"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    started = time.time()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(args.database), read_only=True)
    connection.execute(f"SET memory_limit = '6GB'; SET threads = 4; SET preserve_insertion_order = false; SET temp_directory = '{tempfile.mkdtemp()}'")
    connection.execute(MACROS + META_POLITIES)
    parts = Path(tempfile.mkdtemp())
    for chunk in tqdm(range(CHUNKS), desc="export", unit=" chunk"):
        query = QUERY.format(chunks=CHUNKS, chunk=chunk)
        connection.execute(f"COPY ({query}) TO '{parts / f'{chunk:02d}.csv'}' (HEADER, DELIMITER ',')")
    columns = COLUMNS
    connection.execute(f"COPY (SELECT * FROM {read_typed(f'{parts}/*.csv')}) TO '{args.output}' (HEADER, DELIMITER ',')")
    header = connection.execute(f"SELECT * FROM {read_typed(args.output)} LIMIT 0").description
    assert [column[0] for column in header] == list(columns), "the CSV's columns are not those of ExportedIndividualCSV"
    rows = connection.execute(f"SELECT count(*) FROM {read_typed(args.output)}").fetchone()[0]
    connection.close()
    print(f"{rows:,} individuals written to {args.output} ({args.output.stat().st_size / 1e9:.2f} GB) in {time.time() - started:.0f} s")


if __name__ == "__main__":
    main()
