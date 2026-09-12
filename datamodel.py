"""Cultura data model — the single source of truth for the database schema.

One Pydantic model per table of `data/humans_clean.duckdb`. Every field of every
table is declared here, in the same order as the database, and every field
carries a description.

Every value also carries its origin, because a value without a provenance is not
reproducible. A field's type says where it comes from:

    Wikidata[T]   pulled from a Wikidata property — carries the property id, its
                  label, its definition, and the extraction date. The date is
                  mandatory: Wikidata is edited continuously.
    External[T]   taken from another dataset (Pantheon 2.0, CVDB, Cliopatria,
                  Wikipedia, Treccani) — carries the platform and the date.
    Derived[T]    computed from other columns — carries those columns and the rule.
    AIAnswer[T]   produced by a language model — carries the exact model id and
                  the exact prompt.

The identifier columns stay plain: a key is the identity of the row, not a
sourced value.

Verified against the live database on 2026-09-12 (DuckDB v1.5.2): all 18 tables
and 196 columns match — nothing missing, nothing invented. The Wikidata property
ids below come from the database's own `wikidata_properties_definition` table.
The closed vocabularies were read from the data itself rather than from
`docs/DATABASE_SCHEMA.md`, which was out of date on two of them.

Usage:
    from datamodel import TABLES, Individual, Wikidata
    Individual.model_validate(row)
    TABLES["individuals"].model_fields

Self-check: `python datamodel.py`
"""

from datetime import date
from typing import Annotated, Generic, Literal, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

T = TypeVar("T")

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]

ExternalPlatform = Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia", "treccani"]


class Wikidata(BaseModel, Generic[T]):
    property_id: str = Field(..., description="Wikidata property the value was read from, e.g. 'P569'. Non-property sources use their RDF term, e.g. 'rdfs:label'.")
    property_name: str = Field(..., description="Label of the property, e.g. 'date of birth'.")
    property_definition: str = Field(..., description="Wikidata definition of the property, e.g. 'date on which the subject was born'.")
    value: T | None = Field(None, description="The value itself, exactly as read from Wikidata.")
    date_of_extraction: date = Field(..., description="Day the value was pulled from Wikidata. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")


class External(BaseModel, Generic[T]):
    platform: ExternalPlatform = Field(..., description="Dataset the value was taken from.")
    value: T | None = Field(None, description="The value itself, as read from that dataset.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset, when it publishes one.")
    date_of_extraction: date = Field(..., description="Day the value was taken from the dataset.")


class Derived(BaseModel, Generic[T]):
    value: T | None = Field(None, description="The computed value.")
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Columns the value was computed from, as 'table.column'.")
    rule: str = Field(..., description="The rule applied to those columns, in one sentence.")
    computed_on: date | None = Field(None, description="Day the computation was run.")


class AIAnswer(BaseModel, Generic[T]):
    value: T | None = Field(None, description="The value the model returned.")
    model: str = Field(..., description="Exact model id that produced the value, e.g. 'claude-opus-5'.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim, including any formatting instructions.")
    answered_on: date | None = Field(None, description="Day the model was queried.")


Relationship = Literal["author", "composer", "creator", "director", "editor", "illustrator", "performer", "producer", "screenwriter"]

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

FloruitSource = Literal["wikidata_property", "wikidata_description", "works", "life_expectancy", "cv_database", "wikipedia", "none"]

PrecisionClass = Literal["year", "decade", "century"]

LifeExpectancyLookupSource = Literal["birth_bin", "category+birth_bin:Leadership", "category+birth_bin:Culture", "category+birth_bin:Sports/Games", "category+birth_bin:Discovery/Science", "category+birth_bin:Other"]

MetaOccupation = Literal["scientist", "artist"]

Level1Occupation = Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]

PolityType = Literal["POLITY", "RELATION"]

PRECISION = "Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium."


