import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_file_readers
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "04 occupations"


def main():
    connection = build_helpers.open_database()
    qids = build_helpers.limited(build_helpers.keys_of(raw_file_readers.OCCUPATION_LABEL))
    build_helpers.report(STEP, f"{len(qids):,} occupations")

    with Table(connection, "occupation", datamodel_in_duckdb.Occupation) as table:
        table.extend(raw_to_duckdb_models.occupation(raw) for raw in json_to_raw_models.occupations(qids))

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
