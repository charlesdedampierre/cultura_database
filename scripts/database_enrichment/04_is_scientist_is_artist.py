import json

from common import Enrichment, ROOT, as_json, open_database, provenance_column, stage

ANSWERS = ROOT / "data" / "raw_data_from_wikidata" / "suboccupations_scientist_artist.json"

ENRICHMENT = Enrichment(
    reads=("Individual.occupation",),
    writes=("Individual.is_scientist", "Individual.is_artist"),
    rule="True when any of the individual's occupations is the root occupation itself or descends from it through Wikidata's subclass tree. The tree was walked once and the descendants saved, 2 562 under scientist (Q901) and 1 786 under artist (Q483501), so nothing is walked here. An individual with no occupation at all gets neither flag.",
    answers=ANSWERS,
)

ROOTS = {"is_scientist": "scientist", "is_artist": "artist"}


def descendants():
    with ANSWERS.open() as handle:
        saved = json.load(handle)
    return {
        column: {saved[name]["root_qid"], *saved[name]["suboccupations"]}
        for column, name in ROOTS.items()
    }


def main():
    ENRICHMENT.announce()
    families = descendants()
    for column, family in families.items():
        print(f"{len(family):,} occupations count as {column.removeprefix('is_')}")

    connection = open_database()
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
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(ENRICHMENT.provenance())}])

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
    connection.close()


if __name__ == "__main__":
    main()
