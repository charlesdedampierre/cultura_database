"""Give each Cliopatria territory its Seshat id, and each individual's polity matches the Seshat ids of the territories their peak activity window overlaps."""

from tqdm import tqdm

from common import D, DATABASE, Enrichment, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of

import json_to_raw_models

TERRITORY = Enrichment(
    reads=("PolityCliopatria.seshat_id", "PolityCliopatria.name", "PolityCliopatria.wikidata", "PolityCliopatria.from_year", "PolityCliopatria.to_year", "PolityCliopatria.area"),
    writes=("Polity.territories.seshat_id",),
    rule="The SeshatID of the Cliopatria feature the territory was built from, matched on the polity's name without parentheses, whether it is a meta polity (parentheses in Cliopatria, child_polities here), its Wikidata item, the years and the area, which find exactly one feature for each of the 13 755 territories.",
    answers=DATABASE,
)

INDIVIDUAL = Enrichment(
    reads=("Polity.territories",),
    writes=("IndividualEnriched.polity.seshat_ids",),
    rule="For each polity the individual is matched to, the seshat_id of every territory of that polity whose years overlap the peak activity window, ordered by the territory's first year, each id once.",
    inputs=("IndividualEnriched.peak_productivity", "IndividualEnriched.polity"),
    answers=DATABASE,
)


def features():
    """One row per Cliopatria feature: the key a territory is found by — its polity's name without parentheses, whether it is a meta polity, its Wikidata item, years and area — and its SeshatID."""
    for span in tqdm(json_to_raw_models.polities(), desc="cliopatria features", unit=" features"):
        name = (span.name or "").strip()
        if not name:
            continue
        is_meta = name.startswith("(") and name.endswith(")")
        yield {
            "name": name[1:-1] if is_meta else name,
            "is_meta": is_meta,
            "wikidata": span.wikidata,
            "start_year": span.from_year,
            "end_year": span.to_year,
            "area": span.area,
            "seshat_id": span.seshat_id,
        }


def match_territories(connection):
    """Each territory's SeshatID, listed per polity in the order of its territories; stops unless every territory finds exactly one feature."""
    stage(connection, "feature", {
        "name": "VARCHAR", "is_meta": "BOOLEAN", "wikidata": "VARCHAR",
        "start_year": "BIGINT", "end_year": "BIGINT", "area": "DOUBLE", "seshat_id": "VARCHAR",
    }, features())
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE territory_feature AS
        WITH territory AS (
            SELECT polity.cliopatria_id, polity.name, len(polity.child_polities) > 0 AS is_meta, polity.entity.qid AS wikidata,
                   positions.position, polity.territories[positions.position] AS territory
            FROM polity, unnest(generate_series(1, len(polity.territories))) AS positions(position)
        )
        SELECT territory.cliopatria_id, territory.position, count(feature.name) AS found, any_value(feature.seshat_id) AS seshat_id
        FROM territory LEFT JOIN feature
          ON feature.name = territory.name
         AND feature.is_meta = territory.is_meta
         AND feature.wikidata IS NOT DISTINCT FROM territory.wikidata
         AND feature.start_year = territory.territory.start_year
         AND feature.end_year = territory.territory.end_year
         AND feature.area = territory.territory.area
        GROUP BY ALL
        """
    )
    territories, unmatched, ambiguous = connection.execute(
        "SELECT count(*), count(*) FILTER (WHERE found = 0), count(*) FILTER (WHERE found > 1) FROM territory_feature"
    ).fetchone()
    if unmatched or ambiguous:
        raise SystemExit(f"of {territories:,} territories, {unmatched:,} match no Cliopatria feature and {ambiguous:,} more than one")
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE seshat_by_polity AS
        SELECT cliopatria_id, list(seshat_id ORDER BY position) AS seshat_ids
        FROM territory_feature GROUP BY cliopatria_id
        """
    )


