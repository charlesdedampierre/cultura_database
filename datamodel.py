"""Cultura data model — the single source of truth for the database schema.

One Pydantic model per table of `data/humans_clean.duckdb`. Every field of every
table is declared here; the DuckDB database is meant to be generated from this
file, not the other way round.

Verified against the live database on 2026-09-12 (DuckDB v1.5.2): all 18 tables
and 196 columns match — nothing missing, nothing invented. The closed
vocabularies (the `Literal` aliases below) were read from the data itself rather
than from `docs/DATABASE_SCHEMA.md`, which was out of date on two of them.

Usage:
    from datamodel import TABLES, Individual
    Individual.model_validate(row)        # validate one row
    TABLES["individuals"].model_fields    # introspect columns

Self-check: `python datamodel.py`
"""

from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

# --------------------------------------------------------------------------- #
# Shared types
# --------------------------------------------------------------------------- #

# Wikidata entity id, e.g. "Q937". Applied to identifier columns only — columns
# that denormalize a *matched* or *raw* value stay plain strings, because the
# live data contains non-QID junk there.
QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]

# Wikidata date precision codes, as stored in the `*_precision` columns:
# 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium.
# Kept as plain int: the full range present in the data has not been verified,
# and rejecting an unexpected code would block a load for no good reason.
Precision = int

# Year span as a string, e.g. "1892-1964", or a single year "1946".
# BCE keeps its leading minus, e.g. "-558" — which is why these are not ints.
YearSpan = str


