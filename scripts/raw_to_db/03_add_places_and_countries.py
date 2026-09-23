import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_file_readers
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "03 places"

PLACE_FILES = (raw_file_readers.PLACE_LOCATION, raw_file_readers.PLACE_INSTANCE_OF, raw_file_readers.PLACE_INCEPTION, raw_file_readers.PLACE_DISSOLUTION)
COUNTRY_FILES = (raw_file_readers.COUNTRY_LOCATION, raw_file_readers.COUNTRY_OF_PLACE, raw_file_readers.COUNTRY_MODERN, raw_file_readers.COUNTRY_SITELINK)


def qids_across(paths):
    found = set()
    for path in paths:
        found.update(build_helpers.keys_of(path))
    return found


def main():
    connection = build_helpers.open_database()
    countries = qids_across(COUNTRY_FILES)
    places = qids_across(PLACE_FILES) - countries
    build_helpers.report(STEP, f"{len(places):,} places and {len(countries):,} countries")

    with Table(connection, "place", datamodel_in_duckdb.Place) as table:
        table.extend(raw_to_duckdb_models.country(raw) for raw in json_to_raw_models.countries(build_helpers.limited(sorted(countries))))
        for batch in build_helpers.chunks(build_helpers.limited(sorted(places))):
            table.extend(raw_to_duckdb_models.place(raw) for raw in json_to_raw_models.places(batch))
            build_helpers.check_disk()
            build_helpers.report(STEP, f"{table.count + len(table.pending):,} places written")

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
