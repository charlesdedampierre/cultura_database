"""Flag each individual as a scientist and/or an artist from their occupations, and as probably fictional when a place they are tied to is fictional."""

import json
import re

from common import Enrichment, ROOT, as_json, open_database, provenance_column, stage

OCCUPATION_ANSWERS = ROOT / "data" / "raw_data_from_wikidata" / "suboccupations_scientist_artist.json"

SCIENTIST_ARTIST = Enrichment(
    reads=("Individual.occupation",),
    writes=("Individual.is_scientist", "Individual.is_artist"),
    rule="True when any of the individual's occupations is the root occupation itself or descends from it through Wikidata's subclass tree. The tree was walked once and the descendants saved, 2 562 under scientist (Q901) and 1 786 under artist (Q483501), so nothing is walked here. An individual with no occupation at all gets neither flag.",
    answers=OCCUPATION_ANSWERS,
)

ROOTS = {"is_scientist": "scientist", "is_artist": "artist"}

PLACE_ANSWERS = ROOT / "data" / "raw_data_from_wikidata" / "city_entity_types.json"
FICTIONAL = re.compile(r"fiction|myth|legend|imaginary|hypothetical", re.IGNORECASE)

IS_HUMAN = Enrichment(
    reads=("Individual.place_of_birth", "Individual.place_of_death", "Individual.country_of_citizenship", "Place.instance_of"),
    writes=("Individual.is_human",),
    rule="False when any place the individual is tied to — birthplace, deathplace, country of citizenship — is itself fictional, which is read off the labels of that place's Wikidata classes matching fiction, myth, legend, imaginary or hypothetical. It is a test of the places, not of the person: someone born in a fictional city is taken to be a fictional character. Everyone else is True, including anyone tied to no place at all, so a False is evidence and a True is only the absence of it.",
    answers=PLACE_ANSWERS,
)


def descendants():
    with OCCUPATION_ANSWERS.open() as handle:
        saved = json.load(handle)
    return {
        column: {saved[name]["root_qid"], *saved[name]["suboccupations"]}
        for column, name in ROOTS.items()
    }


def fill_scientist_artist(connection):
    SCIENTIST_ARTIST.announce()
    families = descendants()
    for column, family in families.items():
        print(f"{len(family):,} occupations count as {column.removeprefix('is_')}")

    people = connection.execute(
        "SELECT entity.qid, list_transform(occupation, o -> o.entity.qid) FROM individual WHERE len(occupation) > 0"
    ).fetchall()

    rows = [
        {
            "qid": qid,
            "is_scientist": any(o in families["is_scientist"] for o in occupations),
            "is_artist": any(o in families["is_artist"] for o in occupations),
        }
        for qid, occupations in people
    ]
    stage(connection, "answer", {"qid": "VARCHAR", "is_scientist": "BOOLEAN", "is_artist": "BOOLEAN"}, rows)
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(SCIENTIST_ARTIST.provenance())}])

    connection.execute(
        """
        UPDATE individual SET
            is_scientist = answer.is_scientist,
            is_artist = answer.is_artist,
            field_provenance = map_concat(
                individual.field_provenance,
                MAP {'is_scientist': provenance.value, 'is_artist': provenance.value}
            )
        FROM answer, provenance WHERE individual.entity.qid = answer.qid
        """
    )

    scientists, artists, decided, total = connection.execute(
        "SELECT count(*) FILTER (is_scientist), count(*) FILTER (is_artist), count(is_scientist), count(*) FROM individual"
    ).fetchone()
    print(f"\ndecided on {decided:,} of {total:,} individuals: {scientists:,} scientists, {artists:,} artists")


def fictional_classes():
    with PLACE_ANSWERS.open() as handle:
        typed = json.load(handle)
    labels = {t["id"]: t["label"] for entry in typed.values() for t in entry.get("types", ())}
    return {qid for qid, label in labels.items() if FICTIONAL.search(label or "")}


def fill_is_human(connection):
    IS_HUMAN.announce()
    classes = fictional_classes()
    print(f"{len(classes)} place classes match the fictional vocabulary")

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
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(IS_HUMAN.provenance())}])

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
    print(f"\n{places} places are fictional")
    print(f"individual.is_human set on {total:,} individuals; {not_human:,} are False")


def main():
    connection = open_database()
    fill_scientist_artist(connection)
    print()
    fill_is_human(connection)
    connection.close()


if __name__ == "__main__":
    main()
