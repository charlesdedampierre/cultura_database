"""Mark each place as a settlement or not, from the language-model classification of its Wikidata classes saved in data/ai_outputs/urban_settlement.json."""

from common import Enrichment, R, ai_run, as_json, open_database, provenance_column, stage

ANSWERS, RUN = ai_run("urban_settlement", R.SettlementClassificationRun)

ENRICHMENT = Enrichment(
    reads=("Place.instance_of",),
    writes=("Place.is_settlement",),
    rule="A language model was shown each Wikidata class a place is an instance of, with its label, and asked whether the class denotes a populated place rather than an administrative region, a building or a natural feature. A place is a settlement when any of its classes is one. The model read the classes, never the places, so every place of the same classes gets the same answer.",
    answers=ANSWERS,
    prompt_id=RUN.prompt_id,
    model_name=RUN.model_name,
)


def settlement_classes():
    return {answer.qid for answer in RUN.answers if answer.urban_settlement}


def main():
    ENRICHMENT.announce()
    classes = settlement_classes()
    print(f"{len(classes):,} classes the model called a populated place")

    connection = open_database()
    places = connection.execute(
        "SELECT entity.qid AS qid, list_transform(instance_of, c -> c.qid) AS classes FROM place"
    ).fetchall()

    decided = [
        {"qid": qid, "is_settlement": any(c in classes for c in (found or []))}
        for qid, found in places
        if found
    ]
    stage(connection, "answer", {"qid": "VARCHAR", "is_settlement": "BOOLEAN"}, decided)
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(ENRICHMENT.provenance())}])

    connection.execute(
        """
        UPDATE place SET
            is_settlement = answer.is_settlement,
            field_provenance = map_concat(field_provenance, MAP {'is_settlement': provenance.value})
        FROM answer, provenance WHERE place.entity.qid = answer.qid
        """
    )

    settled, total = connection.execute(
        "SELECT count(*) FILTER (is_settlement), count(*) FROM place"
    ).fetchone()
    without = connection.execute("SELECT count(*) FROM place WHERE is_settlement IS NULL").fetchone()[0]
    print(f"\nplace.is_settlement set on {total - without:,} of {total:,} places; {settled:,} are settlements")
    connection.close()


if __name__ == "__main__":
    main()
