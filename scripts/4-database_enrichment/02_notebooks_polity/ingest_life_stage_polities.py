"""Ingest the life-stage polity parquets of 01_life_stage_polities_export.py into individual_enriched of cultura_enriched_v3.2,
shaped by datamodel_in_duckdb.PolityMatch.

pre_active_life_polity, active_life_polity and post_active_life_polity get every polity of the stage, longest overlap first;
main_polity is the first polity of active_life_polity. active_life_ongoing is True for an active stage written with an empty end_year
(no death year, active life reaching the present), False for any other active stage. seshat stays empty: the Polity territories of v3.2 carry no Seshat id yet (enrichment step 08).
Every other column keeps the value it already had.

Run with --sample to build the polity matches of 10,000 individuals without writing anything."""

import argparse
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

STAGE_PARQUETS = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities" / "batch_*.parquet"
TASK_LOG = ROOT / "task.log"
TABLE = "individual_enriched"
NEW_TABLE = "individual_enriched_rebuilt"
BATCHES = 10  # hash buckets of individuals when building the matches
REBUILD_RANGES = 40  # qid ranges written one after the other
SAMPLE_SIZE = 10_000

MATCH_LIST_TYPE = f"{duck_type(D.PolityMatch)}[]"
STAGE_COLUMNS = {"pre_active": "pre_active_life_polity", "active": "active_life_polity", "post_active": "post_active_life_polity"}
FIELD_NAMES = {
    "birthplace": "birthplace", "deathplace": "deathplace", "citizenship": "country_of_citizenship", "work location": "work_location",
    "residence": "residence", "employer": "employer", "educated at": "educated_at", "position held": "position_held",
}
METHOD_NAMES = {"coordinates": "polygon", "URL": "url"}
NAME_FIXES = {"Kingdom of Naples (Napoleonic": "Kingdom of Naples (Napoleonic)"}  # cut short by the export

READS = (
    "IndividualEnriched.birth_date", "IndividualEnriched.death_date", "IndividualEnriched.start_of_active_life", "IndividualEnriched.end_of_active_life",
    "IndividualWikidata.place_of_birth", "IndividualWikidata.place_of_death", "IndividualWikidata.country_of_citizenship", "IndividualWikidata.work_location",
    "IndividualWikidata.residence", "IndividualWikidata.employer", "IndividualWikidata.educated_at", "IndividualWikidata.position_held", "Polity.territories",
)
ENRICHMENTS = {
    column: Enrichment(reads=READS, writes=(f"IndividualEnriched.{column}",), rule=D.IndividualEnriched.model_fields[column].description, answers=HERE / "01_life_stage_polities.ipynb")
    for column in [*STAGE_COLUMNS.values(), "main_polity", "active_life_ongoing"]
}


def report(message):
    line = f"{datetime.now():%H:%M:%S}  ingest_polities  {message}"
    print(line, flush=True)
    with TASK_LOG.open("a") as handle:
        handle.write(line + "\n")


def sql_map(mapping):
    return "MAP {" + ", ".join(f"'{key}': '{value}'" for key, value in mapping.items()) + "}"


def load_stage_rows(connection, sample):
    where = f"WHERE qid IN (SELECT DISTINCT qid FROM read_parquet('{STAGE_PARQUETS}') ORDER BY hash(qid) LIMIT {SAMPLE_SIZE})" if sample else ""
    connection.execute(f"CREATE OR REPLACE TEMP TABLE stage_rows AS SELECT * FROM read_parquet('{STAGE_PARQUETS}') {where}")
    rows, keys, individuals = connection.execute("SELECT count(*), count(DISTINCT (qid, stage)), count(DISTINCT qid) FROM stage_rows").fetchone()
    assert rows == keys, f"{rows - keys} duplicated (qid, stage) rows"
    mismatched = connection.execute("SELECT count(*) FROM stage_rows WHERE len(polities) <> len(polity_years)").fetchone()[0]
    assert mismatched == 0, f"{mismatched} stages with as many polities as years"
    report(f"{rows:,} stages of {individuals:,} individuals")


