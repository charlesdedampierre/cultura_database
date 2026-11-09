"""Give each polity match of an individual's life stages (pre-active, active, post-active) the Seshat ids of the territories that stage overlaps.
Each territory already carries the SeshatID of its Cliopatria feature, read from the raw file when the polity table is built (raw_to_duckdb_models.territory)."""

from common import D, DATABASE, ROOT, SCRATCH, Enrichment, as_json, open_database, provenance_column, rewrite_individual_enriched
from pydantic_to_duckdb_schema import columns_of

PRESENT_YEAR = 2026  # end of an ongoing active life, as in 02_notebooks_polity/01_life_stage_polities_export.py
STAGES = ("pre_active_life_polity", "active_life_polity", "post_active_life_polity")
SESHAT_POLITIES = ROOT / "data" / "seshat" / "seshat_polities.json"
MATCH_FIELDS = [field for field in D.PolityMatch.model_fields if field != "seshat"]

INDIVIDUAL = Enrichment(
    reads=("Polity.territories", "Seshat API long_name"),
    writes=(*(f"IndividualEnriched.{column}.seshat" for column in STAGES), "IndividualEnriched.main_polity.seshat"),
    rule="For each polity matched to a life stage, the seshat_id of every territory of that polity whose years overlap the stage, ordered by the territory's first year, each id once, "
         "with its long name from the Seshat API (data/seshat/seshat_polities.json, scripts/2-wikidata_extraction_scripts/09_extract_seshat_polities.py). "
         "The stages are those of the polity export: pre-active from birth to start of active life, active from start to end of active life (to the present year when ongoing, cut at death), "
         "post-active from end of active life to death. main_polity takes the Seshat polities of the first active-life match.",
    inputs=("IndividualEnriched.birth_date", "IndividualEnriched.death_date", "IndividualEnriched.start_of_active_life", "IndividualEnriched.end_of_active_life",
            "IndividualEnriched.active_life_ongoing", *(f"IndividualEnriched.{column}" for column in STAGES)),
    answers=DATABASE,
)


