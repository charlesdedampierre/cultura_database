"""Ingest the date parquets of notebooks 01, 02 and 04 into individual_enriched of cultura_database_V4, shaped by datamodel_in_duckdb.IndividualEnriched.

birth_date and death_date come from 01_age_at_death, replaced by the coarse label of 05_coarse_dates for the individuals with only coarse dates;
start_of_active_life and end_of_active_life come from 03_b_active_life. Every other column keeps the value it already had."""

import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "4-database_enrichment"))

from common import D, DATABASE, SCRATCH, Enrichment, as_json, open_database, stage
from pydantic_to_duckdb_schema import columns_of, duck_type
from tqdm import tqdm

PARQUETS = ROOT / "data" / "enriched_parquets"
TASK_LOG = ROOT / "task.log"
DATE_TYPE = duck_type(D.IndividualDate)
TABLE = "individual_enriched"
NEW_TABLE = "individual_enriched_rebuilt"
BATCHES = 10  # qid ranges written one after the other

AGE_AT_DEATH = PARQUETS / "individual_dates_from_age_at_death.parquet"
ACTIVE_LIFE = PARQUETS / "individual_active_life.parquet"
COARSE_DATES = PARQUETS / "individual_coarse_dates.parquet"

BIRTH_DEATH_READS = ("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "IndividualWikidata.occupation")
ACTIVE_LIFE_READS = ("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "IndividualEnriched.birth_date", "IndividualEnriched.death_date", "IndividualWikidata.occupation", "IndividualWikidata.position_held", "Work.inception", "Work.publication_date")


def enrichment(column, reads, answers):
    return Enrichment(reads=reads, writes=(f"IndividualEnriched.{column}",), rule=D.IndividualEnriched.model_fields[column].description, answers=answers)


ENRICHMENTS = {
    "birth_date": enrichment("birth_date", BIRTH_DEATH_READS, HERE / "01_age_at_death.ipynb"),
    "death_date": enrichment("death_date", BIRTH_DEATH_READS, HERE / "01_age_at_death.ipynb"),
    "start_of_active_life": enrichment("start_of_active_life", ACTIVE_LIFE_READS, HERE / "03_b_active_life.ipynb"),
    "end_of_active_life": enrichment("end_of_active_life", ACTIVE_LIFE_READS, HERE / "03_b_active_life.ipynb"),
}


def as_individual_date(column):
    """A parquet date without coarse_label, given one so it casts to IndividualDate."""
    return f"CASE WHEN {column} IS NULL THEN NULL ELSE struct_insert({column}, coarse_label := NULL::VARCHAR) END"


NEW_VALUES = {
    "entity": "individual.entity",
    "birth_date": f"coalesce(coarse_dates.birth_date, {as_individual_date('age_at_death.birth_date')})",
    "death_date": f"coalesce(coarse_dates.death_date, {as_individual_date('age_at_death.death_date')})",
    "start_of_active_life": "active_life.start_of_active_life",
    "end_of_active_life": "active_life.end_of_active_life",
    "field_provenance": f"map_concat(coalesce(previous.field_provenance, MAP {{}}), (SELECT map_from_entries(list((date_provenance.column_name, date_provenance.provenance))) FROM date_provenance))",
}


RENAMED = {"pre_active_life_polity": "early_stage_polity", "active_life_polity": "active_stage_polity", "post_active_life_polity": "late_stage_polity"}  # new column: old column whose values it keeps
RETIRED = {"first_work_date", "last_work_date", *RENAMED.values()}  # replaced by the active life: dropped even when filled


def report(message):
    line = f"{datetime.now():%H:%M:%S}  ingest_dates     {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def load_sources(connection):
    for name, path in (("age_at_death", AGE_AT_DEATH), ("active_life", ACTIVE_LIFE), ("coarse_dates", COARSE_DATES)):
        connection.execute(f"CREATE OR REPLACE TEMP VIEW {name} AS SELECT * FROM read_parquet('{path}')")
        rows, unique = connection.execute(f"SELECT count(*), count(DISTINCT qid) FROM {name}").fetchone()
        assert rows == unique, f"{name}: {rows - unique} duplicated qids"
        report(f"{name}: {rows:,} individuals from {path.name}")
    rows = [{"column_name": column, "provenance": as_json(e.provenance())} for column, e in ENRICHMENTS.items()]
    stage(connection, "date_provenance", {"column_name": "VARCHAR", "provenance": duck_type(D.Provenance)}, rows)


def keep_previous(connection):
    """Columns of individual_enriched as it is, so the columns this script does not write keep their values; a column outside the datamodel must be empty."""
    existing = [row[0] for row in connection.execute(f"DESCRIBE {TABLE}").fetchall()]
    for column in set(existing) - set(columns_of(D.IndividualEnriched)) - RETIRED:
        filled = connection.execute(f'SELECT count("{column}") FROM {TABLE}').fetchone()[0]
        assert filled == 0, f"{TABLE}.{column} is not in the datamodel and holds {filled:,} values"
        report(f"{TABLE}.{column} is not in the datamodel and is empty: dropped")
    return existing


def select_list(existing):
    values = []
    for column, kind in columns_of(D.IndividualEnriched).items():
        kept = RENAMED.get(column, column) if RENAMED.get(column) in existing else column
        value = NEW_VALUES.get(column, f'previous."{kept}"' if kept in existing else "NULL")
        values.append(f'CAST({value} AS {kind}) AS "{column}"')
    return ",\n       ".join(values)


def rebuild(connection, existing):
    """Write the new table in qid ranges (the whole table at once does not fit in memory), then put it in place of the old one."""
    cuts = connection.execute(f"SELECT quantile_disc(entity.qid, {[i / BATCHES for i in range(1, BATCHES)]}) FROM individual").fetchone()[0]
    ranges = list(zip([None, *cuts], [*cuts, None]))
    connection.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
    for number, (low, high) in enumerate(tqdm(ranges, desc="qid ranges")):
        inside = " AND ".join([f"individual.entity.qid >= '{low}'"] * (low is not None) + [f"individual.entity.qid < '{high}'"] * (high is not None))
        rows = f"""
            SELECT {select_list(existing)}
            FROM individual
            LEFT JOIN age_at_death ON age_at_death.qid = individual.entity.qid
            LEFT JOIN coarse_dates ON coarse_dates.qid = individual.entity.qid
            LEFT JOIN active_life ON active_life.qid = individual.entity.qid
            LEFT JOIN {TABLE} AS previous ON previous.entity.qid = individual.entity.qid
            WHERE {inside}
            ORDER BY individual.entity.qid
        """
        connection.execute(f"CREATE TABLE {NEW_TABLE} AS {rows}" if number == 0 else f"INSERT INTO {NEW_TABLE} {rows}")
        report(f"qid range {number + 1}/{len(ranges)} written")
    connection.execute(f"DROP TABLE {TABLE}")
    connection.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO {TABLE}")


def check(connection):
    individuals = connection.execute("SELECT count(*) FROM individual").fetchone()[0]
    rows, births, deaths, active_starts, active_ends, coarse = connection.execute(f"""
        SELECT count(*), count(birth_date), count(death_date), count(start_of_active_life), count(end_of_active_life),
               count(*) FILTER (birth_date.coarse_label IS NOT NULL OR death_date.coarse_label IS NOT NULL)
        FROM {TABLE}
    """).fetchone()
    assert rows == individuals, f"{TABLE} has {rows:,} rows for {individuals:,} individuals"
    expected_coarse = connection.execute("SELECT count(*) FROM coarse_dates SEMI JOIN individual ON individual.entity.qid = coarse_dates.qid").fetchone()[0]
    assert coarse == expected_coarse, f"{coarse:,} coarse individuals written, {expected_coarse:,} expected"
    coarse_years = connection.execute(f"SELECT count(*) FROM {TABLE} WHERE (birth_date.coarse_label IS NOT NULL AND birth_date.year IS NOT NULL) OR (death_date.coarse_label IS NOT NULL AND death_date.year IS NOT NULL)").fetchone()[0]
    assert coarse_years == 0, f"{coarse_years:,} coarse dates keep a year"
    report(f"{rows:,} individuals: {births:,} births, {deaths:,} deaths ({coarse:,} with a coarse label), {active_starts:,} starts and {active_ends:,} ends of active life")


def main():
    for e in ENRICHMENTS.values():
        e.announce()
    started = time.time()
    report(f"writing {TABLE} of {DATABASE}")
    connection = open_database()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false; SET temp_directory='{SCRATCH}'")  # 16 GB machine: spill the sort to disk
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