class Table(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Individual(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual, e.g. Q937 for Albert Einstein. Primary key.")
    name_en: Wikidata[str] | None = Field(None, description="Full name of the individual in English. Wikidata rdfs:label.")
    description_en: Wikidata[str] | None = Field(None, description="Short Wikidata description, e.g. 'German-born theoretical physicist'. Wikidata schema:description.")
    birthdate: Wikidata[str] | None = Field(None, description="Date of birth as an ISO string; a negative year means BCE. Wikidata P569 'date of birth'.")
    birthdate_precision: Wikidata[int] | None = Field(None, description=f"Precision of `birthdate`, as returned with P569. {PRECISION}")
    deathdate: Wikidata[str] | None = Field(None, description="Date of death as an ISO string; a negative year means BCE. Wikidata P570 'date of death'.")
    deathdate_precision: Wikidata[int] | None = Field(None, description=f"Precision of `deathdate`, as returned with P570. {PRECISION}")
    country_of_citizenship_en: Wikidata[str] | None = Field(None, description="English labels of the countries of citizenship, semicolon-separated when several. Wikidata P27 'country of citizenship'.")
    birthcity_en: Wikidata[str] | None = Field(None, description="English name of the city of birth. Wikidata P19 'place of birth'.")
    deathcity_en: Wikidata[str] | None = Field(None, description="English name of the city of death. Wikidata P20 'place of death'.")
    occupations_en: Wikidata[str] | None = Field(None, description="English occupation labels, semicolon-separated when several. Wikidata P106 'occupation'.")
    wikimedia_links_count: Derived[int] | None = Field(None, description="Number of Wikipedia articles about the individual across all languages. Counted over `wikimedia_links`.")
    gender: Wikidata[str] | None = Field(None, description="Gender label. Free text, not a closed vocabulary: 48 distinct values in the data, a few of them unresolved ids. Wikidata P21 'sex or gender'.")
    identifiers_count: Derived[int] | None = Field(None, description="Number of external-database identifiers held by the individual. Counted over `identifiers`.")
    writing_language_name_en: Wikidata[str] | None = Field(None, description="English names of the languages the individual wrote in, semicolon-separated. Wikidata P6886 'writing language'.")
    number_of_works: Derived[int] | None = Field(None, description="Number of works credited to the individual. Counted over `works`.")
    floruit_date: Wikidata[str] | None = Field(None, description="Floruit as declared by Wikidata, ISO string. Set only where Wikidata carries the property. Wikidata P1317 'floruit'.")
    floruit_precision: Wikidata[int] | None = Field(None, description=f"Precision of `floruit_date`, as returned with P1317. {PRECISION}")
    floruit_year: Derived[int] | None = Field(None, description="Single year representing the individual's activity, resolved from whatever evidence exists. Copied from `individuals_floruit_period`.")
    dates_in_description: Derived[str] | None = Field(None, description="Year span parsed out of the Wikidata description, e.g. '1937-2016'; a single year when only one was found.")
    birthdate_in_description: Derived[int] | None = Field(None, description="Birth year parsed out of the Wikidata description. NULL when none was found.")
    deathdate_in_description: Derived[int] | None = Field(None, description="Death year parsed out of the Wikidata description.")
    floruit_year_in_description: Derived[int] | None = Field(None, description="Floruit year parsed out of the Wikidata description.")
    date_description: Derived[str] | None = Field(None, description="Raw date substring matched in the Wikidata description before parsing. Kept so the extraction can be audited.")
    pantheon_2_db: External[int] | None = Field(None, description="1 if the individual appears in the Pantheon 2.0 dataset, else 0.")
    cross_verified_db: External[int] | None = Field(None, description="1 if the individual appears in the cross-verified database (CVDB), else 0.")
    non_human: Derived[int] | None = Field(None, description="1 if the row is not actually a human (872 rows), else 0. Filter these out of any analysis.")
    works_period: Derived[str] | None = Field(None, description="Span of years over which the individual produced works, e.g. '1892-1964', or a single year when first equals last. NULL when no work is dated.")
    notability_western: Derived[int] | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    notability_non_western: Derived[int] | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    notability_general: Derived[float] | None = Field(None, description="Geometric mean of the two notability scores (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")
    birthdate_from_CV: External[str] | None = Field(None, description="Birth date taken from the cross-verified database, used where Wikidata has none.")
    deathdate_from_CV: External[str] | None = Field(None, description="Death date taken from the cross-verified database, used where Wikidata has none.")
    birthdate_from_life_expectancy: Derived[str] | None = Field(None, description="Birth date estimated from the death date and a median life expectancy, when only the death date is known.")
    deathdate_from_life_expectancy: Derived[str] | None = Field(None, description="Death date estimated from the birth date and a median life expectancy, when only the birth date is known.")
    life_expectancy_lookup_source: Derived[LifeExpectancyLookupSource] | None = Field(None, description="Which life-expectancy table produced the estimate: the overall birth bin, or the birth bin within an occupation category.")
    life_expectancy_median_used: Derived[float] | None = Field(None, description="Median life expectancy in years applied to build the estimate.")
    birthdate_from_wikipedia: External[str] | None = Field(None, description="Birth date scraped from the individual's Wikipedia article.")
    deathdate_from_wikipedia: External[str] | None = Field(None, description="Death date scraped from the individual's Wikipedia article.")
    floruit_from_wikipedia: External[str] | None = Field(None, description="Floruit scraped from the individual's Wikipedia article.")
    is_artist: Derived[bool] | None = Field(None, description="Artist flag. Unpopulated in the live database (all NULL) — derive it from `occupations.level1_main_occ` instead.")
    is_scientist: Derived[bool] | None = Field(None, description="Scientist flag. Unpopulated in the live database (all NULL) — derive it from `occupations.level1_main_occ` instead.")


class IndividualKeys(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. Primary key.")
    birthcity_id: Wikidata[str] | None = Field(None, description="Wikidata id of the city of birth; joins `places.id`. Wikidata P19 'place of birth'.")
    deathcity_id: Wikidata[str] | None = Field(None, description="Wikidata id of the city of death; joins `places.id`. Wikidata P20 'place of death'.")
    country_of_citizenship_ids: Wikidata[str] | None = Field(None, description="Wikidata ids of the countries of citizenship, semicolon-separated and index-aligned with the labels on `individuals`. Wikidata P27 'country of citizenship'.")
    occupations_ids: Wikidata[str] | None = Field(None, description="Wikidata ids of the occupations, semicolon-separated and index-aligned with the labels on `individuals`; joins `occupations.id`. Wikidata P106 'occupation'.")
    gender_id: Wikidata[str] | None = Field(None, description="Wikidata id behind the gender label, e.g. Q6581097 for male. Wikidata P21 'sex or gender'.")
    writing_language_ids: Wikidata[str] | None = Field(None, description="Wikidata ids of the writing languages, semicolon-separated; joins `writing_languages.id`. Wikidata P6886 'writing language'.")


class IndividualFloruitPeriod(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. Primary key.")
    name_en: Wikidata[str] | None = Field(None, description="Full name of the individual in English. Wikidata rdfs:label.")
    birthdate: Derived[str] | None = Field(None, description="Birth date used as input, ISO string, picked from whichever source had one — see `source`.")
    birthdate_precision: Derived[int] | None = Field(None, description=f"Precision of `birthdate`. {PRECISION}")
    birth_year: Derived[int] | None = Field(None, description="Birth year parsed from `birthdate`. Negative for BCE.")
    deathdate: Derived[str] | None = Field(None, description="Death date used as input, ISO string, picked from whichever source had one — see `source`.")
    deathdate_precision: Derived[int] | None = Field(None, description=f"Precision of `deathdate`. {PRECISION}")
    death_year: Derived[int] | None = Field(None, description="Death year parsed from `deathdate`. Negative for BCE.")
    floruit_date: Derived[str] | None = Field(None, description="Floruit date used as input, ISO string, picked from whichever source had one.")
    floruit_precision: Derived[int] | None = Field(None, description=f"Precision of `floruit_date`. {PRECISION}")
    floruit_year: Derived[int] | None = Field(None, description="The single year that represents the individual's activity: the midpoint of the window, or the only known year.")
    floruit_period: Derived[str] | None = Field(None, description="The activity window as a label, e.g. '1962-1987'.")
    floruit_period_start: Derived[int] | None = Field(None, description="First year of the activity window. By convention an individual is active from age 30, or from the death year when they died before 30.")
    floruit_period_end: Derived[int] | None = Field(None, description="Last year of the activity window. By convention age 60, or the year before death when they died before 60.")
    method: Derived[FloruitMethod] | None = Field(None, description="How the window was derived, as <anchor>_<evidence>: which dates were available (birth only, birth and death, floruit, works) and how they were read.")
    source: Derived[FloruitSource] | None = Field(None, description="Where the dates came from: a Wikidata property, the Wikidata description text, the works table, the life-expectancy model, CVDB, or Wikipedia.")
    precision_class: Derived[PrecisionClass] | None = Field(None, description="How precisely the window is known: to the year, the decade, or only the century. Use it to exclude vague individuals from an analysis.")
    estimated: Derived[int] | None = Field(None, description="1 if the window rests on the life-expectancy model rather than on attested dates, else 0.")
    works_period: Derived[str] | None = Field(None, description="Works-derived year span. Mirrors `individuals.works_period`.")


class IndividualCliopatria(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. NOT unique: one row per polity the individual overlaps.")
    name_en: Wikidata[str] | None = Field(None, description="Full name of the individual in English. Wikidata rdfs:label.")
    polity_id: int = Field(..., description="Polity the individual is attached to; joins `polities_cliopatria.id`.")
    polity_name: External[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    origin: Derived[CliopatriaOrigin] | None = Field(None, description="Which attribute of the individual placed them in the polity: their birthplace, their deathplace, or their country of citizenship.")
    matched_name: Derived[str] | None = Field(None, description="Name of the city or country that produced the match.")
    matched_wikidata_id: Derived[str] | None = Field(None, description="Wikidata id of the matched city or country.")
    method: Derived[CliopatriaMethod] | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
    floruit_year: Derived[int] | None = Field(None, description="Floruit year used to test the overlap with the polity's periods.")
    floruit_period_start: Derived[int] | None = Field(None, description="First year of the individual's activity window.")
    floruit_period_end: Derived[int] | None = Field(None, description="Last year of the individual's activity window.")
    overlap_years: Derived[int] | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")


class IndividualCliopatriaPotential(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. Primary key.")
    floruit_year: Derived[int] | None = Field(None, description="Floruit year used when testing the candidate matches.")
    polygon_deathplace: Derived[bool] | None = Field(None, description="True if the death place falls inside some polity polygon.")
    polygon_birthplace: Derived[bool] | None = Field(None, description="True if the birth place falls inside some polity polygon.")
    polygon_country_of_citizenship: Derived[bool] | None = Field(None, description="True if the country of citizenship falls inside some polity polygon.")
    url_country_of_citizenship: Derived[bool] | None = Field(None, description="True if the country of citizenship matched a polity by Wikipedia URL.")
    url_deathplace: Derived[bool] | None = Field(None, description="True if the death place matched a polity by Wikipedia URL.")
    url_birthplace: Derived[bool] | None = Field(None, description="True if the birth place matched a polity by Wikipedia URL.")


class Work(Table):
    id: int = Field(..., description="Surrogate primary key, autoincremented.")
    individual_id: QID = Field(..., description="Wikidata identifier of the individual; joins `individuals.wikidata_id`.")
    individual_name: Wikidata[str] | None = Field(None, description="Name of the individual in English. Wikidata rdfs:label.")
    work_id: Wikidata[str] | None = Field(None, description="Wikidata identifier of the work.")
    work_name: Wikidata[str] | None = Field(None, description="Title of the work. Wikidata rdfs:label.")
    relationship: Wikidata[Relationship] | None = Field(None, description="Role the individual played in the work, one of nine Wikidata credit properties (P50 author, P57 director, P58 screenwriter, P86 composer, P98 editor, P110 illustrator, P162 producer, P170 creator, P175 performer). The live column mixes labels with raw property ids; both are accepted and normalized to the label.")
    instance_of: Wikidata[str] | None = Field(None, description="Wikidata class ids of the work, pipe-joined. Wikidata P31 'instance of'.")
    instance_of_en: Wikidata[str] | None = Field(None, description="English labels of the classes, pipe-joined and index-aligned with `instance_of`. Wikidata P31 'instance of'.")
    inception_date: Wikidata[str] | None = Field(None, description="Date the work was created, ISO timestamp. Wikidata P571 'inception'.")
    inception_precision: Wikidata[int] | None = Field(None, description=f"Precision of `inception_date`, as returned with P571. {PRECISION}")
    publication_date: Wikidata[str] | None = Field(None, description="Date the work was published, ISO timestamp. Wikidata P577 'publication date'.")
    publication_precision: Wikidata[int] | None = Field(None, description=f"Precision of `publication_date`, as returned with P577. {PRECISION}")

    @field_validator("relationship", mode="before")
    @classmethod
    def normalize_relationship(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            return value | {"value": RELATIONSHIP_FROM_PROPERTY.get(value["value"], value["value"])}
        return value


class Occupation(Table):
    id: QID = Field(..., description="Wikidata identifier of the occupation. Primary key. Wikidata P106 'occupation'.")
    name_en: Wikidata[str] | None = Field(None, description="Name of the occupation in English. Wikidata rdfs:label.")
    meta_occupation: AIAnswer[MetaOccupation] | None = Field(None, description="Coarse split into scientist or artist. NULL for every occupation that is neither.")
    count: Derived[int] | None = Field(None, description="Number of individuals holding this occupation. Counted over `individuals`.")
    description_en: Wikidata[str] | None = Field(None, description="Wikidata description of the occupation. Wikidata schema:description.")
    level1_main_occ: AIAnswer[Level1Occupation] | None = Field(None, description="Top tier of the occupation ontology — the grouping used in the paper's figures. 'Missing' means the occupation was not classified.")
    level2_main_occ: AIAnswer[str] | None = Field(None, description="Mid tier of the ontology, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'.")
    level3_main_occ: AIAnswer[str] | None = Field(None, description="Fine tier of the ontology, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'.")
    ontology_n_votes: Derived[int] | None = Field(None, description="Number of model votes backing the ontology assignment. Low values mark a weakly supported classification.")


class CountryOfCitizenship(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the country, historical entities included. Primary key. Wikidata P27 'country of citizenship'.")
    name_en: Wikidata[str] | None = Field(None, description="Name of the country in English. Wikidata rdfs:label.")
    count: Derived[int] | None = Field(None, description="Number of individuals holding this country as citizenship. Counted over `individuals`.")
    description_en: Wikidata[str] | None = Field(None, description="Wikidata description of the country. Wikidata schema:description.")
    instance_of: Wikidata[str] | None = Field(None, description="Wikidata class of the entity as a label, e.g. 'sovereign state'. Wikidata P31 'instance of'.")
    en_wikipedia_url: Wikidata[str] | None = Field(None, description="URL of the English Wikipedia article, used to match Cliopatria polities. Wikidata schema:about.")
    lat: Wikidata[float] | None = Field(None, description="Latitude in degrees, from the country's coordinates or its capital's. Wikidata P625 'coordinate location', falling back to P36 'capital'.")
    lon: Wikidata[float] | None = Field(None, description="Longitude in degrees, from the country's coordinates or its capital's. Wikidata P625 'coordinate location', falling back to P36 'capital'.")
    iso_country_name: Derived[str] | None = Field(None, description="Modern country this entity maps onto, so historical citizenships can be aggregated on today's borders.")
    iso_a3_code: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of `iso_country_name`, e.g. 'FRA'.")
    iso_modern_country_origin: Derived[str] | None = Field(None, description="How the mapping onto the modern country was resolved.")
    instance_qids: Wikidata[str] | None = Field(None, description="Wikidata class ids of the entity, semicolon-separated. Wikidata P31 'instance of'.")
    instance_labels: Wikidata[str] | None = Field(None, description="English labels of `instance_qids`, semicolon-separated and index-aligned. Wikidata P31 'instance of'.")
    inception: Wikidata[str] | None = Field(None, description="Date the entity came into being. Wikidata P571 'inception'.")
    dissolved: Wikidata[str] | None = Field(None, description="Date the entity ceased to exist. Wikidata P576 'dissolved, abolished or demolished date'.")


class Place(Table):
    id: QID = Field(..., description="Wikidata identifier of the place. Primary key.")
    name_en: Wikidata[str] | None = Field(None, description="Name of the place in English. Wikidata rdfs:label.")
    lat: Wikidata[float] | None = Field(None, description="Latitude in degrees. Used to test whether the place falls inside a polity polygon. Wikidata P625 'coordinate location'.")
    lon: Wikidata[float] | None = Field(None, description="Longitude in degrees. Wikidata P625 'coordinate location'.")
    original_country_name: Wikidata[str] | None = Field(None, description="Country the place belongs to according to Wikidata. Wikidata P17 'country'.")
    original_country_name_id: Wikidata[str] | None = Field(None, description="Wikidata id of `original_country_name`. Wikidata P17 'country'.")
    en_wikipedia_url_original_country_name: Wikidata[str] | None = Field(None, description="English Wikipedia URL of that country. Wikidata schema:about.")
    iso_country_name: Derived[str] | None = Field(None, description="Modern country the place maps onto.")
    iso_a3_code: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of `iso_country_name`.")
    entity_type: Wikidata[str] | None = Field(None, description="Wikidata class label, e.g. 'village', 'city in the United States'. Wikidata P31 'instance of'.")
    entity_type_ids: Wikidata[str] | None = Field(None, description="Wikidata class ids of the place, semicolon-separated. Wikidata P31 'instance of'.")
    is_urban_settlement: Derived[int] | None = Field(None, description="1 if the place is classified as an urban settlement, else 0.")
    inception_date: Wikidata[str] | None = Field(None, description="Date the place was founded, ISO timestamp. Wikidata P571 'inception'.")
    inception_precision: Wikidata[int] | None = Field(None, description=f"Precision of `inception_date`, as returned with P571. {PRECISION}")
    dissolution_date: Wikidata[str] | None = Field(None, description="Date the place ceased to exist, ISO timestamp. Wikidata P576 'dissolved, abolished or demolished date'.")
    dissolution_precision: Wikidata[int] | None = Field(None, description=f"Precision of `dissolution_date`, as returned with P576. {PRECISION}")


class WritingLanguage(Table):
    id: QID = Field(..., description="Wikidata identifier of the language. Primary key.")
    name: Wikidata[str] | None = Field(None, description="Name of the language in English. Wikidata rdfs:label.")
    count: Derived[int] | None = Field(None, description="Number of individuals who wrote in it. Counted over `individual_writing_languages`.")


class IndividualWritingLanguage(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. NOT unique: one row per language the individual wrote in.")
    individual_name: Wikidata[str] | None = Field(None, description="Name of the individual in English. Wikidata rdfs:label.")
    language_id: Wikidata[str] | None = Field(None, description="Wikidata id of the language; joins `writing_languages.id`. Wikidata P6886 'writing language'.")
    language_name: Wikidata[str] | None = Field(None, description="Name of the language in English. Wikidata rdfs:label.")


class Identifier(Table):
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. NOT unique: one row per external database the individual appears in.")
    individual_name: Wikidata[str] | None = Field(None, description="Name of the individual in English. Wikidata rdfs:label.")
    property_id: Wikidata[str] | None = Field(None, description="Wikidata property that carries the identifier, e.g. P214 for VIAF; joins `identifier_types.property_id`. Any external-id property.")
    identifier_name: Wikidata[str] | None = Field(None, description="Name of the external system. Wikidata rdfs:label of the property.")
    value: Wikidata[str] | None = Field(None, description="The identifier itself, as issued by that system. Any external-id property.")
    url: Wikidata[str] | None = Field(None, description="Direct link to the individual's external record, built from the property's URL formatter.")


class IdentifierType(Table):
    property_id: str = Field(..., description="Wikidata property that carries this identifier, e.g. P214. Primary key.")
    name_en: Wikidata[str] | None = Field(None, description="Name of the external database in English. Wikidata rdfs:label.")
    count: Derived[int] | None = Field(None, description="Number of individuals carrying an identifier from this database. Counted over `identifiers`.")
    description: Wikidata[str] | None = Field(None, description="Wikidata description of the property. Wikidata schema:description.")
    issuer_name: Wikidata[str] | None = Field(None, description="Organization that issues the identifiers, e.g. a national library. Wikidata P1629 'subject item of this property'.")
    issuer_id: Wikidata[str] | None = Field(None, description="Wikidata id of the issuer.")
    issuer_instance: Wikidata[str] | None = Field(None, description="Wikidata class of the issuer, e.g. 'national library'. Wikidata P31 'instance of'.")
    country_name: Wikidata[str] | None = Field(None, description="Country of the issuer. Use it to weigh how national a database's coverage is. Wikidata P17 'country'.")
    country_id: Wikidata[str] | None = Field(None, description="Wikidata id of that country. Wikidata P17 'country'.")
    inception: Wikidata[str] | None = Field(None, description="Year the external database was created. Wikidata P571 'inception'.")
    database_records: Wikidata[str] | None = Field(None, description="Total number of records in the external database, stored as text. Wikidata P4876 'number of records'.")
    website: Wikidata[str] | None = Field(None, description="Official URL of the external database. Wikidata P856 'official website'.")


class WikimediaLink(Table):
    id: int = Field(..., description="Surrogate primary key.")
    wikidata_id: QID = Field(..., description="Wikidata identifier of the individual. NOT unique: one row per language edition. These rows are what the notability scores count.")
    individual_name: Wikidata[str] | None = Field(None, description="Name of the individual in English. Wikidata rdfs:label.")
    site: Wikidata[str] | None = Field(None, description="Wikipedia edition code, e.g. 'frwiki' for the French Wikipedia. Wikidata schema:about sitelink.")
    title: Wikidata[str] | None = Field(None, description="Title of the article in that edition. Wikidata schema:about sitelink.")
    url: Wikidata[str] | None = Field(None, description="Full URL of the article. Wikidata schema:about sitelink.")


class PolityCliopatria(Table):
    id: int = Field(..., description="Polity identifier, from the Cliopatria dataset. Primary key.")
    name: External[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    type: External[PolityType] | None = Field(None, description="POLITY for a state, RELATION for a dependency link between two polities.")
    wikipedia_url: External[str] | None = Field(None, description="English Wikipedia URL, used to match Wikidata places and countries.")
    wikidata_id: Derived[str] | None = Field(None, description="Wikidata id of the polity, resolved from its Wikipedia URL. NULL where no match was found.")
    number_individuals: Derived[int] | None = Field(None, description="Number of individuals matched to this polity. Counted over `individuals_cliopatria`.")


class PolityPeriodCliopatria(Table):
    id: int = Field(..., description="Surrogate primary key of the period.")
    polity_id: int = Field(..., description="Polity this period belongs to; joins `polities_cliopatria.id`. A polity has many periods, one per territorial change.")
    polity_name: External[str] | None = Field(None, description="Name of the polity.")
    from_year: External[int] | None = Field(None, description="First year of the period. Negative for BCE.")
    to_year: External[int] | None = Field(None, description="Last year of the period. Negative for BCE.")
    area: External[float] | None = Field(None, description="Area of the territory in square kilometres.")
    geometry: External[str] | None = Field(None, description="Territory as a GeoJSON polygon. This is what decides whether a birth or death place falls inside the polity.")


class PolityModernCountryCliopatria(Table):
    polity_id: int = Field(..., description="Historical polity; joins `polities_cliopatria.id`. NOT unique: one row per modern country the polity spans.")
    polity_name: External[str] | None = Field(None, description="Name of the polity.")
    country_qid: Derived[str] | None = Field(None, description="Wikidata id of the modern country, reached from the polity through a Wikidata property path.")
    country_name: Wikidata[str] | None = Field(None, description="English name of the modern country. Wikidata rdfs:label.")
    iso_a3_code: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of the modern country.")
    continent: Wikidata[str] | None = Field(None, description="Continent of the modern country. Wikidata P30 'continent'.")
    sources: Derived[str] | None = Field(None, description="Wikidata property paths that produced the mapping, pipe-joined: P17, P36/P17, P1366/P17, P131/P17.")


class WikidataPropertyDefinition(Table):
    property_id: str = Field(..., description="Wikidata property the data was extracted from, e.g. P569 for date of birth.")
    property_name: Wikidata[str] | None = Field(None, description="Label of the property. Wikidata rdfs:label.")
    description: Wikidata[str] | None = Field(None, description="Wikidata description of the property. Wikidata schema:description.")
    table_name: str | None = Field(None, description="Table in this database that the property feeds.")
    column_name: str | None = Field(None, description="Column in that table that the property feeds.")


TABLES: dict[str, type[Table]] = {
    "individuals": Individual,
    "individuals_keys": IndividualKeys,
    "individuals_floruit_period": IndividualFloruitPeriod,
    "individuals_cliopatria": IndividualCliopatria,
    "individuals_cliopatria_potential": IndividualCliopatriaPotential,
    "works": Work,
    "occupations": Occupation,
    "country_of_citizenship": CountryOfCitizenship,
    "places": Place,
    "writing_languages": WritingLanguage,
    "individual_writing_languages": IndividualWritingLanguage,
    "identifiers": Identifier,
    "identifier_types": IdentifierType,
    "wikimedia_links": WikimediaLink,
    "polities_cliopatria": PolityCliopatria,
    "polities_periods_cliopatria": PolityPeriodCliopatria,
    "polities_modern_countries_cliopatria": PolityModernCountryCliopatria,
    "wikidata_properties_definition": WikidataPropertyDefinition,
}


def demo() -> None:
    assert len(TABLES) == 18, "one model per table"

    undescribed = [
        f"{table}.{name}"
        for table, model in TABLES.items()
        for name, field in model.model_fields.items()
        if not field.description
    ]
    assert not undescribed, f"fields without a description: {undescribed}"

    keys = {"wikidata_id", "id", "individual_id", "polity_id", "property_id", "table_name", "column_name"}
    originless = [
        f"{table}.{name}"
        for table, model in TABLES.items()
        for name, field in model.model_fields.items()
        if name not in keys and not any(isinstance(arg, type) and issubclass(arg, (Wikidata, External, Derived, AIAnswer)) for arg in get_args(field.annotation))
    ]
    assert not originless, f"fields without an origin model: {originless}"

    einstein = Individual(
        wikidata_id="Q937",
        name_en=Wikidata[str](
            property_id="rdfs:label",
            property_name="label (English)",
            property_definition="the English label of the entity",
            value="Albert Einstein",
            date_of_extraction=date(2026, 5, 2),
        ),
        birthdate=Wikidata[str](
            property_id="P569",
            property_name="date of birth",
            property_definition="date on which the subject was born",
            value="1879-03-14",
            date_of_extraction=date(2026, 5, 2),
        ),
        number_of_works=Derived[int](
            value=419,
            derived_from=("works.individual_id",),
            rule="count of rows in works for this individual",
            computed_on=date(2026, 5, 3),
        ),
        pantheon_2_db=External[int](
            platform="pantheon_2",
            value=1,
            dataset_version="2.0",
            date_of_extraction=date(2026, 3, 19),
        ),
    )
    assert einstein.birthdate.value == "1879-03-14"
    assert einstein.birthdate.date_of_extraction == date(2026, 5, 2)
    assert einstein.deathdate is None

    author = Work(
        id=1,
        individual_id="Q937",
        relationship={
            "property_id": "P50",
            "property_name": "author",
            "property_definition": "main creator(s) of a written work",
            "value": "P50",
            "date_of_extraction": "2026-05-03",
        },
    )
    assert author.relationship.value == "author", "a raw property id is normalized to its label"

    wikidata_kwargs = {
        "property_id": "P569",
        "property_name": "date of birth",
        "property_definition": "date on which the subject was born",
        "value": "1879-03-14",
    }
    for model, kwargs, why in [
        (Wikidata[str], wikidata_kwargs, "a Wikidata value must carry an extraction date"),
        (AIAnswer[str], {"value": "Culture"}, "an AI value must carry its model and prompt"),
        (Derived[int], {"value": 1, "rule": "counted"}, "a derived value must name its inputs"),
        (Derived[int], {"value": 1, "derived_from": (), "rule": "counted"}, "derived_from must not be empty"),
        (Individual, {"wikidata_id": "not-a-qid"}, "the primary key must be a QID"),
        (Individual, {"wikidata_id": "Q937", "unknown_column": 1}, "unknown columns are rejected"),
    ]:
        try:
            model(**kwargs)
        except Exception:
            pass
        else:
            raise AssertionError(f"accepted what it should reject: {why}")

    columns = sum(len(model.model_fields) for model in TABLES.values())
    print(f"OK — {len(TABLES)} tables, {columns} columns, all described and all carrying an origin")


if __name__ == "__main__":
    demo()