def write_territories(connection):
    provenance = as_json(TERRITORY.provenance())
    territories_type = columns_of(D.Polity)["territories"]
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE polity AS
        SELECT polity.* REPLACE (
            CAST(list_transform(polity.territories, (territory, position) -> struct_insert(
                struct_update(territory, field_provenance := CASE
                    WHEN seshat_by_polity.seshat_ids[position] IS NULL THEN territory.field_provenance
                    ELSE map_concat(territory.field_provenance, MAP {{'seshat_id': ?::{provenance_column()}}})
                END),
                seshat_id := seshat_by_polity.seshat_ids[position]
            )) AS {territories_type}) AS territories
        )
        FROM polity LEFT JOIN seshat_by_polity ON polity.cliopatria_id = seshat_by_polity.cliopatria_id
        ORDER BY polity.cliopatria_id
        """,
        [provenance],
    )


def write_individuals(connection):
    provenance = as_json(INDIVIDUAL.provenance())
    polity_type = columns_of(D.IndividualEnriched)["polity"]
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE seshat_territory AS
        SELECT polity.cliopatria_id, territory.start_year, territory.end_year, territory.seshat_id
        FROM polity, unnest(polity.territories) AS t(territory)
        WHERE territory.seshat_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE OR REPLACE TEMP TABLE match_seshat AS
        WITH matched AS (
            SELECT individual_enriched.entity.qid AS qid, matches.position,
                   individual_enriched.polity[matches.position].polity.cliopatria_id AS cliopatria_id,
                   individual_enriched.peak_productivity.start_year AS window_start,
                   individual_enriched.peak_productivity.end_year AS window_end
            FROM individual_enriched, unnest(generate_series(1, len(individual_enriched.polity))) AS matches(position)
            WHERE len(individual_enriched.polity) > 0
        ),
        overlapping AS (
            SELECT matched.qid, matched.position, seshat_territory.seshat_id, min(seshat_territory.start_year) AS first_year
            FROM matched JOIN seshat_territory
              ON seshat_territory.cliopatria_id = matched.cliopatria_id
             AND seshat_territory.start_year <= matched.window_end
             AND seshat_territory.end_year >= matched.window_start
            GROUP BY ALL
        ),
        by_match AS (
            SELECT qid, position, list(seshat_id ORDER BY first_year, seshat_id) AS seshat_ids
            FROM overlapping GROUP BY ALL
        )
        SELECT qid, map_from_entries(list((position, seshat_ids))) AS seshat_ids
        FROM by_match GROUP BY qid
        """
    )
    connection.execute(
        f"""
        CREATE OR REPLACE TABLE individual_enriched AS
        SELECT individual_enriched.* REPLACE (
            CAST(list_transform(individual_enriched.polity, (match, position) -> struct_insert(
                match, seshat_ids := coalesce(match_seshat.seshat_ids[position], []::VARCHAR[])
            )) AS {polity_type}) AS polity,
            CASE WHEN match_seshat.qid IS NULL THEN individual_enriched.field_provenance
                 ELSE map_concat(individual_enriched.field_provenance, MAP {{'polity.seshat_ids': ?::{provenance_column()}}})
            END AS field_provenance
        )
        FROM individual_enriched LEFT JOIN match_seshat ON individual_enriched.entity.qid = match_seshat.qid
        """,
        [provenance],
    )


def main():
    TERRITORY.announce()
    INDIVIDUAL.announce()
    connection = open_database()

    match_territories(connection)
    connection.begin()
    write_territories(connection)
    territories, with_id, distinct = connection.execute(
        "SELECT count(*), count(territory.seshat_id), count(DISTINCT territory.seshat_id) FROM polity, unnest(territories) AS t(territory)"
    ).fetchone()
    print(f"{with_id:,} of {territories:,} territories carry a Seshat id, {distinct:,} distinct")

    print("assigning Seshat ids to individuals (one SQL pass, a few minutes)")
    write_individuals(connection)
    connection.commit()
    matched, with_id, several = connection.execute(
        """
        SELECT count(*) FILTER (WHERE len(polity) > 0),
               count(*) FILTER (WHERE len(flatten(list_transform(polity, match -> match.seshat_ids))) > 0),
               count(*) FILTER (WHERE len(list_distinct(flatten(list_transform(polity, match -> match.seshat_ids)))) > 1)
        FROM individual_enriched
        """
    ).fetchone()
    print(f"{with_id:,} of {matched:,} individuals with a polity carry a Seshat id, {several:,} of them more than one")
    connection.close()


if __name__ == "__main__":
    main()