def build_matches(connection):
    """One row per individual with the PolityMatch list of each stage, longest overlap first."""
    connection.execute(f"""
        CREATE OR REPLACE TEMP TABLE stage_polity AS
        SELECT qid, stage, start_year, end_year, certainty, location,
               {sql_map(METHOD_NAMES)}[method] || '_of_' || {sql_map(FIELD_NAMES)}[wikidata_field] AS assignation_method,
               coalesce({sql_map(NAME_FIXES)}[polity_name], polity_name) AS polity_name,
               years_spent_in_polity, rank
        FROM (
            SELECT stage_rows.*, unnest(polities) AS polity_name, unnest(polity_years) AS years_spent_in_polity, generate_subscripts(polities, 1) AS rank
            FROM stage_rows
        )
    """)
    connection.execute("""
        CREATE OR REPLACE TEMP TABLE polity_years AS
        SELECT cliopatria_id, name, world, meta_polities,
               list_transform(territories, territory -> {'start_year': territory.start_year, 'end_year': territory.end_year}) AS territory_years
        FROM polity
    """)
    unmatched = connection.execute("SELECT list(DISTINCT polity_name) FROM stage_polity ANTI JOIN polity_years ON polity_years.name = stage_polity.polity_name").fetchone()[0]
    assert not unmatched, f"polities missing from the polity table: {unmatched}"
    connection.execute(f"""
        CREATE OR REPLACE TEMP TABLE life_stage_polities (qid VARCHAR, {", ".join(f"{column} {MATCH_LIST_TYPE}" for column in STAGE_COLUMNS.values())}, active_life_ongoing BOOLEAN)
    """)
    for bucket in tqdm(range(BATCHES), desc="match batches"):
        build_bucket(connection, bucket)
    rows, active, unique, ongoing = connection.execute("SELECT count(*), count(*) FILTER (len(active_life_polity) > 0), count(DISTINCT qid), count(*) FILTER (active_life_ongoing) FROM life_stage_polities").fetchone()
    individuals = connection.execute("SELECT count(DISTINCT qid) FROM stage_rows").fetchone()[0]
    assert rows == unique == individuals, f"{rows:,} rows, {unique:,} qids, {individuals:,} individuals"
    report(f"{rows:,} individuals, {active:,} with an active-life polity, {ongoing:,} with an ongoing active life")
    rows = [{"column_name": column, "provenance": as_json(e.provenance())} for column, e in ENRICHMENTS.items()]
    stage(connection, "polity_provenance", {"column_name": "VARCHAR", "provenance": duck_type(D.Provenance)}, rows)


def build_bucket(connection, bucket):
    """The polity matches of one hash bucket of individuals (the whole set at once does not fit in memory)."""
    in_bucket = f"hash(qid) % {BATCHES} = {bucket}"
    connection.execute(f"""
        CREATE OR REPLACE TEMP TABLE stage_matches AS
        WITH candidates AS (
            SELECT stage_polity.*, polity_years.cliopatria_id, polity_years.world, polity_years.meta_polities,
                   len(list_filter(polity_years.territory_years, territory -> territory.start_year <= coalesce(stage_polity.end_year, territory.start_year) AND territory.end_year >= stage_polity.start_year)) > 0 AS stage_overlap
            FROM stage_polity
            JOIN polity_years ON polity_years.name = stage_polity.polity_name
            WHERE hash(stage_polity.qid) % {BATCHES} = {bucket}
            QUALIFY row_number() OVER (PARTITION BY stage_polity.qid, stage_polity.stage, stage_polity.polity_name ORDER BY stage_overlap DESC, polity_years.cliopatria_id) = 1
        )
        SELECT qid, stage,
               CAST(list({{
                   'polity': {{
                       'cliopatria_id': cliopatria_id, 'name': polity_name, 'meta_polities': meta_polities, 'child_polities': [],
                       'existence_wikidata': NULL, 'entity': NULL, 'sitelink': NULL, 'territories': [], 'world': world, 'field_provenance': MAP {{}}
                   }},
                   'years_spent_in_polity': years_spent_in_polity,
                   'assignation_method': assignation_method,
                   'certainty': certainty,
                   'location': location,
                   'seshat': []
               }} ORDER BY years_spent_in_polity DESC, rank) AS {MATCH_LIST_TYPE}) AS matches
        FROM candidates
        GROUP BY qid, stage
    """)
    connection.execute(f"""
        INSERT INTO life_stage_polities
        SELECT qid,
               {", ".join(f"coalesce(list(matches) FILTER (WHERE stage = '{name}')[1], []::{MATCH_LIST_TYPE}) AS {column}" for name, column in STAGE_COLUMNS.items())},
               any_value(active_life_ongoing) AS active_life_ongoing
        FROM (SELECT qid, bool_or(end_year IS NULL) FILTER (WHERE stage = 'active') AS active_life_ongoing FROM stage_rows WHERE {in_bucket} GROUP BY qid)
        LEFT JOIN stage_matches USING (qid)
        GROUP BY qid
    """)
    connection.execute("DROP TABLE stage_matches")


NEW_VALUES = {
    **{column: f"coalesce(life_stage_polities.{column}, []::{MATCH_LIST_TYPE})" for column in STAGE_COLUMNS.values()},
    "main_polity": "life_stage_polities.active_life_polity[1]",
    "active_life_ongoing": "life_stage_polities.active_life_ongoing",
    "field_provenance": "map_concat(coalesce(previous.field_provenance, MAP {}), (SELECT map_from_entries(list((polity_provenance.column_name, polity_provenance.provenance))) FROM polity_provenance))",
}