def stage_windows(connection):
    """One row per polity match of a life stage, with the stage's years."""
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE life AS
        SELECT entity.qid AS qid, birth_date.year AS birth, death_date.year AS death,
               greatest(start_of_active_life.year, birth_date.year) AS active_start,
               CASE WHEN active_life_ongoing THEN {PRESENT_YEAR}
                    WHEN death_date.year IS NULL THEN end_of_active_life.year
                    ELSE least(end_of_active_life.year, death_date.year) END AS active_end,
               {", ".join(STAGES)}
        FROM individual_enriched
        WHERE {" OR ".join(f"len({column}) > 0" for column in STAGES)}
        """
    )
    windows = {
        "pre_active_life_polity": ("birth", "active_start"),
        "active_life_polity": ("active_start", "active_end"),
        "post_active_life_polity": ("active_end", "death"),
    }
    connection.execute(
        "CREATE OR REPLACE TEMP TABLE stage_match AS\n" + "\nUNION ALL\n".join(
            f"""
            SELECT qid, '{column}' AS stage, matches.position, {column}[matches.position].polity.cliopatria_id AS cliopatria_id,
                   {window_start} AS window_start, {window_end} AS window_end
            FROM life, unnest(generate_series(1, len({column}))) AS matches(position)
            WHERE len({column}) > 0
            """
            for column, (window_start, window_end) in windows.items()
        )
    )


def match_individuals(connection):
    """For each individual, a map from match position to Seshat ids, one map per stage; the long names are looked up when writing (seshat_polities)."""
    if not SESHAT_POLITIES.exists():
        raise SystemExit(f"{SESHAT_POLITIES} does not exist; run scripts/2-wikidata_extraction_scripts/09_extract_seshat_polities.py")
    connection.execute("CREATE OR REPLACE TEMP TABLE seshat_name AS SELECT map(list(name), list(long_name)) AS long_name FROM read_json(?)", [str(SESHAT_POLITIES)])
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE seshat_territory AS
        SELECT polity.cliopatria_id, territory.start_year, territory.end_year, territory.seshat_id
        FROM polity, unnest(polity.territories) AS t(territory)
        WHERE territory.seshat_id IS NOT NULL
        """
    )
    stage_windows(connection)
    connection.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE match_seshat AS
        WITH overlapping AS (
            SELECT stage_match.qid, stage_match.stage, stage_match.position, seshat_territory.seshat_id, min(seshat_territory.start_year) AS first_year
            FROM stage_match JOIN seshat_territory
              ON seshat_territory.cliopatria_id = stage_match.cliopatria_id
             AND seshat_territory.start_year <= stage_match.window_end
             AND seshat_territory.end_year >= stage_match.window_start
            GROUP BY ALL
        ),
        by_match AS (
            SELECT qid, stage, position, list(seshat_id ORDER BY first_year, seshat_id) AS seshat_ids
            FROM overlapping GROUP BY ALL
        )
        SELECT qid,
               {", ".join(f"map_from_entries(list((position, seshat_ids)) FILTER (WHERE stage = '{column}')) AS {column}" for column in STAGES)}
        FROM by_match GROUP BY qid
        """
    )


def seshat_polities(ids):
    """The Seshat structs (id, long name) of a list of Seshat ids."""
    return f"list_transform(coalesce({ids}, []), seshat_id -> {{'id': seshat_id, 'long_name': seshat_name.long_name[seshat_id]}})"


def with_seshat(match, seshat):
    """The polity match rebuilt with its seshat field (the stored struct may still carry the former seshat_ids)."""
    return "{" + ", ".join(f"'{field}': {match}.{field}" for field in MATCH_FIELDS) + f", 'seshat': {seshat}" + "}"


def write_individuals(connection):
    provenance = as_json(INDIVIDUAL.provenance())
    types = columns_of(D.IndividualEnriched)
    match_individuals(connection)
    stages = ",\n            ".join(
        f"CAST(list_transform(individual_enriched.{column}, (match, position) -> "
        + with_seshat("match", seshat_polities(f"match_seshat.{column}[position]"))
        + f") AS {types[column]}) AS {column}"
        for column in STAGES
    )
    main_polity = with_seshat("individual_enriched.main_polity", seshat_polities("match_seshat.active_life_polity[1]"))
    keys = ", ".join(f"'{column}.seshat': ?::{provenance_column()}" for column in (*STAGES, "main_polity"))
    rewrite_individual_enriched(
        connection,
        f"""
        SELECT individual_enriched.* REPLACE (
            {stages},
            CAST(CASE WHEN individual_enriched.main_polity IS NULL THEN NULL ELSE
                {main_polity}
            END AS {types["main_polity"]}) AS main_polity,
            CASE WHEN match_seshat.qid IS NULL THEN individual_enriched.field_provenance
                 ELSE map_concat(coalesce(individual_enriched.field_provenance, MAP {{}}), MAP {{{keys}}})
            END AS field_provenance
        )
        FROM individual_enriched LEFT JOIN match_seshat ON individual_enriched.entity.qid = match_seshat.qid
        CROSS JOIN seshat_name
        WHERE {{inside}}
        """,
        [provenance] * (len(STAGES) + 1),
    )


def main():
    INDIVIDUAL.announce()
    connection = open_database()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit='8GB'; SET threads=2; SET preserve_insertion_order=false; SET temp_directory='{SCRATCH}'")

    connection.begin()
    territories, with_id, distinct = connection.execute(
        "SELECT count(*), count(territory.seshat_id), count(DISTINCT territory.seshat_id) FROM polity, unnest(territories) AS t(territory)"
    ).fetchone()
    print(f"{with_id:,} of {territories:,} territories carry a Seshat id, {distinct:,} distinct")

    print("assigning Seshat ids to the life-stage polities of individuals, in qid ranges")
    write_individuals(connection)
    connection.commit()
    connection.execute("CHECKPOINT")
    for column in STAGES:
        matched, with_id = connection.execute(
            f"""
            SELECT count(*) FILTER (WHERE len({column}) > 0),
                   count(*) FILTER (WHERE len(flatten(list_transform({column}, match -> match.seshat))) > 0)
            FROM individual_enriched
            """
        ).fetchone()
        print(f"{column}: {with_id:,} of {matched:,} individuals with a polity carry a Seshat polity")
    named, ids = connection.execute(
        "SELECT count(seshat.long_name), count(*) FROM individual_enriched, unnest(active_life_polity) AS m(match), unnest(match.seshat) AS s(seshat)"
    ).fetchone()
    print(f"active_life_polity: {named:,} of {ids:,} Seshat polities carry a long name")
    connection.close()


if __name__ == "__main__":
    main()