class Table(BaseModel):
    """Base for every table model.

    `table_name` and `primary_key` carry the information a DDL generator needs,
    so the schema can be rebuilt from this file alone.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    table_name: ClassVar[str]
    primary_key: ClassVar[tuple[str, ...]] = ()


# --------------------------------------------------------------------------- #
# Closed vocabularies (read from the live data)
# --------------------------------------------------------------------------- #

# The canonical roles. The live `works.relationship` column also holds raw
# Wikidata property ids for the same nine roles; `Work` normalizes them.
Relationship = Literal[
    "author",
    "composer",
    "creator",
    "director",
    "editor",
    "illustrator",
    "performer",
    "producer",
    "screenwriter",
]

RELATIONSHIP_FROM_PROPERTY: dict[str, str] = {
    "P50": "author",
    "P57": "director",
    "P58": "screenwriter",
    "P86": "composer",
    "P98": "editor",
    "P110": "illustrator",
    "P162": "producer",
    "P170": "creator",
    "P175": "performer",
}

# How an individual was located inside a polity.
CliopatriaOrigin = Literal["birthplace", "deathplace", "country_of_citizenship"]
CliopatriaMethod = Literal["merge_with_polygon", "merge_with_url"]

# How the floruit window was derived. 22 values in the live data (the schema doc
# listed only 8). Read as <anchor>_<evidence>.
FloruitMethod = Literal[
    "birth_only_property",
    "birth_only_description",
    "birth_only_cv",
    "birth_only_wikipedia",
    "birth_death_property",
    "birth_death_description",
    "birth_death_cv",
    "birth_death_wikipedia",
    "birth_death_estimated_birth",
    "birth_century",
    "birth_death_century",
    "death_century",
    "floruit_property",
    "floruit_property_century",
    "floruit_property_decade",
    "floruit_description",
    "floruit_wikipedia",
    "floruit_wikipedia_span",
    "works_span",
    "works_single",
    "under_30",
    "no_data",
]

FloruitSource = Literal[
    "wikidata_property",
    "wikidata_description",
    "works",
    "life_expectancy",
    "cv_database",
    "wikipedia",
    "none",
]

PrecisionClass = Literal["year", "decade", "century"]

LifeExpectancyLookupSource = Literal[
    "birth_bin",
    "category+birth_bin:Leadership",
    "category+birth_bin:Culture",
    "category+birth_bin:Sports/Games",
    "category+birth_bin:Discovery/Science",
    "category+birth_bin:Other",
]

MetaOccupation = Literal["scientist", "artist"]

Level1Occupation = Literal[
    "Leadership",
    "Culture",
    "Discovery/Science",
    "Sports/Games",
    "Other",
    "Missing",
]

PolityType = Literal["POLITY", "RELATION"]


# --------------------------------------------------------------------------- #
# Core: individuals
# --------------------------------------------------------------------------- #


class Individual(Table):
    """One human (13,003,420 rows). The spine of the database."""

    table_name: ClassVar[str] = "individuals"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID
    name_en: str | None = None
    description_en: str | None = Field(None, description="Short Wikidata description")

    # --- dates as held by Wikidata properties ---
    birthdate: str | None = Field(None, description="ISO date, negative year for BCE")
    birthdate_precision: Precision | None = None
    deathdate: str | None = None
    deathdate_precision: Precision | None = None
    floruit_date: str | None = Field(None, description="Wikidata P1317, ISO date")
    floruit_precision: Precision | None = None
    floruit_year: int | None = Field(
        None, description="Resolved from individuals_floruit_period"
    )

    # --- denormalized labels, semicolon-separated when multi-valued ---
    country_of_citizenship_en: str | None = None
    birthcity_en: str | None = None
    deathcity_en: str | None = None
    occupations_en: str | None = None
    writing_language_name_en: str | None = None
    gender: str | None = Field(
        None, description="Free-text Wikidata gender label; not a closed vocabulary"
    )

    # --- rollup counts ---
    wikimedia_links_count: int | None = Field(
        None, description="Wikipedia pages across all languages"
    )
    identifiers_count: int | None = None
    number_of_works: int | None = Field(None, description="Rows in `works`")

    # --- dates recovered from the Wikidata description text ---
    dates_in_description: YearSpan | None = None
    birthdate_in_description: int | None = None
    deathdate_in_description: int | None = None
    floruit_year_in_description: int | None = None
    date_description: str | None = Field(None, description="Raw matched date string")

    # --- presence in reference datasets (0/1) ---
    pantheon_2_db: int | None = Field(None, ge=0, le=1)
    cross_verified_db: int | None = Field(None, ge=0, le=1)
    non_human: int | None = Field(None, ge=0, le=1, description="Misclassified entity")

    works_period: YearSpan | None = Field(
        None,
        description="Span of years the individual produced works. Per-work year is "
        "works.publication_date, else works.inception_date.",
    )

    # --- notability ---
    notability_western: int | None = Field(
        None, description="Count of Western-language Wikipedia editions (0-228)"
    )
    notability_non_western: int | None = None
    notability_general: float | None = Field(
        None, description="Geometric mean of the two — the canonical ranking metric"
    )

    # --- dates from secondary sources, used to fill the gaps ---
    birthdate_from_CV: str | None = None
    deathdate_from_CV: str | None = None
    birthdate_from_wikipedia: str | None = None
    deathdate_from_wikipedia: str | None = None
    floruit_from_wikipedia: str | None = None
    birthdate_from_life_expectancy: str | None = None
    deathdate_from_life_expectancy: str | None = None
    life_expectancy_lookup_source: LifeExpectancyLookupSource | None = None
    life_expectancy_median_used: float | None = None

    # --- unpopulated flags (all NULL in the live database) ---
    is_artist: bool | None = Field(None, description="Unpopulated; use occupations")
    is_scientist: bool | None = Field(None, description="Unpopulated; use occupations")


class IndividualKeys(Table):
    """Wikidata ids behind the denormalized labels on `individuals` (13,002,897 rows)."""

    table_name: ClassVar[str] = "individuals_keys"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID
    birthcity_id: str | None = None
    deathcity_id: str | None = None
    country_of_citizenship_ids: str | None = Field(None, description="Semicolon-separated")
    occupations_ids: str | None = Field(None, description="Semicolon-separated")
    gender_id: str | None = None
    writing_language_ids: str | None = Field(None, description="Semicolon-separated")


class IndividualFloruitPeriod(Table):
    """Resolved activity window per individual (13,003,420 rows).

    The window is what dating an individual actually relies on: birth/death are
    often missing, so it is derived from whatever evidence exists (`method`) and
    labelled with where that evidence came from (`source`).
    """

    table_name: ClassVar[str] = "individuals_floruit_period"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID
    name_en: str | None = None

    birthdate: str | None = None
    birthdate_precision: Precision | None = None
    birth_year: int | None = None
    deathdate: str | None = None
    deathdate_precision: Precision | None = None
    death_year: int | None = None
    floruit_date: str | None = None
    floruit_precision: Precision | None = None
    floruit_year: int | None = None

    floruit_period: YearSpan | None = Field(None, description='Label, e.g. "1962-1987"')
    floruit_period_start: int | None = None
    floruit_period_end: int | None = None

    method: FloruitMethod | None = None
    source: FloruitSource | None = None
    precision_class: PrecisionClass | None = None
    estimated: int | None = Field(
        None, ge=0, le=1, description="1 if the life-expectancy model was used"
    )
    works_period: YearSpan | None = Field(
        None, description="Mirrors individuals.works_period"
    )


class IndividualCliopatria(Table):
    """Individual x historical polity (7,830,341 rows, 5,161,090 individuals).

    Not unique on `wikidata_id`: one person can overlap several polities.
    """

    table_name: ClassVar[str] = "individuals_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID
    name_en: str | None = None
    polity_id: int
    polity_name: str | None = None

    origin: CliopatriaOrigin | None = None
    matched_name: str | None = Field(None, description="City or country that matched")
    matched_wikidata_id: str | None = None
    method: CliopatriaMethod | None = None

    floruit_year: int | None = None
    floruit_period_start: int | None = None
    floruit_period_end: int | None = None
    overlap_years: int | None = Field(
        None, description="Floruit years covered by this polity, summed over its periods"
    )


class IndividualCliopatriaPotential(Table):
    """Which match routes were available per individual (9,721,925 rows).

    Diagnostic table: it says how an individual *could* have been matched to a
    polity, which is what makes the coverage of `individuals_cliopatria` auditable.
    """

    table_name: ClassVar[str] = "individuals_cliopatria_potential"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID
    floruit_year: int | None = None
    polygon_birthplace: bool | None = None
    polygon_deathplace: bool | None = None
    polygon_country_of_citizenship: bool | None = None
    url_birthplace: bool | None = None
    url_deathplace: bool | None = None
    url_country_of_citizenship: bool | None = None


# --------------------------------------------------------------------------- #
# Works
# --------------------------------------------------------------------------- #


class Work(Table):
    """One (individual, work, role) triple (38,555,710 rows)."""

    table_name: ClassVar[str] = "works"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int
    individual_id: QID
    individual_name: str | None = None
    work_id: str | None = None
    work_name: str | None = None
    relationship: Relationship | None = None

    instance_of: str | None = Field(None, description="Pipe-joined P31 class ids")
    instance_of_en: str | None = Field(
        None, description="Pipe-joined labels, index-aligned with instance_of"
    )

    inception_date: str | None = Field(None, description="P571, ISO timestamp")
    inception_precision: Precision | None = None
    publication_date: str | None = Field(None, description="P577, ISO timestamp")
    publication_precision: Precision | None = None

    @field_validator("relationship", mode="before")
    @classmethod
    def normalize_relationship(cls, value: object) -> object:
        """Map a raw Wikidata property id onto its role label.

        The live column mixes the two spellings ("author" and "P50"); the model
        keeps only the label.
        """
        if isinstance(value, str):
            return RELATIONSHIP_FROM_PROPERTY.get(value, value)
        return value


# --------------------------------------------------------------------------- #
# Reference tables
# --------------------------------------------------------------------------- #


class Occupation(Table):
    """Occupation vocabulary with its three-tier ontology (18,230 rows)."""

    table_name: ClassVar[str] = "occupations"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID
    name_en: str | None = None
    description_en: str | None = None
    count: int | None = Field(None, description="Individuals holding this occupation")

    meta_occupation: MetaOccupation | None = Field(
        None, description="Coarse split; NULL for everything that is neither"
    )
    level1_main_occ: Level1Occupation | None = None
    level2_main_occ: str | None = Field(
        None, description='Mid tier, e.g. "Culture-core", "Academia", "Politics"'
    )
    level3_main_occ: str | None = Field(
        None, description='Fine tier, e.g. "politician", "writer", "painter"'
    )
    ontology_n_votes: int | None = Field(
        None, description="Observations backing the ontology assignment"
    )


class CountryOfCitizenship(Table):
    """Country vocabulary, historical entities included (4,572 rows)."""

    table_name: ClassVar[str] = "country_of_citizenship"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID
    name_en: str | None = None
    description_en: str | None = None
    count: int | None = None

    instance_of: str | None = None
    instance_qids: str | None = Field(None, description="Semicolon-separated P31 QIDs")
    instance_labels: str | None = Field(None, description="Labels for instance_qids")

    en_wikipedia_url: str | None = None
    lat: float | None = None
    lon: float | None = None

    iso_country_name: str | None = Field(None, description="Mapped modern country")
    iso_a3_code: str | None = Field(None, description="ISO 3166-1 alpha-3")
    iso_modern_country_origin: str | None = Field(None, description="Resolution method")

    inception: str | None = Field(None, description="P571")
    dissolved: str | None = Field(None, description="P576")


class Place(Table):
    """Place vocabulary — birth and death cities (314,724 rows)."""

    table_name: ClassVar[str] = "places"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID
    name_en: str | None = None
    lat: float | None = None
    lon: float | None = None

    original_country_name: str | None = Field(None, description="Country from Wikidata")
    original_country_name_id: str | None = None
    en_wikipedia_url_original_country_name: str | None = None

    iso_country_name: str | None = Field(None, description="Mapped modern country")
    iso_a3_code: str | None = None

    entity_type: str | None = Field(None, description='Class label, e.g. "village"')
    entity_type_ids: str | None = Field(None, description="Semicolon-separated P31 ids")
    is_urban_settlement: int | None = Field(None, ge=0, le=1)

    inception_date: str | None = None
    inception_precision: Precision | None = None
    dissolution_date: str | None = None
    dissolution_precision: Precision | None = None


class WritingLanguage(Table):
    """Writing-language vocabulary (524 rows)."""

    table_name: ClassVar[str] = "writing_languages"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID
    name: str | None = None
    count: int | None = None


class IndividualWritingLanguage(Table):
    """Individual x writing language (234,476 rows)."""

    table_name: ClassVar[str] = "individual_writing_languages"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID
    individual_name: str | None = None
    language_id: str | None = None
    language_name: str | None = None


# --------------------------------------------------------------------------- #
# External identifiers
# --------------------------------------------------------------------------- #


class Identifier(Table):
    """An individual's record in an external database (59,508,342 rows)."""

    table_name: ClassVar[str] = "identifiers"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID
    individual_name: str | None = None
    property_id: str | None = Field(None, description='Wikidata property, e.g. "P214"')
    identifier_name: str | None = Field(None, description="External system name")
    value: str | None = None
    url: str | None = Field(None, description="Direct link to the external record")


