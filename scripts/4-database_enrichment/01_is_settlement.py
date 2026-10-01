"""Mark each place as a settlement or not, from the language-model classification of its Wikidata classes saved in entity_type_classification.json."""

import json
import sys
from pathlib import Path

from common import Enrichment, ROOT, as_json, open_database, provenance_column, stage

ENRICHMENT = Enrichment(
    reads=("Place.instance_of",),
    writes=("Place.is_settlement",),
    rule="A language model was shown each Wikidata class a place is an instance of, with its label, and asked whether the class denotes a populated place rather than an administrative region, a building or a natural feature. A place is a settlement when any of its classes is one. The model read the classes, never the places, so every place of the same classes gets the same answer.",
    answers=ROOT / "data" / "raw_data_from_wikidata" / "entity_type_classification.json",
    prompt_id="urban_settlement",
)


def settlement_classes():
    with ENRICHMENT.answers.open() as handle:
        answered = json.load(handle)
    return {qid for qid, entry in answered.items() if entry.get("urban_settlement")}


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
