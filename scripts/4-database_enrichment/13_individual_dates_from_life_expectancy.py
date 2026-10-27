"""Estimate a missing birth or death year from the mean life expectancy of the individual's meta occupation (one of four) and century, appended to individual.birth_date or individual.death_date."""

import polars as pl

from common import D, Enrichment, ROOT, as_json, open_database, stage
from pydantic_to_duckdb_schema import duck_type

CURRENT_YEAR = 2026
OLDEST_AGE = 110
LAST_BIRTH_YEAR = 1920
CENTURY = 100
MIN_LIVES = 10
LIFESPAN_RANGE = (0, 110)
KNOWN = ("day", "month", "year", "decade")
META_OCCUPATIONS = ("Culture", "Discovery/Science", "Leadership", "Sports/Games")
ALL = "All"
RULE_PREFIX = "Estimated from life expectancy:"

DEATH = Enrichment(
    reads=("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death"),
    writes=("Individual.death_date",),
    rule=f"{RULE_PREFIX} the birth year plus the mean life expectancy of the individuals of the same meta occupation born in the same century, among those of the four meta occupations Culture, Discovery/Science, Leadership and Sports/Games whose Wikidata birth and death are both stated to the year or the decade and {LIFESPAN_RANGE[0]} to {LIFESPAN_RANGE[1]} years apart, born in {LAST_BIRTH_YEAR} or earlier (some born later are still alive). Someone with none of the four meta occupations takes the mean of all four together. A century with fewer than {MIN_LIVES} of them takes the closest century that has {MIN_LIVES}, the later one on a tie. Only for someone born more than {OLDEST_AGE} years before {CURRENT_YEAR}, who cannot still be alive.",
    inputs=("Individual.birth_date", "Individual.death_date", "Occupation.meta_occupation"),
    answers=ROOT / "notebooks" / "01_life_expectancy.ipynb",
)

BIRTH = Enrichment(
    reads=("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death"),
    writes=("Individual.birth_date",),
    rule=f"{RULE_PREFIX} the death year minus the mean life expectancy of the individuals of the same meta occupation who died in the same century, among those of the four meta occupations Culture, Discovery/Science, Leadership and Sports/Games whose Wikidata birth and death are both stated to the year or the decade and {LIFESPAN_RANGE[0]} to {LIFESPAN_RANGE[1]} years apart, born in {LAST_BIRTH_YEAR} or earlier (some born later are still alive). Someone with none of the four meta occupations takes the mean of all four together. A century with fewer than {MIN_LIVES} of them takes the closest century that has {MIN_LIVES}, the later one on a tie.",
    inputs=("Individual.birth_date", "Individual.death_date", "Occupation.meta_occupation"),
    answers=ROOT / "notebooks" / "01_life_expectancy.ipynb",
)

PEOPLE = """
WITH held AS (
    SELECT entity.qid AS qid, unnest(occupation).entity.qid AS occupation_qid, generate_subscripts(occupation, 1) AS position
    FROM individual
),
counted AS (
    SELECT held.qid, occupation.meta_occupation, count(*) AS occupations, min(held.position) AS first_position
    FROM held
    JOIN occupation ON occupation.entity.qid = held.occupation_qid
    WHERE list_contains($meta_occupations, occupation.meta_occupation)
    GROUP BY ALL
),
main_meta_occupation AS (
    SELECT qid, meta_occupation
    FROM counted
    QUALIFY row_number() OVER (PARTITION BY qid ORDER BY occupations DESC, first_position) = 1
)
SELECT individual.entity.qid AS qid,
       coalesce(main_meta_occupation.meta_occupation, $all) AS meta_occupation,
       list_filter(individual.birth_date, d -> d.field_provenance['year'].rule IS NULL AND list_contains($known, d.precision))[1] AS birth,
       list_filter(individual.death_date, d -> d.field_provenance['year'].rule IS NULL AND list_contains($known, d.precision))[1] AS death,
       len(individual.birth_date) = 0 AS no_birth,
       len(individual.death_date) = 0 AS no_death
FROM individual
LEFT JOIN main_meta_occupation ON main_meta_occupation.qid = individual.entity.qid
WHERE len(individual.birth_date) > 0 OR len(individual.death_date) > 0
"""


def century_label(start):
    return f"{start}–{start + CENTURY - 1}" if start >= 0 else f"{-start}–{-(start + CENTURY - 1)} BC"


def load_people(connection):
    people = connection.execute(PEOPLE, {"known": list(KNOWN), "meta_occupations": list(META_OCCUPATIONS), "all": ALL}).pl()
    return people.select(
        "qid", "meta_occupation", "no_birth", "no_death",
        pl.col("birth").struct.field("year").alias("birth_year"),
        pl.col("death").struct.field("year").alias("death_year"),
    )


def lives_of(people):
    return (
        people.filter(pl.col("birth_year").is_not_null() & pl.col("death_year").is_not_null())
        .with_columns((pl.col("death_year") - pl.col("birth_year")).alias("life_expectancy"))
        .filter(pl.col("life_expectancy").is_between(*LIFESPAN_RANGE) & pl.col("meta_occupation").is_in(list(META_OCCUPATIONS)) & (pl.col("birth_year") <= LAST_BIRTH_YEAR))
    )


