"""Add the life locations: the places of work locations, residences and
institution locations missing from `place`, the `institution` table, and the four
life-location fields of `individual` (P937, P551, P108, P69); positions held (P39) are step 09.

Runs on the database at build_helpers.DATABASE (CULTURA_DB), after 07 in a full
build or on its own to bring an existing database up to date: every write
replaces what a previous run of this step wrote."""
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

STEP = "08 life locations"
PROVENANCE = duck_type(datamodel_in_duckdb.Provenance)
MEMORY_LIMIT = "6GB"

FIELDS = {
    "work_location": raw_file_readers.WORK_LOCATION,
    "residence": raw_file_readers.RESIDENCE,
    "employer": raw_file_readers.EMPLOYER,
    "educated_at": raw_file_readers.EDUCATED_AT,
}
PLACE_FIELDS = ("work_location", "residence")
INSTITUTION_FIELDS = ("employer", "educated_at")


class HeldPlaces(BaseModel):
    qid: str
    value: tuple[datamodel_in_duckdb.Place, ...] = ()


class HeldInstitutions(BaseModel):
    qid: str
    value: tuple[datamodel_in_duckdb.Institution, ...] = ()


def add_places(connection):
    known = {qid for (qid,) in connection.execute("SELECT entity.qid FROM place").fetchall()}
    with Table(connection, "place_stage", datamodel_in_duckdb.Place) as stage:
        stage.extend(raw_to_duckdb_models.place(raw) for raw in json_to_raw_models.life_location_places() if raw.qid not in known)
    connection.execute("INSERT INTO place BY NAME SELECT * FROM place_stage")
    connection.execute("DROP TABLE place_stage")
    build_helpers.report(STEP, f"{stage.count:,} places added to place")


def add_institutions(connection, qids, labels):
    with_coordinates = dict(connection.execute("SELECT entity.qid, entity.label_en FROM place WHERE coordinates.latitude IS NOT NULL").fetchall())
    with Table(connection, "institution", datamodel_in_duckdb.Institution) as table:
        table.extend(raw_to_duckdb_models.institution(raw, with_coordinates) for raw in json_to_raw_models.institutions(qids, labels))
    located = connection.execute("SELECT count(*) FROM institution WHERE location IS NOT NULL").fetchone()[0]
    build_helpers.report(STEP, f"{table.count:,} institutions, {located:,} with a location")


def held_row(field, qid, targets, labels):
    if field in PLACE_FIELDS:
        return HeldPlaces(qid=qid, value=tuple(datamodel_in_duckdb.Place(entity=raw_to_duckdb_models.entity(t, labels.get(t))) for t in targets))
    return HeldInstitutions(qid=qid, value=tuple(datamodel_in_duckdb.Institution(entity=raw_to_duckdb_models.entity(t, labels.get(t))) for t in targets))


def fill_field(connection, field, statements, labels, present):
    kind = columns_of(datamodel_in_duckdb.Individual)[field]
    connection.execute(f"ALTER TABLE individual ADD COLUMN IF NOT EXISTS {field} {kind}")
    model = HeldPlaces if field in PLACE_FIELDS else HeldInstitutions
    with Table(connection, "held_stage", model) as stage:
        for qid, values in statements.items():
            targets = raw_to_duckdb_models.held(values) if qid in present else ()
            if targets:
                stage.add(held_row(field, qid, targets, labels))
    provenance = datamodel_in_duckdb.Provenance(raw=(f"IndividualWikidata.{field}",), rule="Targets of the non-deprecated statements, once each, in Wikidata's order.")
    connection.execute(f"CREATE OR REPLACE TEMP TABLE provenance_stage AS SELECT CAST(CAST(? AS JSON) AS {PROVENANCE}) AS value", [provenance.model_dump_json()])
    connection.execute(f"UPDATE individual SET {field} = [] WHERE {field} IS NULL OR (len({field}) > 0 AND entity.qid NOT IN (SELECT qid FROM held_stage))")
    connection.execute(
        f"""
        UPDATE individual SET
            {field} = held_stage.value,
            field_provenance = map_concat(field_provenance, MAP {{'{field}': provenance_stage.value}})
        FROM held_stage, provenance_stage WHERE individual.entity.qid = held_stage.qid
        """
    )
    connection.execute("DROP TABLE held_stage")
    build_helpers.report(STEP, f"individual.{field}: {stage.count:,} individuals")


def main():
    connection = build_helpers.open_database()
    connection.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")
    labels = json_to_raw_models.life_location_labels()
    present = {qid for (qid,) in connection.execute("SELECT entity.qid FROM individual").fetchall()}
    build_helpers.report(STEP, f"{len(present):,} individuals in {build_helpers.DATABASE.name}")
    add_places(connection)

    institutions = set()
    for field, path in FIELDS.items():
        statements = json_to_raw_models.qualified_values(path)
        if field in INSTITUTION_FIELDS:
            institutions.update(target for qid, values in statements.items() if qid in present for target in raw_to_duckdb_models.held(values))
        fill_field(connection, field, statements, labels, present)
        build_helpers.check_disk()
    add_institutions(connection, sorted(institutions), labels)

    build_helpers.report(STEP, f"done   db {build_helpers.DATABASE.stat().st_size / 1e9:.1f} GB   free {build_helpers.free_gb():.0f} GB")
    connection.close()


if __name__ == "__main__":
    main()
