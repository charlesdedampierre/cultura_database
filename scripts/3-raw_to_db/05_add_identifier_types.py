import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_file_readers
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "05 identifiers"


def main():
    connection = build_helpers.open_database()
    pids = build_helpers.limited(sorted({p["property_id"] for p in raw_file_readers.items(raw_file_readers.EXTERNAL_ID_PROPERTY, "properties.item")}))
    build_helpers.report(STEP, f"{len(pids):,} external-id properties")

    with Table(connection, "identifier", datamodel_in_duckdb.Identifier) as table:
        table.extend(raw_to_duckdb_models.identifier(raw) for raw in json_to_raw_models.external_id_properties(pids))

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
