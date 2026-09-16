import json
import re

from common import Enrichment, ROOT, as_json, open_database, provenance_column, stage

ANSWERS = ROOT / "data" / "raw_data_from_wikidata" / "city_entity_types.json"
FICTIONAL = re.compile(r"fiction|myth|legend|imaginary|hypothetical", re.IGNORECASE)

ENRICHMENT = Enrichment(
    reads=("Individual.place_of_birth", "Individual.place_of_death", "Individual.country_of_citizenship", "Place.instance_of"),
    writes=("Individual.is_human",),
    rule="False when any place the individual is tied to — birthplace, deathplace, country of citizenship — is itself fictional, which is read off the labels of that place's Wikidata classes matching fiction, myth, legend, imaginary or hypothetical. It is a test of the places, not of the person: someone born in a fictional city is taken to be a fictional character. Everyone else is True, including anyone tied to no place at all, so a False is evidence and a True is only the absence of it.",
    answers=ANSWERS,
)


def fictional_classes():
    with ANSWERS.open() as handle:
        typed = json.load(handle)
    labels = {t["id"]: t["label"] for entry in typed.values() for t in entry.get("types", ())}
    return {qid for qid, label in labels.items() if FICTIONAL.search(label or "")}


def main():
    ENRICHMENT.announce()
    classes = fictional_classes()
    print(f"{len(classes)} place classes match the fictional vocabulary")

    connection = open_database()
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE fictional_class AS SELECT unnest(?::VARCHAR[]) AS qid",
        [sorted(classes)],
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE fictional_place AS
        SELECT DISTINCT place.entity.qid AS qid
        FROM place, unnest(place.instance_of) AS t(class)
        JOIN fictional_class ON fictional_class.qid = class.qid
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE tie AS
        SELECT entity.qid AS qid, place_of_birth.entity.qid AS place FROM individual
        UNION ALL
        SELECT entity.qid, place_of_death.entity.qid FROM individual
        UNION ALL
        SELECT entity.qid, citizenship.entity.qid FROM individual, unnest(country_of_citizenship) AS t(citizenship)
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE answer AS
        SELECT individual.entity.qid AS qid,
               NOT EXISTS (SELECT 1 FROM tie JOIN fictional_place ON fictional_place.qid = tie.place
                           WHERE tie.qid = individual.entity.qid) AS is_human
        FROM individual
        """
    )
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(ENRICHMENT.provenance())}])

    connection.execute(
        """
        UPDATE individual SET
            is_human = answer.is_human,
            field_provenance = map_concat(individual.field_provenance, MAP {'is_human': provenance.value})
        FROM answer, provenance WHERE individual.entity.qid = answer.qid
        """
    )

    places = connection.execute("SELECT count(*) FROM fictional_place").fetchone()[0]
    not_human, total = connection.execute(
        "SELECT count(*) FILTER (NOT is_human), count(*) FROM individual"
    ).fetchone()
    print(f"\n{places} of the sample's places are fictional")
    print(f"individual.is_human set on {total:,} individuals; {not_human:,} are False")
    connection.close()


if __name__ == "__main__":
    main()
