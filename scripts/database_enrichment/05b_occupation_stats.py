from pathlib import Path

import numpy as np
import polars as pl
from tqdm import tqdm

from common import D, Enrichment, ROOT, SCRATCH, open_database
from pydantic_to_duckdb_schema import write_table

CROSS_VERIFIED = ROOT / "data" / "similar_databases" / "cross_verified.duckdb"
OCCUPATIONS = ("Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other", "Missing")
ALL = "All"
YEAR_OR_FINER = ("day", "month", "year")
BIN_WIDTH = 50
FIRST_BIN, LAST_BIN = -3500, 1900
LIFESPAN_RANGE = (0, 110)
FLORUIT_AGE_RANGE = (10, 100)
MIN_LIVES = 10
MIN_FLORUITS = 5
NEIGHBOUR_BINS = (0, 1, 3)

LIFE_EXPECTANCY = Enrichment(
    reads=("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "CrossVerifiedPerson.level1_main_occ"),
    writes=("OccupationStats.life_expectancy_from_wikidata_birth_death",),
    rule=f"Age at death in fractional years, death minus birth, for the individuals whose Wikidata birth and death are both stated to the year or finer, kept between {LIFESPAN_RANGE[0]} and {LIFESPAN_RANGE[1]}, quartered.",
    answers=Path(__file__).resolve(),
)

PRODUCTIVITY_WINDOW = Enrichment(
    reads=("IndividualWikidata.date_of_birth", "IndividualWikidata.floruit", "CrossVerifiedPerson.level1_main_occ"),
    writes=("OccupationStats.productivity_window_from_wikidata_floruit",),
    rule=f"Age at floruit, floruit year minus birth year, for the individuals whose Wikidata birth and floruit are both stated to the year or finer, kept between {FLORUIT_AGE_RANGE[0]} and {FLORUIT_AGE_RANGE[1]}, quartered.",
    answers=Path(__file__).resolve(),
)

FRAC_YEAR = """
CREATE TEMP MACRO frac_year(d) AS d.year + (
    30 * (coalesce(CAST(regexp_extract(d.iso, '^-?\\d+-(\\d+)', 1) AS INT), 1) - 1)
       + coalesce(CAST(regexp_extract(d.iso, '^-?\\d+-\\d+-(\\d+)', 1) AS INT), 1) - 1
) / 365.0
"""

PEOPLE = """
CREATE TEMP TABLE people AS
WITH wikidata_dates AS (
    SELECT entity.qid AS qid,
           list_filter(birth_date, d -> d.field_provenance['year'].rule IS NULL)[1]   AS birth,
           list_filter(death_date, d -> d.field_provenance['year'].rule IS NULL)[1]   AS death,
           list_filter(floruit_date, d -> d.field_provenance['year'].rule IS NULL)[1] AS floruit
    FROM individual
)
SELECT cv.level1_main_occ AS occupation,
       w.birth.year // $bin_width * $bin_width AS birth_bin,
       CASE WHEN list_contains($year_or_finer, w.death.precision)
            THEN frac_year(w.death) - frac_year(w.birth) END AS lifespan,
       CASE WHEN list_contains($year_or_finer, w.floruit.precision)
            THEN w.floruit.year - w.birth.year END           AS age_at_floruit
FROM wikidata_dates AS w
LEFT JOIN cv.individuals AS cv ON cv.wikidata_code = w.qid
WHERE list_contains($year_or_finer, w.birth.precision)
  AND w.birth.year < $last_bin + $bin_width
"""


def arrays(frame, column=None):
    occupation = frame["occupation"].to_numpy().astype(object)
    birth_bin = frame["birth_bin"].to_numpy()
    return (occupation, birth_bin) if column is None else (occupation, birth_bin, frame[column].to_numpy())


def load_people(connection):
    connection.execute(f"ATTACH '{CROSS_VERIFIED}' AS cv (READ_ONLY)")
    connection.execute(FRAC_YEAR)
    connection.execute(PEOPLE, {"year_or_finer": list(YEAR_OR_FINER), "bin_width": BIN_WIDTH, "last_bin": LAST_BIN})
    people = connection.sql("SELECT * FROM people").pl()
    return {
        "everyone": arrays(people),
        "lifespan": arrays(people.filter(pl.col("lifespan").is_between(*LIFESPAN_RANGE)), "lifespan"),
        "age_at_floruit": arrays(people.filter(pl.col("age_at_floruit").is_between(*FLORUIT_AGE_RANGE)), "age_at_floruit"),
    }


def age_range(values):
    low, median, high = np.quantile(values, [0.25, 0.5, 0.75])
    return D.AgeRange(low=round(low, 1), median=round(median, 1), high=round(high, 1))


def in_occupation(occupations, occupation):
    return np.ones(len(occupations), dtype=bool) if occupation == ALL else occupations == occupation


def pools(occupation, start_year):
    for neighbours in NEIGHBOUR_BINS:
        described = "the cohort alone" if neighbours == 0 else f"the cohort and {neighbours} on each side"
        yield described, lambda occupations, bins, n=neighbours: in_occupation(occupations, occupation) & (np.abs(bins - start_year) <= n * BIN_WIDTH)
    if occupation != ALL:
        yield f"{occupation} over all cohorts", lambda occupations, bins: occupations == occupation
    yield "every individual over all cohorts", lambda occupations, bins: np.ones(len(occupations), dtype=bool)


def measure(sample, minimum, occupation, start_year):
    occupations, bins, values = sample
    for described, selects in pools(occupation, start_year):
        pooled = values[selects(occupations, bins)]
        if len(pooled) >= minimum:
            return age_range(pooled), len(pooled), described
    return None, 0, "no pool large enough"


def with_pool(enrichment, described):
    return enrichment.provenance().model_copy(update={"rule": f"{enrichment.rule} Measured on {described}."})


def compute(people):
    rows = []
    occupations, bins = people["everyone"]
    grid = [(o, b) for o in OCCUPATIONS + (ALL,) for b in range(FIRST_BIN, LAST_BIN + 1, BIN_WIDTH)]
    for occupation, start_year in tqdm(grid, desc="occupation x cohort", unit=" cell"):
        life, death_n, life_pool = measure(people["lifespan"], MIN_LIVES, occupation, start_year)
        window, floruit_n, window_pool = measure(people["age_at_floruit"], MIN_FLORUITS, occupation, start_year)
        rows.append(D.OccupationStats(
            cv_occupation=occupation,
            date_range=D.DateRange(start_year=start_year, end_year=start_year + BIN_WIDTH - 1),
            life_expectancy_from_wikidata_birth_death=life,
            productivity_window_from_wikidata_floruit=window,
            birth_n=int((in_occupation(occupations, occupation) & (bins == start_year)).sum()),
            death_n=death_n,
            floruit_n=floruit_n,
            field_provenance={
                "life_expectancy_from_wikidata_birth_death": with_pool(LIFE_EXPECTANCY, life_pool),
                "productivity_window_from_wikidata_floruit": with_pool(PRODUCTIVITY_WINDOW, window_pool),
            },
        ))
    return rows


def report(connection):
    for column in ("life_expectancy_from_wikidata_birth_death", "productivity_window_from_wikidata_floruit"):
        print(f"\n{column}, rows by pool:")
        for pool, n in connection.execute(f"""
            SELECT regexp_extract(field_provenance['{column}'].rule, 'Measured on (.*)\\.$', 1) AS pool, count(*)
            FROM occupation_stats GROUP BY pool ORDER BY count(*) DESC
        """).fetchall():
            print(f"   {n:>4}  {pool}")
    print("\nCulture, 1600 to 1950:")
    print(connection.sql("""
        SELECT date_range.start_year AS cohort, birth_n,
               life_expectancy_from_wikidata_birth_death.median AS life_median, death_n,
               productivity_window_from_wikidata_floruit AS window, floruit_n
        FROM occupation_stats
        WHERE cv_occupation = 'Culture' AND date_range.start_year BETWEEN 1600 AND 1950
        ORDER BY cohort
    """))


def main():
    LIFE_EXPECTANCY.announce()
    PRODUCTIVITY_WINDOW.announce()
    connection = open_database()
    people = load_people(connection)
    print(f"{len(people['everyone'][0]):,} individuals with a Wikidata birth year, {len(people['lifespan'][0]):,} with a lifespan, {len(people['age_at_floruit'][0]):,} with an age at floruit")
    written = write_table(connection, "occupation_stats", D.OccupationStats, compute(people), SCRATCH)
    print(f"occupation_stats: {written:,} rows")
    report(connection)
    connection.close()


if __name__ == "__main__":
    main()
