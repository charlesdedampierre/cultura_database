"""Last enrichment step: remove the individuals flagged as fictional (individual.is_human = False, step 04) from every table keyed by an individual."""

from common import Enrichment, open_database

TABLES = {
    "individual": "individual.entity.qid",
    "individual_enriched": "individual_enriched.entity.qid",
    "individual_identifier": "individual_identifier.qid",
    "individual_sitelink": "individual_sitelink.qid",
    "individual_work": "individual_work.qid",
}

ENRICHMENT = Enrichment(
    reads=("Individual.is_human",),
    writes=tuple(f"{table} (rows removed)" for table in TABLES),
    rule="Every individual whose is_human is False, i.e. tied to a place Wikidata types as fictional, mythical or hypothetical (step 04), is deleted with all their rows. Works, places and occupations are kept.",
    answers=None,
)


def main():
    ENRICHMENT.announce()
    connection = open_database()
    connection.execute("CREATE OR REPLACE TEMP TABLE fictional AS SELECT individual.entity.qid AS qid FROM individual WHERE NOT individual.is_human")
    fictional = connection.execute("SELECT count(*) FROM fictional").fetchone()[0]
    print(f"{fictional:,} individuals flagged as fictional")
    for table, key in TABLES.items():
        removed = connection.execute(f"DELETE FROM {table} WHERE {key} IN (SELECT qid FROM fictional)").fetchone()[0]
        print(f"   {table}: {removed:,} rows removed")
    print(f"\n{connection.execute('SELECT count(*) FROM individual').fetchone()[0]:,} individuals left")
    connection.close()


if __name__ == "__main__":
    main()
