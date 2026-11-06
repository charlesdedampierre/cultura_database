"""Put each occupation in a Cross-Verified level-1 domain, from the language-model classification of its label saved in data/ai_outputs/meta_occupation.json."""

from common import D, Enrichment, R, ai_run, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of

ANSWERS, RUN = ai_run("meta_occupation", R.MetaOccupationRun)

ENRICHMENT = Enrichment(
    reads=("Occupation.entity",),
    writes=("Occupation.meta_occupation",),
    rule="A language model was shown each labelled occupation, its label alone, and asked which Cross-Verified level-1 domain it belongs to: Culture, Discovery/Science, Leadership, Sports/Games or Other, with the level-2 domains of Laouenan et al. (2022) as the rules for each. Occupations without a label were not shown and stay empty.",
    answers=ANSWERS,
    prompt_id=RUN.prompt_id,
    model_name=RUN.model_name,
)


def add_columns(connection):
    """The non-enriched database predates the field: add it to the occupation table and to the Occupation struct nested in individual.occupation, where it stays empty as the labels do."""
    if "meta_occupation" not in {row[0] for row in connection.execute("DESCRIBE occupation").fetchall()}:
        connection.execute("ALTER TABLE occupation ADD COLUMN meta_occupation VARCHAR")
    nested = columns_of(D.Individual)["occupation"]
    current = connection.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_name = 'individual' AND column_name = 'occupation'"
    ).fetchone()[0]
    if "meta_occupation" not in current:
        print("adding meta_occupation to the occupations nested in individual, a rewrite of that column")
        connection.execute(f"ALTER TABLE individual ALTER occupation SET DATA TYPE {nested}")


def main():
    ENRICHMENT.announce()
    connection = open_database()
    add_columns(connection)

    rows = [{"qid": answer.qid, "meta_occupation": answer.meta_occupation} for answer in RUN.answers]
    stage(connection, "answer", {"qid": "VARCHAR", "meta_occupation": "VARCHAR"}, rows)
    stage(connection, "provenance", {"value": provenance_column()}, [{"value": as_json(ENRICHMENT.provenance())}])

    connection.execute(
        """
        UPDATE occupation SET
            meta_occupation = answer.meta_occupation,
            field_provenance = map_concat(field_provenance, MAP {'meta_occupation': provenance.value})
        FROM answer, provenance WHERE occupation.entity.qid = answer.qid
        """
    )

    print()
    print(connection.execute(
        "SELECT coalesce(meta_occupation, 'empty') AS meta_occupation, count(*) AS occupations FROM occupation GROUP BY 1 ORDER BY 2 DESC"
    ).pl())
    connection.close()


if __name__ == "__main__":
    main()