class IdentifierType(Table):
    """The external databases themselves (5,169 rows)."""

    table_name: ClassVar[str] = "identifier_types"
    primary_key: ClassVar[tuple[str, ...]] = ("property_id",)

    property_id: str
    name_en: str | None = None
    description: str | None = None
    count: int | None = Field(None, description="Individuals carrying this identifier")

    issuer_name: str | None = None
    issuer_id: str | None = None
    issuer_instance: str | None = Field(None, description="Type of the issuer")
    country_name: str | None = None
    country_id: str | None = None

    inception: str | None = Field(None, description="Year the database was created")
    database_records: str | None = Field(None, description="Record count, as text")
    website: str | None = None


# --------------------------------------------------------------------------- #
# Wikipedia coverage
# --------------------------------------------------------------------------- #


class WikimediaLink(Table):
    """One Wikipedia article about an individual, in one language (15,551,839 rows).

    The base of the notability scores on `individuals`.
    """

    table_name: ClassVar[str] = "wikimedia_links"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int
    wikidata_id: QID
    individual_name: str | None = None
    site: str | None = Field(None, description='Wikipedia language code, e.g. "frwiki"')
    title: str | None = None
    url: str | None = None


# --------------------------------------------------------------------------- #
# Cliopatria polities
# --------------------------------------------------------------------------- #


