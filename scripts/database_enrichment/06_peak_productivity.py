from dataclasses import dataclass

from common import D, Enrichment, ROOT, as_json, open_database, provenance_column, stage

CURRENT_YEAR = 2026

PRODUCTIVE_AGE = {
    "global": (29, 55),
    "Culture": (30, 62),
    "Discovery/Science": (33, 62),
    "Leadership": (34, 67),
    "Sports/Games": (21, 35),
}

SOURCE_PRIORITY = ("property", "description", "cross_verified", "wikipedia", "life_expectancy")

PRECISION_PRIORITY = (
    ("year", ("day", "month", "year")),
    ("coarse", ("decade", "century", "millennium")),
)

ENRICHMENT = Enrichment(
    reads=("Individual.birth_date", "Individual.death_date", "Individual.floruit_date", "Individual.works_period"),
    writes=("IndividualEnriched.peak_productivity",),
    rule="The years the individual is taken to have been at work, from the first date rule that applies. Rules are tried in the order written in RULES, year-precise dates before coarse ones, and within a rule the date sources in the order written in SOURCE_PRIORITY. assignation_method names the rule and the source that won, so the row says which of them produced it.",
    answers=ROOT / "data" / "cultura_v2.duckdb",
)


@dataclass(frozen=True)
class Dated:
    year: int
    source: str
    precision: str


@dataclass(frozen=True)
class Window:
    start_year: int
    end_year: int
    midpoint_year: int | None
    method: str


def mapping(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {pair["key"]: pair["value"] for pair in value if isinstance(pair, dict) and "key" in pair}
    return {}


def source_of(entry):
    provenance = mapping(entry.get("field_provenance")).get("year") or {}
    answer = provenance.get("ai_answer") or {}
    rule = provenance.get("rule") or ""
    raw = " ".join(provenance.get("raw") or ())
    if answer.get("prompt_id") == "wikipedia_dates":
        return "wikipedia"
    if "CrossVerified" in raw:
        return "cross_verified"
    if "description" in rule.lower():
        return "description"
    if "life expectancy" in rule.lower() or "life_expectancy" in raw:
        return "life_expectancy"
    return "property"


def dated(entries, precisions):
    found = [
        Dated(year=e["year"], source=source_of(e), precision=e["precision"])
        for e in entries or ()
        if e.get("year") is not None and e.get("precision") in precisions
    ]
    found.sort(key=lambda d: SOURCE_PRIORITY.index(d.source) if d.source in SOURCE_PRIORITY else len(SOURCE_PRIORITY))
    return found[0] if found else None


def clamp(start, end):
    end = min(end, CURRENT_YEAR)
    start = min(start, end)
    return start, end


def from_floruit(birth, death, floruit, works, low, high):
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
    if end - start < max(10, span // 2):
        start = end - max(10, span // 2)
    return Window(start, end, floruit.year, f"floruit_{floruit.source}")


def from_works(birth, death, floruit, works, low, high):
    if works is None or works.get("first_year") is None or works.get("last_year") is None:
        return None
    first, last = works["first_year"], works["last_year"]
    if first == last:
        start, end = clamp(first, first + (high - low))
        return Window(start, end, first, "works_single")
    start, end = clamp(first, last)
    return Window(start, end, None, "works_span")


def from_birth_and_death(birth, death, floruit, works, low, high):
    if birth is None or death is None:
        return None
    if birth.year + low > CURRENT_YEAR:
        return None
    start, end = clamp(birth.year + low, min(birth.year + high, death.year))
    return Window(start, end, None, f"birth_death_{birth.source}")


def from_birth(birth, death, floruit, works, low, high):
    if birth is None or birth.year + low > CURRENT_YEAR:
        return None
    start, end = clamp(birth.year + low, birth.year + high)
    return Window(start, end, None, f"birth_only_{birth.source}")


def from_death(birth, death, floruit, works, low, high):
    if death is None:
        return None
    start, end = clamp(death.year - (high - low), death.year)
    return Window(start, end, None, f"death_only_{death.source}")


RULES = (
    from_floruit,
    from_works,
    from_birth_and_death,
    from_birth,
    from_death,
)


def peak_productivity(row, low, high):
    for _, precisions in PRECISION_PRIORITY:
        birth = dated(row["birth_date"], precisions)
        death = dated(row["death_date"], precisions)
        floruit = dated(row["floruit_date"], precisions)
        for rule in RULES:
            window = rule(birth, death, floruit, row["works_period"], low, high)
            if window is not None:
                return window
    return None


def main():
    ENRICHMENT.announce()
    print("rules, in the order they are tried:")
    for rule in RULES:
        print(f"   {rule.__name__}")
    print(f"sources, in the order they are preferred: {', '.join(SOURCE_PRIORITY)}")
    low, high = PRODUCTIVE_AGE["global"]
    print(f"productive age window: {low} to {high}")
    print("per-occupation windows are not applied: they need the cross-verified occupation category, which this database does not carry\n")

    connection = open_database()
    rows = connection.execute(
        """
        SELECT entity.qid AS qid, entity.label_en AS label, entity.description AS description,
               birth_date, death_date, floruit_date, works_period
        FROM individual
        """
    ).arrow().read_all().to_pylist()

    assigned, counts = [], {}
    for row in rows:
        window = peak_productivity(row, low, high)
        method = window.method if window else "no_data"
        counts[method] = counts.get(method, 0) + 1
        enriched = D.IndividualEnriched(
            entity=D.WikidataEntity(qid=row["qid"], label_en=row["label"], description=row["description"]),
            peak_productivity=D.PeakProductivity(
                start_year=window.start_year,
                midpoint_year=window.midpoint_year,
                end_year=window.end_year,
                assignation_method=method,
            ) if window else None,
            field_provenance={"peak_productivity": ENRICHMENT.provenance()},
        )
        assigned.append(as_json(enriched))

    from write import columns_of
    stage(connection, "assigned", columns_of(D.IndividualEnriched), assigned)
    connection.execute("CREATE OR REPLACE TABLE individual_enriched AS SELECT * FROM assigned")

    print(f"{len(assigned):,} individuals, by the rule that decided each one:")
    for method, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"   {method:34} {count:>6,}")
    connection.close()


if __name__ == "__main__":
    main()
