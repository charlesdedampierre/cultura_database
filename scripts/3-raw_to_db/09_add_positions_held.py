"""Add the positions held (P39) of `individual`: one PositionHeld per non-deprecated
statement, with the position's name and the statement's start and end dates.

Runs on the database at build_helpers.DATABASE (CULTURA_DB), after 08 in a full
build or on its own to bring an existing database up to date: the column is
dropped and written again, so a rerun replaces what a previous run wrote."""
import sys
from pathlib import Path

from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import json_to_raw_models
import raw_file_readers
import raw_to_duckdb_models
from duckdb_table_writer import Table
from pydantic_to_duckdb_schema import columns_of, duck_type

STEP = "09 positions held"
PROVENANCE = duck_type(datamodel_in_duckdb.Provenance)
MEMORY_LIMIT = "6GB"
RULE = "One per non-deprecated statement, in Wikidata's order, with the statement's start time (P580) and end time (P582) qualifiers."


class HeldPositions(BaseModel):
    qid: str
    value: tuple[datamodel_in_duckdb.PositionHeld, ...] = ()


def position_held(value, labels):
    return datamodel_in_duckdb.PositionHeld(
        position=raw_to_duckdb_models.entity(value.value, labels.get(value.value)),
        start_date=raw_to_duckdb_models.date(value.start_time, value.start_time_precision, "QualifiedValue.start_time", "QualifiedValue.start_time_precision"),
        end_date=raw_to_duckdb_models.date(value.end_time, value.end_time_precision, "QualifiedValue.end_time", "QualifiedValue.end_time_precision"),
    )


def main():
    connection = build_helpers.open_database()
    connection.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    labels = json_to_raw_models.life_location_labels()
    present = {qid for (qid,) in connection.execute("SELECT entity.qid FROM individual").fetchall()}
    build_helpers.report(STEP, f"{len(present):,} individuals in {build_helpers.DATABASE.name}")
    statements = json_to_raw_models.qualified_values(raw_file_readers.POSITION_HELD)

    with Table(connection, "held_stage", HeldPositions) as stage:
        for qid, values in statements.items():
            kept = tuple(position_held(value, labels) for value in values if value.rank != "deprecated")
            if qid in present and kept:
                stage.add(HeldPositions(qid=qid, value=kept))

    kind = columns_of(datamodel_in_duckdb.Individual)["position_held"]
    provenance = datamodel_in_duckdb.Provenance(raw=("IndividualWikidata.position_held",), rule=RULE)
    connection.execute(f"CREATE OR REPLACE TEMP TABLE provenance_stage AS SELECT CAST(CAST(? AS JSON) AS {PROVENANCE}) AS value", [provenance.model_dump_json()])
    connection.execute("ALTER TABLE individual DROP COLUMN IF EXISTS position_held")
    connection.execute(f"ALTER TABLE individual ADD COLUMN position_held {kind} DEFAULT []")
    connection.execute(
        """
        UPDATE individual SET
            position_held = held_stage.value,
            field_provenance = map_concat(field_provenance, MAP {'position_held': provenance_stage.value})
        FROM held_stage, provenance_stage WHERE individual.entity.qid = held_stage.qid
        """
    )
    connection.execute("DROP TABLE held_stage")

    held, positions, with_start, with_both = connection.execute(
        """
        SELECT count(DISTINCT entity.qid), count(*), count(*) FILTER (held.start_date IS NOT NULL),
               count(*) FILTER (held.start_date IS NOT NULL AND held.end_date IS NOT NULL)
        FROM (SELECT entity, unnest(position_held) AS held FROM individual)
        """
    ).fetchone()
    assert held == stage.count, f"{held:,} individuals with a position in the table, {stage.count:,} staged"
    build_helpers.report(STEP, f"individual.position_held: {held:,} individuals, {positions:,} positions, {with_start:,} with a start, {with_both:,} with a start and an end")
    build_helpers.report(STEP, f"done   db {build_helpers.DATABASE.stat().st_size / 1e9:.1f} GB   free {build_helpers.free_gb():.0f} GB")
    connection.close()


if __name__ == "__main__":
    main()