class PolityCliopatria(Table):
    """A historical polity (1,604 rows)."""

    table_name: ClassVar[str] = "polities_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int
    name: str | None = None
    type: PolityType | None = None
    wikipedia_url: str | None = None
    wikidata_id: str | None = None
    number_individuals: int | None = Field(None, description="Matched individuals")


class PolityPeriodCliopatria(Table):
    """One polity's territory during one time span (13,755 rows).

    A polity has many periods; the geometry is what places an individual inside it.
    """

    table_name: ClassVar[str] = "polities_periods_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int
    polity_id: int
    polity_name: str | None = None
    from_year: int | None = None
    to_year: int | None = None
    area: float | None = Field(None, description="Polygon area in km2")
    geometry: str | None = Field(None, description="GeoJSON polygon")


class PolityModernCountryCliopatria(Table):
    """Historical polity -> modern country, for mapping onto today's borders (1,531 rows)."""

    table_name: ClassVar[str] = "polities_modern_countries_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ()

    polity_id: int
    polity_name: str | None = None
    country_qid: str | None = None
    country_name: str | None = None
    iso_a3_code: str | None = None
    continent: str | None = Field(None, description="From Wikidata P30")
    sources: str | None = Field(
        None, description="Pipe-joined patterns: P17, P36/P17, P1366/P17, P131/P17"
    )


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #


