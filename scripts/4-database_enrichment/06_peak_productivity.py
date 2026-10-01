"""Give each individual a peak activity window from their dates, by rule priority, and estimate a missing birth or death year from the cohort's life expectancy."""

import csv
from dataclasses import dataclass

from tqdm import tqdm

from common import D, Enrichment, ROOT, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of, duck_type

CURRENT_YEAR = 2026

PRODUCTIVE_AGE_DATASET = ROOT / "data" / "productive_age_window.csv"
CROSS_VERIFIED = ROOT / "data" / "similar_databases" / "cross_verified.duckdb"
MAIN_OCCUPATIONS = ("Culture", "Discovery/Science", "Leadership", "Sports/Games")
ALL = "All"
BIN_WIDTH = 50
YOUNG_DEATH_AGE = 18
OLDEST_AGE = 110
ESTIMATE = "life_expectancy_estimate"

RULES = (
    "died_young",
    "floruit",
    "birth_and_death",
    "birth_only",
    "death_only",
    "birth_and_death_century",
    "birth_only_century",
    "death_only_century",
    "works_span",
    "works_single",
)

SOURCE_PRIORITY = (
    "wikidata_property",
    "wikidata_entity_description",
    "cross_verified_database",
    "life_expectancy_estimate",
)

FINE_PRECISIONS = ("day", "month", "year", "decade")
COARSE_UNITS = {"century": 100, "millennium": 1000}

NO_RULE_APPLIES = "no_data"

BATCH = 200_000

ENRICHMENT = Enrichment(
    reads=("Individual.birth_date", "Individual.death_date", "Individual.floruit_date", "Individual.works_period", "CohortAgeStats.productivity_window_from_wikidata_floruit", "CohortAgeStats.life_expectancy_from_wikidata_birth_death", "CrossVerifiedPerson.level1_main_occ"),
    writes=("IndividualEnriched.peak_productivity",),
    rule="The years the individual is taken to have been at work, with how finely they are known and the name of the rule that produced them. Every rule in RULES is tried in the order written and the first that yields a window wins: first the rules on birth, death and floruit dates stated to the year or the decade, then the birth and death rules on dates stated only to the century or millennium, which give a window named in centuries ('late 4th century – early 5th century'), and only then the individual's dated works, the last resort. A floruit stated only to the century or millennium is never used. Someone who died aged 18 or younger is taken to have counted for their whole life. With a death and no birth, the birth is the death minus the median life expectancy of the cohort. Where a rule needs a date the individual has from several sources, the source earliest in SOURCE_PRIORITY is the one used. The productive-age window is the quartiles of age at floruit in cohort_age_stats, for the individual's cross-verified occupation and fifty-year birth cohort; an individual whose occupation is Other, Missing or absent from the cross-verified database takes the All row of the same cohort.",
    answers=ROOT / "scripts" / "4-database_enrichment" / "05b_cohort_age_stats.py",
)

COHORT = Enrichment(
    reads=("CohortAgeStats.cv_occupation", "CohortAgeStats.date_range", "CohortAgeStats.life_expectancy_from_wikidata_birth_death", "CohortAgeStats.productivity_window_from_wikidata_floruit", "CrossVerifiedPerson.level1_main_occ"),
    writes=("IndividualEnriched.cohort_age_stats",),
    rule="The row of cohort_age_stats the individual's peak_productivity was computed from — their cross-verified occupation, or All for anyone outside the four main categories, and their fifty-year birth cohort — copied with its life expectancy and productivity window. The cohort is that of the birth year; without one, of the birth estimated from the floruit, the death (by the median life expectancy) or the first work, in that order, each stated to the year or the decade. A date stated only to the century or millennium never chooses a cohort, so an individual dated by nothing finer has none.",
    inputs=("CohortAgeStats.productivity_window_from_wikidata_floruit",),
    answers=ROOT / "scripts" / "4-database_enrichment" / "05b_cohort_age_stats.py",
)

ESTIMATED_BIRTH = Enrichment(
    reads=("Individual.death_date", "CohortAgeStats.life_expectancy_from_wikidata_birth_death"),
    writes=("Individual.birth_date",),
    rule="The birth year of an individual with a death year and no birth year stated to the year or the decade: the death year minus the median life expectancy of their cross-verified occupation and fifty-year birth cohort in cohort_age_stats, recomputed once on the cohort that first estimate falls in. An estimate, appended after every stated date.",
    inputs=("Individual.death_date", "CohortAgeStats.life_expectancy_from_wikidata_birth_death"),
    answers=ROOT / "scripts" / "4-database_enrichment" / "05b_cohort_age_stats.py",
)