def cohorts(lives, anchor):
    """Mean life expectancy per meta occupation, and for the four together (ALL), per century of the anchor date."""
    lives = lives.with_columns((pl.col(anchor) // CENTURY * CENTURY).alias("century"))
    stats = (pl.len().alias("individuals"), pl.col("life_expectancy").mean().alias("mean"))
    cells = pl.concat([
        lives.group_by("meta_occupation", "century").agg(*stats),
        lives.group_by("century").agg(*stats).select(pl.lit(ALL).alias("meta_occupation"), "century", "individuals", "mean"),
    ])
    large = cells.filter(pl.col("individuals") >= MIN_LIVES).select(
        "meta_occupation", pl.col("century").alias("used_century"), pl.col("individuals").alias("used_individuals"), "mean"
    )
    return large, cells


def closest(large, wanted):
    """For each (meta occupation, century) wanted, the closest century of that meta occupation with MIN_LIVES lives, the later one on a tie."""
    return (
        wanted.join(large, on="meta_occupation")
        .with_columns((pl.col("used_century") - pl.col("century")).abs().alias("distance"))
        .sort("distance", "used_century", descending=[False, True])
        .group_by("meta_occupation", "century", maintain_order=True).first()
        .drop("distance")
    )


def estimate(people, lives, missing):
    anchor, enrichment, sign = ("birth_year", DEATH, 1) if missing == "death" else ("death_year", BIRTH, -1)
    targets = people.filter(pl.col(f"no_{missing}") & pl.col(anchor).is_not_null())
    if missing == "death":
        targets = targets.filter(pl.col(anchor) + OLDEST_AGE < CURRENT_YEAR)
    targets = targets.with_columns((pl.col(anchor) // CENTURY * CENTURY).alias("century"))
    large, cells = cohorts(lives, anchor)
    used = closest(large, targets.select("meta_occupation", "century").unique())
    used = used.join(cells.select("meta_occupation", "century", "individuals"), on=["meta_occupation", "century"], how="left")
    estimated = targets.join(used, on=["meta_occupation", "century"])
    assert estimated.height == targets.height, f"{targets.height - estimated.height} individuals missing a {missing} have no cohort"
    return estimated.with_columns((pl.col(anchor) + sign * pl.col("mean").round()).cast(pl.Int64).alias("year")), used, enrichment


def group_rule(enrichment, row, missing):
    dated = "born" if missing == "death" else "who died"
    group = "individuals of the four meta occupations" if row["meta_occupation"] == ALL else f"{row['meta_occupation']} individuals"
    rule = f"{enrichment.rule} Here {row['mean']:.1f} years, the mean of {row['used_individuals']:,} {group} {dated} in {century_label(row['used_century'])}"
    if row["used_century"] != row["century"]:
        rule += f", the closest century with {MIN_LIVES}; {century_label(row['century'])} has {row['individuals'] or 0}"
    return rule + "."


def provenance_rows(used, enrichment, missing):
    rows = []
    for row in used.iter_rows(named=True):
        provenance = as_json(enrichment.provenance().model_copy(update={"rule": group_rule(enrichment, row, missing)}))
        rows.append({"meta_occupation": row["meta_occupation"], "century": row["century"], "provenance": provenance})
    return rows


def write(connection, estimated, used, enrichment, missing):
    column = f"{missing}_date"
    stage(connection, "cohort_provenance", {"meta_occupation": "VARCHAR", "century": "BIGINT", "provenance": duck_type(D.Provenance)}, provenance_rows(used, enrichment, missing))
    connection.register("estimated", estimated.select("qid", "meta_occupation", "century", "year").to_arrow())
    connection.execute(f"""
        UPDATE individual SET {column} = list_append(individual.{column}, CAST({{
            'iso': NULL, 'year': estimate.year, 'precision': 'year',
            'field_provenance': MAP {{'year': estimate.provenance, 'precision': estimate.provenance}}
        }} AS {duck_type(D.Date)}))
        FROM (SELECT estimated.qid, estimated.year, cohort_provenance.provenance
              FROM estimated JOIN cohort_provenance USING (meta_occupation, century)) AS estimate
        WHERE individual.entity.qid = estimate.qid
    """)
    connection.unregister("estimated")


def report(estimated, used, missing):
    borrowed = used.filter(pl.col("used_century") != pl.col("century"))
    print(f"missing {missing}: {estimated.height:,} estimated from {used.height} cohorts, {borrowed.height} of which borrow the closest century "
          f"({estimated.join(borrowed.select('meta_occupation', 'century'), on=['meta_occupation', 'century']).height:,} individuals)")


def main():
    DEATH.announce()
    BIRTH.announce()
    connection = open_database()
    people = load_people(connection)
    lives = lives_of(people)
    print(f"{people.height:,} individuals with a birth or a death, {lives.height:,} with both stated to the year or the decade ({LIFESPAN_RANGE[0]}-{LIFESPAN_RANGE[1]} years)")
    for missing in ("death", "birth"):
        estimated, used, enrichment = estimate(people, lives, missing)
        report(estimated, used, missing)
        write(connection, estimated, used, enrichment, missing)
    connection.close()


if __name__ == "__main__":
    main()