def persist_matches(connection):
    """Move the matches to a parquet on disk so the rebuild does not hold them in memory."""
    path = SCRATCH / "life_stage_polities.parquet"
    connection.execute(f"COPY life_stage_polities TO '{path}' (FORMAT parquet)")
    connection.execute("DROP TABLE life_stage_polities")
    connection.execute(f"CREATE TEMP VIEW life_stage_polities AS SELECT * FROM read_parquet('{path}')")
    report(f"matches written to {path}")


def select_list(existing):
    values = []
    for column, kind in columns_of(D.IndividualEnriched).items():
        value = NEW_VALUES.get(column, f'previous."{column}"' if column in existing else "NULL")
        values.append(f'CAST({value} AS {kind}) AS "{column}"')
    return ",\n       ".join(values)


def rebuild(connection):
    """Write the new table in qid ranges (the whole table at once does not fit in memory), then put it in place of the old one."""
    existing = [row[0] for row in connection.execute(f"DESCRIBE {TABLE}").fetchall()]
    extra = set(existing) - set(columns_of(D.IndividualEnriched))
    assert not extra, f"{TABLE} has columns outside the datamodel: {extra}"
    cuts = connection.execute(f"SELECT quantile_disc(entity.qid, {[i / REBUILD_RANGES for i in range(1, REBUILD_RANGES)]}) FROM individual").fetchone()[0]
    ranges = list(zip([None, *cuts], [*cuts, None]))
    connection.execute(f"DROP TABLE IF EXISTS {NEW_TABLE}")
    for number, (low, high) in enumerate(tqdm(ranges, desc="qid ranges")):
        inside = " AND ".join([f"individual.entity.qid >= '{low}'"] * (low is not None) + [f"individual.entity.qid < '{high}'"] * (high is not None))
        rows = f"""
            SELECT {select_list(existing)}
            FROM individual
            LEFT JOIN life_stage_polities ON life_stage_polities.qid = individual.entity.qid
            LEFT JOIN {TABLE} AS previous ON previous.entity.qid = individual.entity.qid
            WHERE {inside}
            ORDER BY individual.entity.qid
        """
        connection.execute(f"CREATE TABLE {NEW_TABLE} AS {rows}" if number == 0 else f"INSERT INTO {NEW_TABLE} {rows}")
        report(f"qid range {number + 1}/{len(ranges)} written")
    connection.execute(f"DROP TABLE {TABLE}")
    connection.execute(f"ALTER TABLE {NEW_TABLE} RENAME TO {TABLE}")


def check(connection, before):
    individuals = connection.execute("SELECT count(*) FROM individual").fetchone()[0]
    rows, pre, active, post, main, births, starts, ongoing = connection.execute(f"""
        SELECT count(*), count(*) FILTER (len(pre_active_life_polity) > 0), count(*) FILTER (len(active_life_polity) > 0),
               count(*) FILTER (len(post_active_life_polity) > 0), count(main_polity), count(birth_date), count(start_of_active_life),
               count(*) FILTER (active_life_ongoing)
        FROM {TABLE}
    """).fetchone()
    assert rows == individuals, f"{TABLE} has {rows:,} rows for {individuals:,} individuals"
    assert (births, starts) == before, f"dates changed: {(births, starts)} instead of {before}"
    expected = connection.execute("SELECT count(*) FROM life_stage_polities WHERE len(active_life_polity) > 0").fetchone()[0]
    assert active == expected == main, f"{active:,} active-life polities and {main:,} main polities written, {expected:,} expected"
    expected = connection.execute("SELECT count(*) FILTER (active_life_ongoing) FROM life_stage_polities").fetchone()[0]
    assert ongoing == expected, f"{ongoing:,} ongoing active lives written, {expected:,} expected"
    report(f"{rows:,} individuals: {pre:,} with a pre-active, {active:,} with an active, {post:,} with a post-active polity, {ongoing:,} with an ongoing active life")


def main():
    parser = argparse.ArgumentParser(description="Ingest the life-stage polities into individual_enriched.")
    parser.add_argument("--sample", action="store_true", help=f"build the matches of {SAMPLE_SIZE:,} individuals, write nothing")
    sample = parser.parse_args().sample
    for e in ENRICHMENTS.values():
        e.announce()
    started = time.time()
    connection = open_database(read_only=sample)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit='8GB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{SCRATCH}'")
    load_stage_rows(connection, sample)
    build_matches(connection)
    if sample:
        print(connection.execute("SELECT qid, active_life_polity[1] FROM life_stage_polities WHERE len(active_life_polity) > 1 LIMIT 1").fetchone())
        print(connection.execute("SELECT qid, active_life_ongoing, list_transform(active_life_polity, m -> m.polity.name) FROM life_stage_polities WHERE active_life_ongoing LIMIT 3").fetchall())
        return
    persist_matches(connection)
    report(f"writing {TABLE} of {DATABASE}")
    before = connection.execute(f"SELECT count(birth_date), count(start_of_active_life) FROM {TABLE}").fetchone()
    connection.execute("BEGIN TRANSACTION")
    rebuild(connection)
    check(connection, before)
    connection.execute("COMMIT")
    connection.close()
    report(f"done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