ESTIMATED_DEATH = Enrichment(
    reads=("Individual.birth_date", "CohortAgeStats.life_expectancy_from_wikidata_birth_death"),
    writes=("Individual.death_date",),
    rule=f"The death year of an individual with a birth year and no death year stated to the year or the decade: the birth year plus the median life expectancy of their cross-verified occupation and fifty-year birth cohort in cohort_age_stats, given only to someone born more than {OLDEST_AGE} years before {CURRENT_YEAR}, who cannot still be alive. An estimate, appended after every stated date.",
    inputs=("Individual.birth_date", "CohortAgeStats.life_expectancy_from_wikidata_birth_death"),
    answers=ROOT / "scripts" / "4-database_enrichment" / "05b_cohort_age_stats.py",
)

IMPLEMENTATIONS = {}


def rule(name):
    def keep(function):
        IMPLEMENTATIONS[name] = function
        return function

    return keep


@dataclass(frozen=True)
class Dated:
    year: int
    source: str
    precision: str


@dataclass(frozen=True)
class Period:
    number: int
    unit: int
    source: str


@dataclass(frozen=True)
class Window:
    start_year: int
    end_year: int
    method: str
    precision: str = "year"
    label: str | None = None


@dataclass
class Facts:
    birth: Dated | None
    death: Dated | None
    floruit: Dated | None
    birth_period: Period | None
    death_period: Period | None
    works: dict | None
    estimated_birth: int | None = None
    low: int = 0
    high: int = 0


def typical_age_at_floruit():
    with PRODUCTIVE_AGE_DATASET.open() as handle:
        for row in csv.DictReader(handle):
            if row["category"] == "global":
                return int(row["median_age"])
    raise SystemExit(f"global is not a category of {PRODUCTIVE_AGE_DATASET}")


def load_cohort_age_stats(connection):
    rows = connection.execute("""
        SELECT cv_occupation, date_range, life_expectancy_from_wikidata_birth_death, productivity_window_from_wikidata_floruit
        FROM cohort_age_stats
        WHERE list_contains($categories, cv_occupation)
    """, {"categories": list(MAIN_OCCUPATIONS + (ALL,))}).fetchall()
    cohorts = {
        (occupation, date_range["start_year"]): D.CohortAgeStatsMatch(
            cv_occupation=occupation,
            date_range=date_range,
            life_expectancy_from_wikidata_birth_death=life,
            productivity_window_from_wikidata_floruit=window,
        )
        for occupation, date_range, life, window in rows
    }
    starts = [start for _, start in cohorts]
    return cohorts, min(starts), max(starts)


