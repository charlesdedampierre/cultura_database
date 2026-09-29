import duckdb

from common import D, Enrichment, ROOT, as_json, open_database, stage
from pydantic_to_duckdb_schema import duck_type

ENRICHMENT = Enrichment(
    reads=("Individual.entity",),
    writes=("Individual.birth_date[]", "Individual.death_date[]", "Individual.floruit_date[]"),
    rule="A language model was given the individual's English Wikipedia article and asked for the year they were born, died and were at work. Its answers were saved as three columns and are appended here as one more entry in each date list, beside the Wikidata property and the other sources. A bare year is taken as a year-precision date; an answer giving a range rather than a year is left out, since a Date holds one year and nothing wider.",
    answers=ROOT / "data" / "cultura" / "humans_clean.duckdb",
    prompt_id="wikipedia_dates",
)

COLUMNS = {
    "birth_date": "birthdate_from_wikipedia",
    "death_date": "deathdate_from_wikipedia",
    "floruit_date": "floruit_from_wikipedia",
}


def a_year(answer):
    text = str(answer or "").strip()
    return int(text) if text.lstrip("-").isdigit() else None


def a_date(answer, provenance):
    year = a_year(answer)
    if year is None:
        return None
    return D.Date(
        iso=None,
        year=year,
        precision="year",
        field_provenance={field: provenance for field in ("year", "precision")},
    )


def main():
    ENRICHMENT.announce()
    connection = open_database()
    qids = [r[0] for r in connection.execute("SELECT entity.qid FROM individual").fetchall()]

    saved = duckdb.connect(str(ENRICHMENT.answers), read_only=True)
    saved.execute("CREATE OR REPLACE TEMP TABLE picked AS SELECT unnest(?::VARCHAR[]) AS wikidata_id", [qids])
    columns = ", ".join(COLUMNS.values())
    answered = saved.execute(
        f"SELECT wikidata_id, {columns} FROM individuals JOIN picked USING (wikidata_id)"
    ).fetchall()
    saved.close()

    provenance = ENRICHMENT.provenance()
    rows, offered, unparsed = [], 0, 0
    for qid, *values in answered:
        entry = {"qid": qid}
        for field, value in zip(COLUMNS, values):
            if value is not None:
                offered += 1
            found = a_date(value, provenance)
            if value is not None and found is None:
                unparsed += 1
            entry[field] = as_json(found) if found else None
        if any(entry[field] for field in COLUMNS):
            rows.append(entry)

    print(f"{len(answered):,} of the {len(qids):,} individuals are in the saved answers")
    print(f"{offered:,} answers given by the model, {unparsed:,} of them a range rather than a year")

    if not rows:
        print("\nno date to append")
        connection.close()
        return

    stage(connection, "answer", {"qid": "VARCHAR", **{field: duck_type(D.Date) for field in COLUMNS}}, rows)

    for field in COLUMNS:
        connection.execute(
            f"""
            UPDATE individual SET "{field}" = list_concat(individual."{field}", [answer."{field}"])
            FROM answer WHERE individual.entity.qid = answer.qid AND answer."{field}" IS NOT NULL
            """
        )

    added = connection.execute(
        "SELECT count(*) FROM individual, unnest(birth_date) AS t(d) WHERE d.field_provenance['year'].ai_answer.prompt_id = 'wikipedia_dates'"
    ).fetchone()[0]
    print(f"\n{added:,} birth dates appended from the model's answers")
    connection.close()


if __name__ == "__main__":
    main()
