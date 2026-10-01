import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "01 properties"


def main():
    connection = build_helpers.open_database()
    raw = build_helpers.limited(json_to_raw_models.properties())
    build_helpers.report(STEP, f"{len(raw):,} properties")

    with Table(connection, "wikidata_property", datamodel_in_duckdb.WikidataProperty) as table:
        table.extend(raw_to_duckdb_models.wikidata_property(one) for one in raw)

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
