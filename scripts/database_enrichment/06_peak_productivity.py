import csv
from dataclasses import dataclass

from common import D, Enrichment, ROOT, as_json, open_database, provenance_column, stage

CURRENT_YEAR = 2026

PRODUCTIVE_AGE_DATASET = ROOT / "data" / "productive_age_window.csv"
PRODUCTIVE_AGE_CATEGORY = "global"

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

ENRICHMENT = Enrichment(
    reads=("Individual.birth_date", "Individual.death_date", "Individual.floruit_date", "Individual.works_period"),
    writes=("IndividualEnriched.peak_productivity",),
    rule="The years the individual is taken to have been at work, as a start year, an end year, the single year that stands for them where one exists, and the name of the rule that produced them. Every rule in RULES is tried in the order written, over dates stated to the year before dates stated no finer than a decade; the first rule that yields a window wins. Where a rule needs a date the individual has from several sources, the source earliest in SOURCE_PRIORITY is the one used. An individual no rule fits is left with no window at all.",
    answers=PRODUCTIVE_AGE_DATASET,
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


def productive_age(category=PRODUCTIVE_AGE_CATEGORY):
    with PRODUCTIVE_AGE_DATASET.open() as handle:
        for row in csv.DictReader(handle):
            if row["category"] == category:
                return int(row["low_age"]), int(row["high_age"]), int(row["individuals"])
    raise SystemExit(f"{category} is not a category of {PRODUCTIVE_AGE_DATASET}")


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


def peak_productivity(row, low, high):
    for _, precisions in PRECISION_PRIORITY:
        birth = preferred(row["birth_date"], precisions)
        death = preferred(row["death_date"], precisions)
        floruit = preferred(row["floruit_date"], precisions)
        for name in RULES:
            window = IMPLEMENTATIONS[name](birth, death, floruit, row["works_period"], low, high)
            if window is not None:
                return window
    return None


def main():
    ENRICHMENT.announce()
    low, high, measured_on = productive_age()
    print(f"productive age window: {low} to {high}, the quartiles of age at floruit over {measured_on:,} individuals")
    print(f"read from {PRODUCTIVE_AGE_DATASET.name}, category {PRODUCTIVE_AGE_CATEGORY}\n")
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

    connection = open_database()
    rows = connection.execute("""
        SELECT entity.qid AS qid, entity.label_en AS label, entity.description AS description,
               birth_date, death_date, floruit_date, works_period
        FROM individual
        """).arrow().read_all().to_pylist()

    assigned, counts = [], {}
    for row in rows:
        window = peak_productivity(row, low, high)
        method = window.method if window else NO_RULE_APPLIES
        counts[method] = counts.get(method, 0) + 1
        assigned.append(
            as_json(
                D.IndividualEnriched(
                    entity=D.WikidataEntity(qid=row["qid"], label_en=row["label"], description=row["description"]),
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
        )

    from write import columns_of

    stage(connection, "assigned", columns_of(D.IndividualEnriched), assigned)
    connection.execute("CREATE OR REPLACE TABLE individual_enriched AS SELECT * FROM assigned")

    print(f"{len(assigned):,} individuals, by the rule that decided each one:")
    for method, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"   {method:34} {count:>6,}")
    connection.close()


if __name__ == "__main__":
    main()