def cohort_of(cohorts, occupation, year):
    table, first, last = cohorts
    category = occupation if occupation in MAIN_OCCUPATIONS else ALL
    return table[category, min(max(year // BIN_WIDTH * BIN_WIDTH, first), last)]


def mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {pair["key"]: pair["value"] for pair in value if isinstance(pair, dict) and "key" in pair}
    return {}


def source_of(entry):
    provenance = mapping(entry.get("field_provenance")).get("year") or {}
    rule_text = (provenance.get("rule") or "").lower()
    raw = " ".join(provenance.get("raw") or ())
    if "CrossVerified" in raw:
        return "cross_verified_database"
    if "life expectancy" in rule_text:
        return "life_expectancy_estimate"
    if "description" in rule_text:
        return "wikidata_entity_description"
    return "wikidata_property"


def by_source(entries, precisions):
    found = [entry for entry in entries or () if entry.get("year") is not None and entry.get("precision") in precisions]
    found.sort(key=lambda entry: SOURCE_PRIORITY.index(source_of(entry)) if source_of(entry) in SOURCE_PRIORITY else len(SOURCE_PRIORITY))
    return found[0] if found else None


def preferred(entries):
    entry = by_source(entries, FINE_PRECISIONS)
    return Dated(year=entry["year"], source=source_of(entry), precision=entry["precision"]) if entry else None


def period_number(year, unit):
    """The century or millennium a Wikidata year at that precision names, negative before the common era: 500 is the 5th century, 554 the 6th, -150 the 2nd century BC."""
    if year > 0:
        return (year - 1) // unit + 1
    return -((-year - 1) // unit + 1) if year < 0 else -1


def preferred_period(entries):
    entry = by_source(entries, tuple(COARSE_UNITS))
    if entry is None:
        return None
    unit = COARSE_UNITS[entry["precision"]]
    return Period(number=period_number(entry["year"], unit), unit=unit, source=source_of(entry))


def following(number):
    return 1 if number == -1 else number + 1


def preceding(number):
    return -1 if number == 1 else number - 1


def bounds(number, unit, part=None):
    start, end = ((number - 1) * unit + 1, number * unit) if number > 0 else (number * unit, (number + 1) * unit - 1)
    middle = start + (end - start) // 2
    return {"early": (start, middle), "late": (middle + 1, end)}.get(part, (start, end))


def ordinal(n):
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def period_label(number, unit, part=None):
    name = "century" if unit == 100 else "millennium"
    era = " BC" if number < 0 else ""
    return f"{part + ' ' if part else ''}{ordinal(abs(number))} {name}{era}"


def period_window(first, last, unit, method, first_part=None, last_part=None):
    label = period_label(first, unit, first_part)
    if (first, first_part) != (last, last_part):
        label = f"{label} – {period_label(last, unit, last_part)}"
    start, end = clamp(bounds(first, unit, first_part)[0], bounds(last, unit, last_part)[1])
    return Window(start, end, method, "century" if unit == 100 else "millennium", label)


def clamp(start, end):
    end = min(end, CURRENT_YEAR)
    return min(start, end), end


def born_too_recently(birth, low):
    return birth is not None and birth.year + low > CURRENT_YEAR


@rule("died_young")
def from_died_young(facts):
    """Someone who died aged 18 or younger and is still recorded is exceptional, and counts for their whole life, birth to death."""
    birth, death = facts.birth, facts.death
    if birth is None or death is None or not 0 <= death.year - birth.year <= YOUNG_DEATH_AGE:
        return None
    return Window(birth.year, death.year, f"died_young_{birth.source}")


@rule("floruit")
def from_floruit(facts):
    """The window a single stated floruit year implies: placed around that year within the productive-age window when a birth year says how old they were, and running forward from it for the length of a productive span when nothing does."""
    birth, death, floruit, low, high = facts.birth, facts.death, facts.floruit, facts.low, facts.high
    if floruit is None:
        return None
    span = high - low
    if birth is not None:
        age = floruit.year - birth.year
        if age <= low:
            start, end = floruit.year, birth.year + high
        elif age >= high:
            start, end = birth.year + low, floruit.year
        else:
            start, end = birth.year + low, birth.year + high
    else:
        start, end = floruit.year, floruit.year + span
    if death is not None and death.year < end:
        end = death.year
    start, end = clamp(start, end)
    shortest = max(10, span // 2)
    if end - start < shortest:
        start = end - shortest
    return Window(start, end, f"floruit_{floruit.source}")


@rule("birth_and_death")
def from_birth_and_death(facts):
    """The productive-age window counted from the birth year, cut short at the death year for anyone who died before the end of it."""
    birth, death = facts.birth, facts.death
    if birth is None or death is None or born_too_recently(birth, facts.low):
        return None
    start, end = clamp(birth.year + facts.low, min(birth.year + facts.high, death.year))
    return Window(start, end, f"birth_death_{birth.source}")


@rule("birth_only")
def from_birth_only(facts):
    """The productive-age window counted from the birth year, with no death year to cut it short."""
    birth = facts.birth
    if birth is None or born_too_recently(birth, facts.low):
        return None
    start, end = clamp(birth.year + facts.low, birth.year + facts.high)
    return Window(start, end, f"birth_only_{birth.source}")


@rule("death_only")
def from_death_only(facts):
    """The productive-age window counted from the birth the death implies — the death year minus the median life expectancy of the cohort — and cut short at the death."""
    death, birth = facts.death, facts.estimated_birth
    if death is None or birth is None:
        return None
    start, end = clamp(birth + facts.low, min(birth + facts.high, death.year))
    return Window(start, end, f"death_only_{death.source}")


@rule("birth_and_death_century")
def from_birth_and_death_century(facts):
    """Born and dead in the same century: that century. Born in one and dead in the next: the late part of the first and the early part of the second. Further apart: every century between."""
    birth, death = facts.birth_period, facts.death_period
    if birth is None or death is None or birth.unit != death.unit or bounds(death.number, death.unit)[0] < bounds(birth.number, birth.unit)[0]:
        return None
    method = f"birth_death_century_{birth.source}"
    if death.number == birth.number:
        return period_window(birth.number, birth.number, birth.unit, method)
    if death.number == following(birth.number):
        return period_window(birth.number, death.number, birth.unit, method, "late", "early")
    return period_window(birth.number, death.number, birth.unit, method)


@rule("birth_only_century")
def from_birth_only_century(facts):
    """Born in a century and nothing more: someone born late in it is active in the next, so the window is that century and the next."""
    birth = facts.birth_period
    if birth is None:
        return None
    return period_window(birth.number, following(birth.number), birth.unit, f"birth_only_century_{birth.source}")


@rule("death_only_century")
def from_death_only_century(facts):
    """Dead in a century and nothing more: someone who died early in it was active in the one before, so the window is the century before and that one."""
    death = facts.death_period
    if death is None:
        return None
    return period_window(preceding(death.number), death.number, death.unit, f"death_only_century_{death.source}")


@rule("works_span")
def from_works_span(facts):
    """The years the individual's dated works span, taken as they fall — the last resort, used only when no birth, death or floruit says anything."""
    works = facts.works
    if works is None or works.get("first_year") is None or works.get("last_year") is None:
        return None
    if works["first_year"] == works["last_year"]:
        return None
    start, end = clamp(works["first_year"], works["last_year"])
    return Window(start, end, "works_span")


@rule("works_single")
def from_works_single(facts):
    """A single dated work year, widened forward by the length of a productive span — the last resort, like works_span."""
    works = facts.works
    if works is None or works.get("first_year") is None:
        return None
    if works["first_year"] != works.get("last_year"):
        return None
    year = works["first_year"]
    start, end = clamp(year, year + (facts.high - facts.low))
    return Window(start, end, "works_single")


assert tuple(IMPLEMENTATIONS) == RULES, f"{tuple(IMPLEMENTATIONS)} is not {RULES}"


def life_expectancy(cohort, typical_age):
    life = cohort.life_expectancy_from_wikidata_birth_death
    return round(life.median) if life and life.median is not None else typical_age


def birth_from_death(cohorts, occupation, death_year, typical_age):
    """The death year minus the median life expectancy, recomputed once on the cohort the first estimate falls in."""
    year = death_year - typical_age
    for _ in range(2):
        year = death_year - life_expectancy(cohort_of(cohorts, occupation, year), typical_age)
    return year


def cohort_year(facts, cohorts, occupation, typical_age):
    if facts.birth is not None:
        return facts.birth.year
    if facts.floruit is not None:
        return facts.floruit.year - typical_age
    if facts.death is not None:
        facts.estimated_birth = birth_from_death(cohorts, occupation, facts.death.year, typical_age)
        return facts.estimated_birth
    if facts.works and facts.works.get("first_year") is not None:
        return facts.works["first_year"] - typical_age
    return None


def estimated_date(year, enrichment):
    provenance = enrichment.provenance()
    return D.Date(year=year, precision="year", field_provenance={"year": provenance, "precision": provenance})


def estimated_dates(facts, cohorts, occupation, typical_age):
    """The birth or death year life expectancy supplies to an individual who has the other one and not this one."""
    birth, death = None, None
    if facts.birth is None and facts.death is not None:
        birth = estimated_date(birth_from_death(cohorts, occupation, facts.death.year, typical_age), ESTIMATED_BIRTH)
    if facts.death is None and facts.birth is not None and facts.birth.year + OLDEST_AGE < CURRENT_YEAR:
        life = life_expectancy(cohort_of(cohorts, occupation, facts.birth.year), typical_age)
        death = estimated_date(facts.birth.year + life, ESTIMATED_DEATH)
    return birth, death


def peak_productivity(row, cohorts, typical_age):
    facts = Facts(
        birth=preferred(row["birth_date"]),
        death=preferred(row["death_date"]),
        floruit=preferred(row["floruit_date"]),
        birth_period=preferred_period(row["birth_date"]),
        death_period=preferred_period(row["death_date"]),
        works=row["works_period"],
    )
    estimates = estimated_dates(facts, cohorts, row["occupation"], typical_age)
    year = cohort_year(facts, cohorts, row["occupation"], typical_age)
    cohort = cohort_of(cohorts, row["occupation"], year) if year is not None else None
    if cohort is not None:
        facts.low = round(cohort.productivity_window_from_wikidata_floruit.low)
        facts.high = round(cohort.productivity_window_from_wikidata_floruit.high)
    for name in RULES:
        window = IMPLEMENTATIONS[name](facts)
        if window is not None:
            return window, cohort, estimates
    return None, cohort, estimates


def remove_estimates(connection):
    """Drops the estimates a previous run appended, so the window is built on stated dates only and a rerun does not stack them."""
    for column in ("birth_date", "death_date"):
        connection.execute(f"""
            UPDATE individual
            SET {column} = list_filter({column}, d -> coalesce(d.field_provenance['year'].rule, '') NOT ILIKE '%life expectancy%')
            WHERE list_bool_or(list_transform({column}, d -> coalesce(d.field_provenance['year'].rule, '') ILIKE '%life expectancy%'))
        """)


def append_estimates(connection, estimates):
    stage(connection, "estimated", {"qid": "VARCHAR", "birth": duck_type(D.Date), "death": duck_type(D.Date)}, estimates)
    for column, field in (("birth_date", "birth"), ("death_date", "death")):
        connection.execute(f"""
            UPDATE individual
            SET {column} = list_append(individual.{column}, estimated.{field})
            FROM estimated
            WHERE individual.entity.qid = estimated.qid AND estimated.{field} IS NOT NULL
        """)


def main():
    ENRICHMENT.announce()
    COHORT.announce()
    ESTIMATED_BIRTH.announce()
    ESTIMATED_DEATH.announce()
    connection = open_database()
    remove_estimates(connection)
    connection.execute(f"ATTACH '{CROSS_VERIFIED}' AS cv (READ_ONLY)")
    cohorts = load_cohort_age_stats(connection)
    typical_age = typical_age_at_floruit()
    print(f"productive age windows: {len(cohorts[0]):,} occupation x cohort rows from cohort_age_stats, cohorts {cohorts[1]} to {cohorts[2]}")
    print(f"occupations with their own window: {', '.join(MAIN_OCCUPATIONS)}; everyone else takes {ALL}")
    print(f"cohort without a birth year: anchor year minus {typical_age}, the median age at floruit in {PRODUCTIVE_AGE_DATASET.name}\n")
    print("rules, in the order they are tried:")
    for position, name in enumerate(RULES, start=1):
        print(f"   {position}. {name}")
    print(f"   {len(RULES) + 1}. {NO_RULE_APPLIES}")
    print(f"\nyear rules read dates stated to: {', '.join(FINE_PRECISIONS)}; century rules: {', '.join(COARSE_UNITS)}")
    print("\ndate sources, in the order they are preferred:")
    for position, name in enumerate(SOURCE_PRIORITY, start=1):
        print(f"   {position}. {name}")
    print()

    reader = connection.cursor().execute("""
        SELECT individual.entity,
               individual.birth_date, individual.death_date, individual.floruit_date, individual.works_period,
               cv.level1_main_occ AS occupation
        FROM individual
        LEFT JOIN cv.individuals AS cv ON cv.wikidata_code = individual.entity.qid
        """).fetch_record_batch(BATCH)
    counts = {}
    categories = {}
    estimates = []

    def assigned():
        for batch in tqdm(reader, desc="peak window", unit=" batches of 200k", mininterval=5):
            for row in batch.to_pylist():
                window, cohort, (birth, death) = peak_productivity(row, cohorts, typical_age)
                if birth or death:
                    estimates.append({"qid": row["entity"]["qid"], "birth": birth and as_json(birth), "death": death and as_json(death)})
                method = window.method if window else NO_RULE_APPLIES
                counts[method] = counts.get(method, 0) + 1
                category = cohort.cv_occupation if cohort else "no cohort"
                categories[category] = categories.get(category, 0) + 1
                yield as_json(
                    D.IndividualEnriched(
                        entity=D.WikidataEntity(**row["entity"]),
                        peak_productivity=(
                            D.PeakProductivity(
                                start_year=window.start_year,
                                end_year=window.end_year,
                                assignation_method=method,
                                precision=window.precision,
                                label=window.label or f"{window.start_year}–{window.end_year}",
                            )
                            if window
                            else None
                        ),
                        cohort_age_stats=cohort,
                        field_provenance={"peak_productivity": ENRICHMENT.provenance(), "cohort_age_stats": COHORT.provenance()},
                    )
                )

    total = stage(connection, "assigned", columns_of(D.IndividualEnriched), assigned())
    connection.execute("CREATE OR REPLACE TABLE individual_enriched AS SELECT * FROM assigned")
    append_estimates(connection, estimates)
    births = sum(1 for estimate in estimates if estimate["birth"])
    deaths = sum(1 for estimate in estimates if estimate["death"])

    print(f"{total:,} individuals, by the rule that decided each one:")
    for method, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"   {method:34} {count:>6,}")
    print(f"\nestimated from life expectancy: {births:,} birth years, {deaths:,} death years")
    print("\nproductive-age window used, by occupation:")
    for category, count in sorted(categories.items(), key=lambda pair: -pair[1]):
        print(f"   {category:34} {count:>6,}")
    connection.close()


if __name__ == "__main__":
    main()
