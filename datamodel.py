"""Cultura data model — the single source of truth for the database schema.

One Pydantic model per table of `data/humans_clean.duckdb`. Every field of every
table is declared here, in the same order as the database, and every field
carries a description. The DuckDB database is meant to be generated from this
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

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]

PRECISION = "Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium."

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

CliopatriaOrigin = Literal["birthplace", "deathplace", "country_of_citizenship"]

CliopatriaMethod = Literal["merge_with_polygon", "merge_with_url"]

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


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    table_name: ClassVar[str]
    primary_key: ClassVar[tuple[str, ...]] = ()


class Individual(Table):
    table_name: ClassVar[str] = "individuals"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID = Field(
        ..., description="Wikidata identifier of the individual, e.g. Q937 for Albert Einstein."
    )
    name_en: str | None = Field(None, description="Full name of the individual in English.")
    description_en: str | None = Field(
        None,
        description="Short Wikidata description, e.g. 'German-born theoretical physicist'.",
    )
    birthdate: str | None = Field(
        None,
        description="Date of birth as an ISO string. A negative year means BCE, e.g. '-0558-01-01'.",
    )
    birthdate_precision: int | None = Field(
        None, description=f"Precision of `birthdate`. {PRECISION}"
    )
    deathdate: str | None = Field(
        None, description="Date of death as an ISO string. A negative year means BCE."
    )
    deathdate_precision: int | None = Field(
        None, description=f"Precision of `deathdate`. {PRECISION}"
    )
    country_of_citizenship_en: str | None = Field(
        None,
        description="English labels of the countries of citizenship, semicolon-separated "
        "when the individual holds several. Ids are in `individuals_keys`.",
    )
    birthcity_en: str | None = Field(
        None, description="English name of the city of birth. Id is in `individuals_keys`."
    )
    deathcity_en: str | None = Field(
        None, description="English name of the city of death. Id is in `individuals_keys`."
    )
    occupations_en: str | None = Field(
        None,
        description="English occupation labels, semicolon-separated when there are several. "
        "Ids are in `individuals_keys`, the vocabulary in `occupations`.",
    )
    wikimedia_links_count: int | None = Field(
        None,
        description="Number of Wikipedia articles about the individual across all languages. "
        "Rows are in `wikimedia_links`.",
    )
    gender: str | None = Field(
        None,
        description="Wikidata gender label. Free text, not a closed vocabulary: the live "
        "column holds 48 distinct values, a few of them unresolved ids.",
    )
    identifiers_count: int | None = Field(
        None,
        description="Number of external-database identifiers held by the individual. "
        "Rows are in `identifiers`.",
    )
    writing_language_name_en: str | None = Field(
        None,
        description="English names of the languages the individual wrote in, "
        "semicolon-separated. Rows are in `individual_writing_languages`.",
    )
    number_of_works: int | None = Field(
        None, description="Number of rows for this individual in the `works` table."
    )
    floruit_date: str | None = Field(
        None,
        description="Floruit as declared by Wikidata property P1317, ISO string. Set only "
        "for the individuals where Wikidata carries the property.",
    )
    floruit_precision: int | None = Field(
        None, description=f"Precision of `floruit_date`. {PRECISION}"
    )
    floruit_year: int | None = Field(
        None,
        description="Single floruit year, resolved in `individuals_floruit_period` from "
        "whatever evidence exists. Populated for every individual that can be dated.",
    )
    dates_in_description: str | None = Field(
        None,
        description="Year span parsed out of `description_en`, e.g. '1937-2016'. A single "
        "year when only one was found.",
    )
    birthdate_in_description: int | None = Field(
        None, description="Birth year extracted from `description_en`. NULL when none was found."
    )
    deathdate_in_description: int | None = Field(
        None, description="Death year extracted from `description_en`."
    )
    floruit_year_in_description: int | None = Field(
        None, description="Floruit year extracted from `description_en`."
    )
    date_description: str | None = Field(
        None,
        description="Raw date substring matched in `description_en` before parsing, "
        "e.g. '1937-2016'. Kept so the extraction can be audited.",
    )
    pantheon_2_db: int | None = Field(
        None, ge=0, le=1, description="1 if the individual is in the Pantheon 2.0 dataset, else 0."
    )
    cross_verified_db: int | None = Field(
        None,
        ge=0,
        le=1,
        description="1 if the individual is in the cross-verified database (CVDB), else 0.",
    )
    non_human: int | None = Field(
        None,
        ge=0,
        le=1,
        description="1 if the row is not actually a human (872 rows), else 0. Filter these out.",
    )
    works_period: str | None = Field(
        None,
        description="Span of years over which the individual produced works, e.g. '1892-1964', "
        "or a single year when first equals last. The year of a work is its "
        "`works.publication_date`, else its `works.inception_date`. NULL when no work is dated.",
    )
    notability_western: int | None = Field(
        None,
        description="Number of Western-language Wikipedia editions covering the individual "
        "(0-228).",
    )
    notability_non_western: int | None = Field(
        None, description="Number of non-Western-language Wikipedia editions covering them."
    )
    notability_general: float | None = Field(
        None,
        description="Geometric mean of `notability_western` and `notability_non_western` "
        "(0 to ~282). The project's canonical ranking metric: it rewards fame that "
        "crosses the Western / non-Western divide.",
    )
    birthdate_from_CV: str | None = Field(
        None, description="Birth date taken from the cross-verified database (CVDB)."
    )
    deathdate_from_CV: str | None = Field(
        None, description="Death date taken from the cross-verified database (CVDB)."
    )
    birthdate_from_life_expectancy: str | None = Field(
        None,
        description="Birth date estimated by the life-expectancy model, when the death date "
        "is known but the birth date is not.",
    )
    deathdate_from_life_expectancy: str | None = Field(
        None,
        description="Death date estimated by the life-expectancy model, when the birth date "
        "is known but the death date is not.",
    )
    life_expectancy_lookup_source: LifeExpectancyLookupSource | None = Field(
        None,
        description="Which life-expectancy table produced the estimate: the overall birth "
        "bin, or the birth bin within an occupation category.",
    )
    life_expectancy_median_used: float | None = Field(
        None, description="Median life expectancy in years applied to build the estimate."
    )
    birthdate_from_wikipedia: str | None = Field(
        None, description="Birth date scraped from the individual's Wikipedia article."
    )
    deathdate_from_wikipedia: str | None = Field(
        None, description="Death date scraped from the individual's Wikipedia article."
    )
    floruit_from_wikipedia: str | None = Field(
        None, description="Floruit scraped from the individual's Wikipedia article."
    )
    is_artist: bool | None = Field(
        None,
        description="Artist flag. Unpopulated in the live database (all NULL) — derive it "
        "from `occupations.level1_main_occ` instead.",
    )
    is_scientist: bool | None = Field(
        None,
        description="Scientist flag. Unpopulated in the live database (all NULL) — derive it "
        "from `occupations.level1_main_occ` instead.",
    )


class IndividualKeys(Table):
    table_name: ClassVar[str] = "individuals_keys"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual.")
    birthcity_id: str | None = Field(
        None, description="Wikidata id of the city of birth. Joins `places.id`."
    )
    deathcity_id: str | None = Field(
        None, description="Wikidata id of the city of death. Joins `places.id`."
    )
    country_of_citizenship_ids: str | None = Field(
        None,
        description="Wikidata ids of the countries of citizenship, semicolon-separated, "
        "index-aligned with `individuals.country_of_citizenship_en`. "
        "Join `country_of_citizenship.wikidata_id`.",
    )
    occupations_ids: str | None = Field(
        None,
        description="Wikidata ids of the occupations, semicolon-separated, index-aligned "
        "with `individuals.occupations_en`. Join `occupations.id`.",
    )
    gender_id: str | None = Field(
        None, description="Wikidata id behind `individuals.gender`, e.g. Q6581097 for male."
    )
    writing_language_ids: str | None = Field(
        None,
        description="Wikidata ids of the writing languages, semicolon-separated. "
        "Join `writing_languages.id`.",
    )


class IndividualFloruitPeriod(Table):
    table_name: ClassVar[str] = "individuals_floruit_period"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual.")
    name_en: str | None = Field(None, description="Full name in English, copied from `individuals`.")
    birthdate: str | None = Field(
        None, description="Birth date used as input, ISO string, from any of the sources."
    )
    birthdate_precision: int | None = Field(
        None, description=f"Precision of `birthdate`. {PRECISION}"
    )
    birth_year: int | None = Field(
        None, description="Birth year parsed from `birthdate`. Negative for BCE."
    )
    deathdate: str | None = Field(
        None, description="Death date used as input, ISO string, from any of the sources."
    )
    deathdate_precision: int | None = Field(
        None, description=f"Precision of `deathdate`. {PRECISION}"
    )
    death_year: int | None = Field(
        None, description="Death year parsed from `deathdate`. Negative for BCE."
    )
    floruit_date: str | None = Field(
        None, description="Floruit date used as input, ISO string."
    )
    floruit_precision: int | None = Field(
        None, description=f"Precision of `floruit_date`. {PRECISION}"
    )
    floruit_year: int | None = Field(
        None,
        description="The single year that represents the individual's activity: the midpoint "
        "of the window, or the only known year.",
    )
    floruit_period: str | None = Field(
        None, description="The activity window as a label, e.g. '1962-1987'."
    )
    floruit_period_start: int | None = Field(
        None,
        description="First year of the activity window. By convention an individual is active "
        "from age 30, or from the death year when they died before 30.",
    )
    floruit_period_end: int | None = Field(
        None,
        description="Last year of the activity window. By convention age 60, or the year "
        "before death when they died before 60.",
    )
    method: FloruitMethod | None = Field(
        None,
        description="How the window was derived, as <anchor>_<evidence>: which dates were "
        "available (birth only, birth and death, floruit, works) and how they were read.",
    )
    source: FloruitSource | None = Field(
        None,
        description="Where the dates came from: a Wikidata property, the Wikidata "
        "description text, the works table, the life-expectancy model, CVDB, or Wikipedia.",
    )
    precision_class: PrecisionClass | None = Field(
        None,
        description="How precisely the window is known: to the year, the decade, or only "
        "the century. Use it to exclude vague individuals from an analysis.",
    )
    estimated: int | None = Field(
        None,
        ge=0,
        le=1,
        description="1 if the window rests on the life-expectancy model rather than on "
        "attested dates, else 0.",
    )
    works_period: str | None = Field(
        None, description="Works-derived year span. Mirrors `individuals.works_period`."
    )


class IndividualCliopatria(Table):
    table_name: ClassVar[str] = "individuals_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID = Field(
        ...,
        description="Wikidata identifier of the individual. NOT unique: one person overlapping "
        "several polities has one row per polity.",
    )
    name_en: str | None = Field(None, description="Full name in English, copied from `individuals`.")
    polity_id: int = Field(..., description="Polity the individual is attached to. Joins `polities_cliopatria.id`.")
    polity_name: str | None = Field(
        None, description="Name of the polity, e.g. 'Ottoman Empire'. Copied from `polities_cliopatria.name`."
    )
    origin: CliopatriaOrigin | None = Field(
        None,
        description="Which attribute of the individual placed them in the polity: their "
        "birthplace, their deathplace, or their country of citizenship.",
    )
    matched_name: str | None = Field(
        None, description="Name of the city or country that produced the match."
    )
    matched_wikidata_id: str | None = Field(
        None, description="Wikidata id of the matched city or country."
    )
    method: CliopatriaMethod | None = Field(
        None,
        description="How the match was made: the place fell inside the polity's polygon, "
        "or the two shared a Wikipedia URL.",
    )
    floruit_year: int | None = Field(
        None, description="Floruit year used to test the overlap with the polity's periods."
    )
    floruit_period_start: int | None = Field(None, description="First year of the activity window.")
    floruit_period_end: int | None = Field(None, description="Last year of the activity window.")
    overlap_years: int | None = Field(
        None,
        description="Number of years of the activity window covered by this polity, summed "
        "over all of its periods. Use it to pick the dominant polity of a multi-polity individual.",
    )


class IndividualCliopatriaPotential(Table):
    table_name: ClassVar[str] = "individuals_cliopatria_potential"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual.")
    floruit_year: int | None = Field(
        None, description="Floruit year used when testing the candidate matches."
    )
    polygon_deathplace: bool | None = Field(
        None, description="True if the death place falls inside some polity polygon."
    )
    polygon_birthplace: bool | None = Field(
        None, description="True if the birth place falls inside some polity polygon."
    )
    polygon_country_of_citizenship: bool | None = Field(
        None, description="True if the country of citizenship falls inside some polity polygon."
    )
    url_country_of_citizenship: bool | None = Field(
        None, description="True if the country of citizenship matched a polity by Wikipedia URL."
    )
    url_deathplace: bool | None = Field(
        None, description="True if the death place matched a polity by Wikipedia URL."
    )
    url_birthplace: bool | None = Field(
        None, description="True if the birth place matched a polity by Wikipedia URL."
    )


class Work(Table):
    table_name: ClassVar[str] = "works"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int = Field(..., description="Surrogate primary key, autoincremented.")
    individual_id: QID = Field(
        ..., description="Wikidata identifier of the individual. Joins `individuals.wikidata_id`."
    )
    individual_name: str | None = Field(
        None, description="Name of the individual, copied from `individuals.name_en`."
    )
    work_id: str | None = Field(None, description="Wikidata identifier of the work.")
    work_name: str | None = Field(None, description="Title of the work.")
    relationship: Relationship | None = Field(
        None,
        description="Role the individual played in the work. The live column mixes role "
        "labels with the raw Wikidata property ids for the same roles; both are accepted "
        "and normalized to the label.",
    )
    instance_of: str | None = Field(
        None, description="Wikidata P31 class ids of the work, pipe-joined."
    )
    instance_of_en: str | None = Field(
        None, description="English labels of the P31 classes, pipe-joined, index-aligned with `instance_of`."
    )
    inception_date: str | None = Field(
        None, description="Date the work was created (Wikidata P571), ISO timestamp."
    )
    inception_precision: int | None = Field(
        None, description=f"Precision of `inception_date`. {PRECISION}"
    )
    publication_date: str | None = Field(
        None, description="Date the work was published (Wikidata P577), ISO timestamp."
    )
    publication_precision: int | None = Field(
        None, description=f"Precision of `publication_date`. {PRECISION}"
    )

    @field_validator("relationship", mode="before")
    @classmethod
    def normalize_relationship(cls, value: object) -> object:
        if isinstance(value, str):
            return RELATIONSHIP_FROM_PROPERTY.get(value, value)
        return value


class Occupation(Table):
    table_name: ClassVar[str] = "occupations"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID = Field(..., description="Wikidata identifier of the occupation.")
    name_en: str | None = Field(None, description="Name of the occupation in English.")
    meta_occupation: MetaOccupation | None = Field(
        None,
        description="Coarse split into scientist or artist. NULL for every occupation that "
        "is neither.",
    )
    count: int | None = Field(None, description="Number of individuals holding this occupation.")
    description_en: str | None = Field(
        None, description="Wikidata description of the occupation."
    )
    level1_main_occ: Level1Occupation | None = Field(
        None,
        description="Top tier of the occupation ontology — the grouping used in the paper's "
        "figures. 'Missing' means the occupation was not classified.",
    )
    level2_main_occ: str | None = Field(
        None,
        description="Mid tier of the ontology, e.g. 'Culture-core', 'Academia', 'Politics', "
        "'Religious', 'Military', 'Nobility'.",
    )
    level3_main_occ: str | None = Field(
        None,
        description="Fine tier of the ontology, e.g. 'politician', 'writer', 'actor', "
        "'painter', 'historian'.",
    )
    ontology_n_votes: int | None = Field(
        None,
        description="Number of votes backing the ontology assignment. Low values mark a "
        "weakly supported classification.",
    )


class CountryOfCitizenship(Table):
    table_name: ClassVar[str] = "country_of_citizenship"
    primary_key: ClassVar[tuple[str, ...]] = ("wikidata_id",)

    wikidata_id: QID = Field(
        ..., description="Wikidata identifier of the country, historical entities included."
    )
    name_en: str | None = Field(None, description="Name of the country in English.")
    count: int | None = Field(
        None, description="Number of individuals holding this country as citizenship."
    )
    description_en: str | None = Field(None, description="Wikidata description of the country.")
    instance_of: str | None = Field(
        None, description="Wikidata class of the entity, as a label, e.g. 'sovereign state'."
    )
    en_wikipedia_url: str | None = Field(
        None, description="URL of the English Wikipedia article, used to match Cliopatria polities."
    )
    lat: float | None = Field(None, description="Latitude of the country's centroid, degrees.")
    lon: float | None = Field(None, description="Longitude of the country's centroid, degrees.")
    iso_country_name: str | None = Field(
        None,
        description="Modern country this entity maps onto, so historical citizenships can be "
        "aggregated on today's borders.",
    )
    iso_a3_code: str | None = Field(
        None, description="ISO 3166-1 alpha-3 code of `iso_country_name`, e.g. 'FRA'."
    )
    iso_modern_country_origin: str | None = Field(
        None, description="How the mapping onto the modern country was resolved."
    )
    instance_qids: str | None = Field(
        None, description="Wikidata P31 class ids of the entity, semicolon-separated."
    )
    instance_labels: str | None = Field(
        None, description="English labels of `instance_qids`, semicolon-separated and index-aligned."
    )
    inception: str | None = Field(
        None, description="Date the entity came into being (Wikidata P571)."
    )
    dissolved: str | None = Field(
        None, description="Date the entity ceased to exist (Wikidata P576)."
    )


class Place(Table):
    table_name: ClassVar[str] = "places"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID = Field(..., description="Wikidata identifier of the place.")
    name_en: str | None = Field(None, description="Name of the place in English.")
    lat: float | None = Field(
        None, description="Latitude in degrees. Used to test whether the place falls in a polity polygon."
    )
    lon: float | None = Field(None, description="Longitude in degrees.")
    original_country_name: str | None = Field(
        None, description="Country the place belongs to according to Wikidata."
    )
    original_country_name_id: str | None = Field(
        None, description="Wikidata id of `original_country_name`."
    )
    en_wikipedia_url_original_country_name: str | None = Field(
        None, description="English Wikipedia URL of that country."
    )
    iso_country_name: str | None = Field(
        None, description="Modern country the place maps onto."
    )
    iso_a3_code: str | None = Field(
        None, description="ISO 3166-1 alpha-3 code of `iso_country_name`."
    )
    entity_type: str | None = Field(
        None, description="Wikidata class label, e.g. 'village', 'city in the United States'."
    )
    entity_type_ids: str | None = Field(
        None, description="Wikidata P31 class ids of the place, semicolon-separated."
    )
    is_urban_settlement: int | None = Field(
        None, ge=0, le=1, description="1 if the place is classified as an urban settlement, else 0."
    )
    inception_date: str | None = Field(
        None, description="Date the place was founded (Wikidata P571), ISO timestamp."
    )
    inception_precision: int | None = Field(
        None, description=f"Precision of `inception_date`. {PRECISION}"
    )
    dissolution_date: str | None = Field(
        None, description="Date the place ceased to exist (Wikidata P576), ISO timestamp."
    )
    dissolution_precision: int | None = Field(
        None, description=f"Precision of `dissolution_date`. {PRECISION}"
    )


class WritingLanguage(Table):
    table_name: ClassVar[str] = "writing_languages"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: QID = Field(..., description="Wikidata identifier of the language.")
    name: str | None = Field(None, description="Name of the language in English.")
    count: int | None = Field(None, description="Number of individuals who wrote in it.")


class IndividualWritingLanguage(Table):
    table_name: ClassVar[str] = "individual_writing_languages"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID = Field(
        ...,
        description="Wikidata identifier of the individual. NOT unique: one row per language "
        "the individual wrote in.",
    )
    individual_name: str | None = Field(
        None, description="Name of the individual, copied from `individuals.name_en`."
    )
    language_id: str | None = Field(
        None, description="Wikidata id of the language. Joins `writing_languages.id`."
    )
    language_name: str | None = Field(
        None, description="Name of the language, copied from `writing_languages.name`."
    )


class Identifier(Table):
    table_name: ClassVar[str] = "identifiers"
    primary_key: ClassVar[tuple[str, ...]] = ()

    wikidata_id: QID = Field(
        ...,
        description="Wikidata identifier of the individual. NOT unique: one row per external "
        "database the individual appears in.",
    )
    individual_name: str | None = Field(
        None, description="Name of the individual, copied from `individuals.name_en`."
    )
    property_id: str | None = Field(
        None,
        description="Wikidata property that carries the identifier, e.g. P214 for VIAF. "
        "Joins `identifier_types.property_id`.",
    )
    identifier_name: str | None = Field(
        None, description="Name of the external system, copied from `identifier_types.name_en`."
    )
    value: str | None = Field(None, description="The identifier itself, as issued by that system.")
    url: str | None = Field(None, description="Direct link to the individual's external record.")


class IdentifierType(Table):
    table_name: ClassVar[str] = "identifier_types"
    primary_key: ClassVar[tuple[str, ...]] = ("property_id",)

    property_id: str = Field(
        ..., description="Wikidata property that carries this identifier, e.g. P214."
    )
    name_en: str | None = Field(None, description="Name of the external database in English.")
    count: int | None = Field(
        None, description="Number of individuals carrying an identifier from this database."
    )
    description: str | None = Field(None, description="Wikidata description of the property.")
    issuer_name: str | None = Field(
        None, description="Organization that issues the identifiers, e.g. a national library."
    )
    issuer_id: str | None = Field(None, description="Wikidata id of the issuer.")
    issuer_instance: str | None = Field(
        None, description="Wikidata class of the issuer, e.g. 'national library'."
    )
    country_name: str | None = Field(
        None,
        description="Country of the issuer. Use it to weigh how national the coverage of a "
        "database is.",
    )
    country_id: str | None = Field(None, description="Wikidata id of that country.")
    inception: str | None = Field(None, description="Year the external database was created.")
    database_records: str | None = Field(
        None, description="Total number of records in the external database, stored as text."
    )
    website: str | None = Field(None, description="Official URL of the external database.")


class WikimediaLink(Table):
    table_name: ClassVar[str] = "wikimedia_links"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int = Field(..., description="Surrogate primary key.")
    wikidata_id: QID = Field(
        ...,
        description="Wikidata identifier of the individual. NOT unique: one row per language "
        "edition. These rows are what the notability scores count.",
    )
    individual_name: str | None = Field(
        None, description="Name of the individual, copied from `individuals.name_en`."
    )
    site: str | None = Field(
        None, description="Wikipedia edition code, e.g. 'frwiki' for the French Wikipedia."
    )
    title: str | None = Field(None, description="Title of the article in that edition.")
    url: str | None = Field(None, description="Full URL of the article.")


class PolityCliopatria(Table):
    table_name: ClassVar[str] = "polities_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int = Field(..., description="Polity identifier, from the Cliopatria dataset.")
    name: str | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    type: PolityType | None = Field(
        None,
        description="POLITY for a state, RELATION for a dependency link between two polities.",
    )
    wikipedia_url: str | None = Field(
        None, description="English Wikipedia URL, used to match Wikidata places and countries."
    )
    wikidata_id: str | None = Field(None, description="Wikidata id of the polity, when known.")
    number_individuals: int | None = Field(
        None, description="Number of individuals matched to this polity in `individuals_cliopatria`."
    )


class PolityPeriodCliopatria(Table):
    table_name: ClassVar[str] = "polities_periods_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ("id",)

    id: int = Field(..., description="Surrogate primary key of the period.")
    polity_id: int = Field(
        ...,
        description="Polity this period belongs to. Joins `polities_cliopatria.id`. A polity "
        "has many periods, one per territorial change.",
    )
    polity_name: str | None = Field(
        None, description="Name of the polity, copied from `polities_cliopatria.name`."
    )
    from_year: int | None = Field(
        None, description="First year of the period. Negative for BCE."
    )
    to_year: int | None = Field(None, description="Last year of the period. Negative for BCE.")
    area: float | None = Field(None, description="Area of the territory in square kilometres.")
    geometry: str | None = Field(
        None,
        description="Territory as a GeoJSON polygon. This is what decides whether a birth or "
        "death place falls inside the polity.",
    )


class PolityModernCountryCliopatria(Table):
    table_name: ClassVar[str] = "polities_modern_countries_cliopatria"
    primary_key: ClassVar[tuple[str, ...]] = ()

    polity_id: int = Field(
        ...,
        description="Historical polity. Joins `polities_cliopatria.id`. NOT unique: a polity "
        "spanning several modern countries has one row per country.",
    )
    polity_name: str | None = Field(
        None, description="Name of the polity, copied from `polities_cliopatria.name`."
    )
    country_qid: str | None = Field(None, description="Wikidata id of the modern country.")
    country_name: str | None = Field(None, description="English name of the modern country.")
    iso_a3_code: str | None = Field(
        None, description="ISO 3166-1 alpha-3 code of the modern country."
    )
    continent: str | None = Field(
        None, description="Continent of the modern country, from Wikidata P30."
    )
    sources: str | None = Field(
        None,
        description="Wikidata property paths that produced the mapping, pipe-joined: "
        "P17, P36/P17, P1366/P17, P131/P17.",
    )


class WikidataPropertyDefinition(Table):
    table_name: ClassVar[str] = "wikidata_properties_definition"
    primary_key: ClassVar[tuple[str, ...]] = ()

    property_id: str = Field(
        ..., description="Wikidata property the data was extracted from, e.g. P569 for date of birth."
    )
    property_name: str | None = Field(None, description="Label of the property.")
    description: str | None = Field(None, description="Wikidata description of the property.")
    table_name_: str | None = Field(
        None,
        alias="table_name",
        description="Table the property feeds. Aliased in Python because `table_name` is "
        "reserved on the model.",
    )
    column_name: str | None = Field(None, description="Column the property feeds in that table.")


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


def demo() -> None:
    assert len(TABLES) == len(MODELS) == 18, "table names must be unique"

    undescribed = [
        f"{model.table_name}.{name}"
        for model in MODELS
        for name, field in model.model_fields.items()
        if not field.description
    ]
    assert not undescribed, f"fields without a description: {undescribed}"

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

    assert Work(id=1, individual_id="Q937", relationship="P50").relationship == "author"
    assert Work(id=2, individual_id="Q937", relationship="author").relationship == "author"

    for model, kwargs in [
        (Work, {"id": 3, "individual_id": "Q937", "relationship": "sculptor"}),
        (IndividualFloruitPeriod, {"wikidata_id": "Q937", "source": "guesswork"}),
        (Individual, {"wikidata_id": "not-a-qid"}),
        (Individual, {"wikidata_id": "Q937", "unknown_column": 1}),
        (Individual, {"wikidata_id": "Q937", "non_human": 2}),
    ]:
        try:
            model(**kwargs)
        except Exception:
            pass
        else:
            raise AssertionError(f"{model.__name__} accepted {kwargs}")

    assert IndividualFloruitPeriod(wikidata_id="Q859", works_period="-558").works_period

    print(f"OK — {len(TABLES)} tables, {sum(len(m.model_fields) for m in MODELS)} columns, all described")


if __name__ == "__main__":
    demo()
