import csv
from dataclasses import dataclass

from tqdm import tqdm

from common import D, Enrichment, ROOT, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of

CURRENT_YEAR = 2026

PRODUCTIVE_AGE_DATASET = ROOT / "data" / "productive_age_window.csv"
CROSS_VERIFIED = ROOT / "data" / "similar_databases" / "cross_verified.duckdb"
MAIN_OCCUPATIONS = ("Culture", "Discovery/Science", "Leadership", "Sports/Games")
ALL = "All"
BIN_WIDTH = 50

RULES = (
    "floruit",
    "works_span",
    "works_single",
    "birth_and_death",
    "birth_only",
    "death_only",
)

SOURCE_PRIORITY = (
    "wikidata_property",
    "wikidata_entity_description",
    "cross_verified_database",
    "wikipedia_article",
    "life_expectancy_estimate",
)

PRECISION_PRIORITY = (
    ("stated to the year", ("day", "month", "year")),
    ("stated no finer than a decade", ("decade", "century", "millennium")),
)

NO_RULE_APPLIES = "no_data"

BATCH = 200_000

ENRICHMENT = Enrichment(
    reads=("Individual.birth_date", "Individual.death_date", "Individual.floruit_date", "Individual.works_period", "OccupationStats.productivity_window_from_wikidata_floruit", "CrossVerifiedPerson.level1_main_occ"),
    writes=("IndividualEnriched.peak_productivity",),
    rule="The years the individual is taken to have been at work, as a start year, an end year, the single year that stands for them where one exists, and the name of the rule that produced them. Every rule in RULES is tried in the order written, over dates stated to the year before dates stated no finer than a decade; the first rule that yields a window wins. Where a rule needs a date the individual has from several sources, the source earliest in SOURCE_PRIORITY is the one used. An individual no rule fits is left with no window at all. The productive-age window is the quartiles of age at floruit in occupation_stats, for the individual's cross-verified occupation and fifty-year birth cohort; an individual whose occupation is Other, Missing or absent from the cross-verified database takes the All row of the same cohort. Without a birth year the cohort is the one born the all-period median age at floruit before the floruit, the first work or the death.",
    answers=ROOT / "scripts" / "database_enrichment" / "05b_occupation_stats.py",
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
class Window:
    start_year: int
    end_year: int
    method: str


def typical_age_at_floruit():
    with PRODUCTIVE_AGE_DATASET.open() as handle:
        for row in csv.DictReader(handle):
            if row["category"] == "global":
                return int(row["median_age"])
    raise SystemExit(f"global is not a category of {PRODUCTIVE_AGE_DATASET}")


def productive_age_windows(connection):
    rows = connection.execute("""
        SELECT cv_occupation, date_range.start_year,
               productivity_window_from_wikidata_floruit.low, productivity_window_from_wikidata_floruit.high
        FROM occupation_stats
    """).fetchall()
    windows = {(occupation, start): (round(low), round(high)) for occupation, start, low, high in rows}
    starts = [start for _, start in windows]
    return windows, min(starts), max(starts)


def cohort_year(birth, death, floruit, works, typical_age):
    if birth is not None:
        return birth.year
    anchor = floruit.year if floruit else (works or {}).get("first_year") or (death.year if death else None)
    return None if anchor is None else anchor - typical_age


def productive_age(windows, occupation, year):
    table, first, last = windows
    category = occupation if occupation in MAIN_OCCUPATIONS else ALL
    start = last if year is None else min(max(year // BIN_WIDTH * BIN_WIDTH, first), last)
    return table[category, start]


def mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {pair["key"]: pair["value"] for pair in value if isinstance(pair, dict) and "key" in pair}
    return {}


def source_of(entry):
    provenance = mapping(entry.get("field_provenance")).get("year") or {}
    answer = provenance.get("ai_answer") or {}
    rule_text = (provenance.get("rule") or "").lower()
    raw = " ".join(provenance.get("raw") or ())
    if answer.get("prompt_id") == "wikipedia_dates":
        return "wikipedia_article"
    if "CrossVerified" in raw:
        return "cross_verified_database"
    if "life expectancy" in rule_text:
        return "life_expectancy_estimate"
    if "description" in rule_text:
        return "wikidata_entity_description"
    return "wikidata_property"


def preferred(entries, precisions):
    found = [Dated(year=entry["year"], source=source_of(entry), precision=entry["precision"]) for entry in entries or () if entry.get("year") is not None and entry.get("precision") in precisions]
    found.sort(key=lambda d: SOURCE_PRIORITY.index(d.source) if d.source in SOURCE_PRIORITY else len(SOURCE_PRIORITY))
    return found[0] if found else None


def clamp(start, end):
    end = min(end, CURRENT_YEAR)
    return min(start, end), end


def born_too_recently(birth, low):
    return birth is not None and birth.year + low > CURRENT_YEAR


@rule("floruit")
def from_floruit(birth, death, floruit, works, low, high):
    """The window a single stated floruit year implies: placed around that year within the productive-age window when a birth year says how old they were, and running forward from it for the length of a productive span when nothing does."""
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


@rule("works_span")
def from_works_span(birth, death, floruit, works, low, high):
    """The years the individual's dated works actually span, taken exactly as they fall, whenever the first and the last are not the same year."""
    if works is None or works.get("first_year") is None or works.get("last_year") is None:
        return None
    if works["first_year"] == works["last_year"]:
        return None
    start, end = clamp(works["first_year"], works["last_year"])
    return Window(start, end, "works_span")


@rule("works_single")
def from_works_single(birth, death, floruit, works, low, high):
    """A single dated work year, widened forward by the length of a productive span, one work dating a moment rather than a working life."""
    if works is None or works.get("first_year") is None:
        return None
    if works["first_year"] != works.get("last_year"):
        return None
    year = works["first_year"]
    start, end = clamp(year, year + (high - low))
    return Window(start, end, "works_single")


@rule("birth_and_death")
def from_birth_and_death(birth, death, floruit, works, low, high):
    """The productive-age window counted from the birth year, cut short at the death year for anyone who died before the end of it."""
    if birth is None or death is None or born_too_recently(birth, low):
        return None
    start, end = clamp(birth.year + low, min(birth.year + high, death.year))
    return Window(start, end, f"birth_death_{birth.source}")


@rule("birth_only")
def from_birth_only(birth, death, floruit, works, low, high):
    """The productive-age window counted from the birth year, with no death year to cut it short."""
    if birth is None or born_too_recently(birth, low):
        return None
    start, end = clamp(birth.year + low, birth.year + high)
    return Window(start, end, f"birth_only_{birth.source}")


@rule("death_only")
def from_death_only(birth, death, floruit, works, low, high):
    """The window ending at the death year and running back the length of a productive span, which is as much as a death year alone supports."""
    if death is None:
        return None
    start, end = clamp(death.year - (high - low), death.year)
    return Window(start, end, f"death_only_{death.source}")


assert tuple(IMPLEMENTATIONS) == RULES, f"{tuple(IMPLEMENTATIONS)} is not {RULES}"


def peak_productivity(row, windows, typical_age):
    for _, precisions in PRECISION_PRIORITY:
        birth = preferred(row["birth_date"], precisions)
        death = preferred(row["death_date"], precisions)
        floruit = preferred(row["floruit_date"], precisions)
        year = cohort_year(birth, death, floruit, row["works_period"], typical_age)
        low, high = productive_age(windows, row["occupation"], year)
        for name in RULES:
            window = IMPLEMENTATIONS[name](birth, death, floruit, row["works_period"], low, high)
            if window is not None:
                return window
    return None


def main():
    ENRICHMENT.announce()
    connection = open_database()
    connection.execute(f"ATTACH '{CROSS_VERIFIED}' AS cv (READ_ONLY)")
    windows = productive_age_windows(connection)
    typical_age = typical_age_at_floruit()
    print(f"productive age windows: {len(windows[0]):,} occupation x cohort rows from occupation_stats, cohorts {windows[1]} to {windows[2]}")
    print(f"occupations with their own window: {', '.join(MAIN_OCCUPATIONS)}; everyone else takes {ALL}")
    print(f"cohort without a birth year: anchor year minus {typical_age}, the median age at floruit in {PRODUCTIVE_AGE_DATASET.name}\n")
    print("rules, in the order they are tried:")
    for position, name in enumerate(RULES, start=1):
        print(f"   {position}. {name}")
    print(f"   {len(RULES) + 1}. {NO_RULE_APPLIES}")
    print("\ndate precision, in the order it is tried:")
    for description, _ in PRECISION_PRIORITY:
        print(f"   {description}")
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

    def assigned():
        for batch in tqdm(reader, desc="peak window", unit=" batches of 200k", mininterval=5):
            for row in batch.to_pylist():
                window = peak_productivity(row, windows, typical_age)
                method = window.method if window else NO_RULE_APPLIES
                counts[method] = counts.get(method, 0) + 1
                category = row["occupation"] if row["occupation"] in MAIN_OCCUPATIONS else ALL
                categories[category] = categories.get(category, 0) + 1
                yield as_json(
                    D.IndividualEnriched(
                        entity=D.WikidataEntity(**row["entity"]),
                        peak_productivity=(
                            D.PeakProductivity(
                                start_year=window.start_year,
                                end_year=window.end_year,
                                assignation_method=method,
                            )
                            if window
                            else None
                        ),
                        field_provenance={"peak_productivity": ENRICHMENT.provenance()},
                    )
                )

    total = stage(connection, "assigned", columns_of(D.IndividualEnriched), assigned())
    connection.execute("CREATE OR REPLACE TABLE individual_enriched AS SELECT * FROM assigned")

    print(f"{total:,} individuals, by the rule that decided each one:")
    for method, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"   {method:34} {count:>6,}")
    print("\nproductive-age window used, by occupation:")
    for category, count in sorted(categories.items(), key=lambda pair: -pair[1]):
        print(f"   {category:34} {count:>6,}")
    connection.close()


if __name__ == "__main__":
    main()