class WikidataPropertyDefinition(Table):
    """Which Wikidata property produced which column (49 rows) — the provenance map."""

    table_name: ClassVar[str] = "wikidata_properties_definition"
    primary_key: ClassVar[tuple[str, ...]] = ()

    property_id: str
    property_name: str | None = None
    description: str | None = None
    table_name_: str | None = Field(
        None, alias="table_name", description="Target table in the database"
    )
    column_name: str | None = None


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

MODELS: tuple[type[Table], ...] = (
    Individual,
    IndividualKeys,
    IndividualFloruitPeriod,
    IndividualCliopatria,
    IndividualCliopatriaPotential,
    Work,
    Occupation,
    CountryOfCitizenship,
    Place,
    WritingLanguage,
    IndividualWritingLanguage,
    Identifier,
    IdentifierType,
    WikimediaLink,
    PolityCliopatria,
    PolityPeriodCliopatria,
    PolityModernCountryCliopatria,
    WikidataPropertyDefinition,
)

TABLES: dict[str, type[Table]] = {model.table_name: model for model in MODELS}


# --------------------------------------------------------------------------- #
# Self-check
# --------------------------------------------------------------------------- #


def demo() -> None:
    """Validate the model against rows taken from the live database."""
    assert len(TABLES) == len(MODELS) == 18, "table names must be unique"

    einstein = Individual(
        wikidata_id="Q937",
        name_en="Albert Einstein",
        birthdate="1879-03-14",
        birthdate_precision=11,
        notability_general=282.0,
        pantheon_2_db=1,
    )
    assert einstein.deathdate is None
    assert einstein.wikidata_id == "Q937"

    # A raw Wikidata property id is normalized onto its role label.
    assert Work(id=1, individual_id="Q937", relationship="P50").relationship == "author"
    assert Work(id=2, individual_id="Q937", relationship="author").relationship == "author"

    # A closed vocabulary rejects a value that is not in the data.
    for model, kwargs in [
        (Work, {"id": 3, "individual_id": "Q937", "relationship": "sculptor"}),
        (IndividualFloruitPeriod, {"wikidata_id": "Q937", "source": "guesswork"}),
        (Individual, {"wikidata_id": "not-a-qid"}),
        (Individual, {"wikidata_id": "Q937", "unknown_column": 1}),
    ]:
        try:
            model(**kwargs)
        except Exception:
            pass
        else:
            raise AssertionError(f"{model.__name__} accepted {kwargs}")

    # BCE years survive as strings, and 0/1 flags stay bounded.
    assert IndividualFloruitPeriod(wikidata_id="Q859", works_period="-558").works_period
    try:
        Individual(wikidata_id="Q937", non_human=2)
    except Exception:
        pass
    else:
        raise AssertionError("non_human accepted 2")

    print(f"OK — {len(TABLES)} tables, {sum(len(m.model_fields) for m in MODELS)} columns")


if __name__ == "__main__":
    demo()
