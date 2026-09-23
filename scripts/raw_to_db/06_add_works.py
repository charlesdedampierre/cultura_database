import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_file_readers
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "06 works"

FILES = (raw_file_readers.WORK_LABEL, raw_file_readers.WORK_INSTANCE_OF, raw_file_readers.WORK_INCEPTION, raw_file_readers.WORK_PUBLICATION_DATE)


def every_work():
    found = set()
    for path in FILES:
        before = len(found)
        found.update(key for key, _ in raw_file_readers.pairs_until_truncated(path))
        build_helpers.report(STEP, f"{path.name}: {len(found) - before:,} new, {len(found):,} works so far")
    return sorted(found)


def main():
    connection = build_helpers.open_database()
    qids = build_helpers.limited(every_work())
    build_helpers.report(STEP, f"{len(qids):,} works in {-(-len(qids) // build_helpers.CHUNK)} chunks of {build_helpers.CHUNK:,}")

    with Table(connection, "work", datamodel_in_duckdb.Work) as table:
        for number, batch in enumerate(build_helpers.chunks(qids), start=1):
            table.extend(raw_to_duckdb_models.work(raw) for raw in json_to_raw_models.works(batch))
            table.flush()
            build_helpers.check_disk()
            build_helpers.report(STEP, f"chunk {number}: {table.count:,} works written")

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
