"""Ingest the date parquets of notebooks 01, 02 and 04 into individual_enriched of cultura_enriched_v3.2, shaped by datamodel_in_duckdb.IndividualEnriched.

birth_date and death_date come from 01_age_at_death, replaced by the coarse label of 04_coarse_dates for the individuals with only coarse dates;
first_work_date and last_work_date come from 02_works_periods. Every other column keeps the value it already had."""

import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "4-database_enrichment"))

from common import D, DATABASE, Enrichment, as_json, open_database, stage
from pydantic_to_duckdb_schema import columns_of, duck_type

PARQUETS = ROOT / "data" / "enriched_parquets"
TASK_LOG = ROOT / "task.log"
DATE_TYPE = duck_type(D.IndividualDate)
TABLE = "individual_enriched"

AGE_AT_DEATH = PARQUETS / "individual_dates_from_age_at_death.parquet"
WORK_DATES = PARQUETS / "individual_work_dates.parquet"
COARSE_DATES = PARQUETS / "individual_coarse_dates.parquet"

BIRTH_DEATH_READS = ("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "IndividualWikidata.occupation")
WORK_READS = ("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "IndividualEnriched.birth_date", "IndividualWikidata.occupation", "Work.inception", "Work.publication_date")


def enrichment(column, reads, answers):
    return Enrichment(reads=reads, writes=(f"IndividualEnriched.{column}",), rule=D.IndividualEnriched.model_fields[column].description, answers=answers)


ENRICHMENTS = {
    "birth_date": enrichment("birth_date", BIRTH_DEATH_READS, HERE / "01_age_at_death.ipynb"),
    "death_date": enrichment("death_date", BIRTH_DEATH_READS, HERE / "01_age_at_death.ipynb"),
    "first_work_date": enrichment("first_work_date", WORK_READS, HERE / "02_works_periods.ipynb"),
    "last_work_date": enrichment("last_work_date", WORK_READS, HERE / "02_works_periods.ipynb"),
}


def as_individual_date(column):
    """A parquet date without coarse_label, given one so it casts to IndividualDate."""
    return f"CASE WHEN {column} IS NULL THEN NULL ELSE struct_insert({column}, coarse_label := NULL::VARCHAR) END"


NEW_VALUES = {
    "entity": "individual.entity",
    "birth_date": f"coalesce(coarse_dates.birth_date, {as_individual_date('age_at_death.birth_date')})",
    "death_date": f"coalesce(coarse_dates.death_date, {as_individual_date('age_at_death.death_date')})",
    "first_work_date": "work_dates.first_work_date",
    "last_work_date": "work_dates.last_work_date",
    "field_provenance": f"map_concat(coalesce(previous.field_provenance, MAP {{}}), (SELECT map_from_entries(list((date_provenance.column_name, date_provenance.provenance))) FROM date_provenance))",
}


def report(message):
    line = f"{datetime.now():%H:%M:%S}  ingest_dates     {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def load_sources(connection):
    for name, path in (("age_at_death", AGE_AT_DEATH), ("work_dates", WORK_DATES), ("coarse_dates", COARSE_DATES)):
        connection.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT * FROM read_parquet('{path}')")
        rows, unique = connection.execute(f"SELECT count(*), count(DISTINCT qid) FROM {name}").fetchone()
        assert rows == unique, f"{name}: {rows - unique} duplicated qids"
        report(f"{name}: {rows:,} individuals from {path.name}")
    rows = [{"column_name": column, "provenance": as_json(e.provenance())} for column, e in ENRICHMENTS.items()]
    stage(connection, "date_provenance", {"column_name": "VARCHAR", "provenance": duck_type(D.Provenance)}, rows)


def keep_previous(connection):
    """individual_enriched as it is, so the columns this script does not write keep their values; a column outside the datamodel must be empty."""
    connection.execute(f"CREATE OR REPLACE TEMP TABLE previous AS SELECT * FROM {TABLE}")
    existing = [row[0] for row in connection.execute("DESCRIBE previous").fetchall()]
    for column in set(existing) - set(columns_of(D.IndividualEnriched)):
        filled = connection.execute(f'SELECT count("{column}") FROM previous').fetchone()[0]
        assert filled == 0, f"{TABLE}.{column} is not in the datamodel and holds {filled:,} values"
        report(f"{TABLE}.{column} is not in the datamodel and is empty: dropped")
    return existing


def select_list(existing):
    values = []
    for column, kind in columns_of(D.IndividualEnriched).items():
        value = NEW_VALUES.get(column, f'previous."{column}"' if column in existing else "NULL")
        values.append(f'CAST({value} AS {kind}) AS "{column}"')
    return ",\n       ".join(values)


def rebuild(connection, existing):
    connection.execute(f"""
        CREATE OR REPLACE TABLE {TABLE} AS
        SELECT {select_list(existing)}
        FROM individual
        LEFT JOIN age_at_death ON age_at_death.qid = individual.entity.qid
        LEFT JOIN coarse_dates ON coarse_dates.qid = individual.entity.qid
        LEFT JOIN work_dates ON work_dates.qid = individual.entity.qid
        LEFT JOIN previous ON previous.entity.qid = individual.entity.qid
        ORDER BY individual.entity.qid
    """)


def check(connection):
    individuals = connection.execute("SELECT count(*) FROM individual").fetchone()[0]
    rows, births, deaths, first_works, last_works, coarse = connection.execute(f"""
        SELECT count(*), count(birth_date), count(death_date), count(first_work_date), count(last_work_date),
               count(*) FILTER (birth_date.coarse_label IS NOT NULL OR death_date.coarse_label IS NOT NULL)
        FROM {TABLE}
    """).fetchone()
    assert rows == individuals, f"{TABLE} has {rows:,} rows for {individuals:,} individuals"
    expected_coarse = connection.execute("SELECT count(*) FROM coarse_dates SEMI JOIN individual ON individual.entity.qid = coarse_dates.qid").fetchone()[0]
    assert coarse == expected_coarse, f"{coarse:,} coarse individuals written, {expected_coarse:,} expected"
    coarse_years = connection.execute(f"SELECT count(*) FROM {TABLE} WHERE (birth_date.coarse_label IS NOT NULL AND birth_date.year IS NOT NULL) OR (death_date.coarse_label IS NOT NULL AND death_date.year IS NOT NULL)").fetchone()[0]
    assert coarse_years == 0, f"{coarse_years:,} coarse dates keep a year"
    report(f"{rows:,} individuals: {births:,} births, {deaths:,} deaths ({coarse:,} with a coarse label), {first_works:,} first and {last_works:,} last work dates")


def main():
    for e in ENRICHMENTS.values():
        e.announce()
    started = time.time()
    report(f"writing {TABLE} of {DATABASE}")
    connection = open_database()
    load_sources(connection)
    existing = keep_previous(connection)
    connection.execute("BEGIN TRANSACTION")
    rebuild(connection, existing)
    check(connection)
    connection.execute("COMMIT")
    connection.close()
    report(f"done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
