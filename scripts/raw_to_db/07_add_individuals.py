import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import raw_file_readers
import raw_to_duckdb_models
import json_to_raw_models
from duckdb_table_writer import Table

STEP = "07 individuals"


def every_individual():
    return sorted(raw_file_readers.items(raw_file_readers.INDIVIDUAL_IDS, "item"))


def main():
    connection = build_helpers.open_database()
    qids = build_helpers.limited(every_individual())
    total = len(qids)
    build_helpers.report(STEP, f"{total:,} individuals in {-(-total // build_helpers.CHUNK)} chunks of {build_helpers.CHUNK:,}")

    individual = Table(connection, "individual", datamodel_in_duckdb.Individual)
    identifier = Table(connection, "individual_identifier", datamodel_in_duckdb.IndividualIdentifier)
    sitelink = Table(connection, "individual_sitelink", datamodel_in_duckdb.IndividualSitelink)
    credit = Table(connection, "individual_work", datamodel_in_duckdb.IndividualWork)
    tables = [individual, identifier, sitelink, credit]
    sites = set()

    for number, batch in enumerate(build_helpers.chunks(qids), start=1):
        for raw in json_to_raw_models.individuals(batch):
            sites.update(link.site for link in raw.sitelink if link.site)
            one = raw_to_duckdb_models.individual(raw)
            individual.add(one)
            identifier.extend(one.external_id)
            sitelink.extend(one.sitelink)
            credit.extend(one.work)
        for table in tables:
            table.flush()
        build_helpers.check_disk()
        build_helpers.report(STEP, f"chunk {number}: {individual.count:,}/{total:,} individuals, {credit.count:,} work credits")

    with Table(connection, "sitelink", datamodel_in_duckdb.Sitelink) as sites_table:
        sites_table.extend(raw_to_duckdb_models.sitelink(site) for site in sorted(sites))
    Table(connection, "individual_enriched", datamodel_in_duckdb.IndividualEnriched)

    build_helpers.done(STEP, tables + [sites_table])
    connection.close()


if __name__ == "__main__":
    main()
