import json
from datetime import date
from pathlib import Path
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

HERE = Path(__file__).parent

T = TypeVar("T")

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Wikidata(Model, Generic[T]):
    property: str = Field(..., description="Wikidata property the value was read from, e.g. 'P569'. Non-property sources keep their RDF term, e.g. 'rdfs:label'.")
    description: str | None = Field(None, description="What the property means, e.g. 'date on which the subject was born'. Read from properties.json and carried with the value, which is why no field annotated Wikidata[...] describes itself: the description is data, not schema.")
    value: T | None = Field(None, description="The value itself, exactly as read from Wikidata. Multi-valued fields are pipe-joined in Wikidata order.")
    label_en: str | None = Field(None, description="English label of `value` when the value is a qid, pipe-joined in the same order when it is several. Wikidata rdfs:label. It travels with the value, so no field needs an id / label twin.")
    date_of_extraction: date = Field(..., description="Day the value was pulled from Wikidata. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")


class External(Model, Generic[T]):
    platform: Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"] = Field(..., description="Dataset the value was taken from.")
    value: T | None = Field(None, description="The value itself, as read from that dataset.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset, as listed in sources.json.")
    date_of_extraction: date = Field(..., description="Day the value was taken from the dataset.")


class Derived(Model, Generic[T]):
    value: T | None = Field(None, description="The computed value.")
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Fields the value was computed from, as 'Model.field'.")
    rule: str = Field(..., description="The rule applied to those fields, in one sentence.")
    computed_on: date | None = Field(None, description="Day the computation was run.")


class AIAnswer(Model, Generic[T]):
    value: T | None = Field(None, description="The value the model returned.")
    model: str = Field(..., description="Exact model id that produced the value.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim.")
    answered_on: date | None = Field(None, description="Day the model was queried.")


PROPERTIES: dict[str, dict[str, str]] = json.loads((HERE / "properties.json").read_text())

ROLE_FROM_PROPERTY: dict[str, str] = {pid: p["credit_role"] for pid, p in PROPERTIES.items() if "credit_role" in p}

SOURCES: dict[str, dict[str, str]] = json.loads((HERE / "sources.json").read_text())


def urban_settlement_answer() -> "AIAnswer[bool]":
    return AIAnswer[bool](model="google/gemini-3-flash-preview", prompt=(HERE / "prompts/urban_settlement.txt").read_text().strip(), answered_on=date(2026, 4, 23))


def wikipedia_dates_answer() -> "AIAnswer[str]":
    return AIAnswer[str](model="google/gemini-2.5-flash-lite", prompt=(HERE / "prompts/wikipedia_dates.txt").read_text().strip(), answered_on=date(2026, 5, 6))


class Polity(Model):
    id: External[int] | None = Field(None, description="Polity identifier, from the Cliopatria dataset.")
    name: External[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    method: Derived[Literal["merge_with_polygon", "merge_with_url"]] | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
    matched: Derived[QID] | None = Field(None, description="The city or country that produced the match.")
    overlap_years: Derived[int] | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")


class Location(Model):
    qid: Wikidata[QID] | None = None
    lat: Wikidata[float] | None = None
    lon: Wikidata[float] | None = None
    entity_types: Wikidata[str] | None = None
    is_urban_settlement: AIAnswer[bool] | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
    country: Wikidata[QID] | None = None
    country_wikipedia_url: Wikidata[str] | None = None
    modern_country: Derived[str] | None = Field(None, description="Modern country the place maps onto, so historical data can be aggregated on today's borders.")
    modern_country_iso_a3: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, e.g. 'FRA'.")
    modern_country_resolved_by: Derived[str] | None = Field(None, description="How the mapping was resolved: 'reverse_geocode' (point-in-polygon on the coordinates), 'capital_city', 'qlever_relation', 'qlever_replaced_by', or 'unknown_legacy'.")
    inception: Wikidata[str] | None = None
    dissolution: Wikidata[str] | None = None
    polities: tuple[Polity, ...] = Field((), description="Historical polities whose territory covers this place, one entry per polity, empty when the place matched none. From the Cliopatria dataset.")


class Individual(Model):
    qid: QID | None = Field(None, description="Wikidata item id, e.g. 'Q937'. NULL when the item was named in a source but never resolved to Wikidata.")
    label_en: Wikidata[str] | None = None
    description_en: Wikidata[str] | None = None
    gender: Wikidata[QID] | None = None
    non_human: Derived[bool] | None = Field(None, description="True if the row is not actually a human (872 rows). Set from the Wikidata classes fictional character Q95074, mythical character Q4271324, deity Q178885, fictional human Q15632617, human biblical figure Q21070568, legendary creature Q24334685. Filter these out.")
    birth: Wikidata[str] | None = None
    birth_precision: Wikidata[int] | None = None
    birth_year: Derived[int] | None = Field(None, description="Birth year alone, parsed out of `birth`. Negative for BCE.")
    death: Wikidata[str] | None = None
    death_precision: Wikidata[int] | None = None
    death_year: Derived[int] | None = Field(None, description="Death year alone, parsed out of `death`. Negative for BCE.")
    floruit_declared: Wikidata[str] | None = None
    floruit_declared_precision: Wikidata[int] | None = None
    floruit_declared_year: Derived[int] | None = Field(None, description="Floruit year alone, parsed out of `floruit_declared`.")
    birthplace: Location | None = Field(None, description="City of birth, with its coordinates, its country and its modern country. Wikidata P19 'place of birth'.")
    deathplace: Location | None = Field(None, description="City of death, with its coordinates, its country and its modern country. Wikidata P20 'place of death'.")
    citizenships: Wikidata[str] | None = None
    citizenship_modern_countries: Derived[str] | None = Field(None, description="Modern countries those citizenships map onto, pipe-joined in the same order.")
    citizenship_modern_country_iso_a3_codes: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 codes of those modern countries, pipe-joined in the same order.")
    occupations: Wikidata[str] | None = None
    meta_occupation: Derived[Literal["scientist", "artist"]] | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Set when any occupation is reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
    cvdb_level1: External[Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]] | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing the occupation, not an AI classification. 'Missing' means unclassified.")
    cvdb_level2: External[str] | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
    cvdb_level3: External[str] | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
    cvdb_n_votes: Derived[int] | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")
    writing_languages: Wikidata[str] | None = None
    wikipedia_sites: Wikidata[str] | None = None
    wikipedia_titles: Wikidata[str] | None = None
    wikipedia_urls: Wikidata[str] | None = None
    number_of_wikipedia_articles: Derived[int] | None = Field(None, description="Number of Wikipedia articles across all languages. Counted over `wikipedia_sites`.")
    notability_western: Derived[int] | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    notability_non_western: Derived[int] | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    notability_general: Derived[float] | None = Field(None, description="Geometric mean of the two (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")
    identifier_properties: Wikidata[str] | None = None
    identifier_values: Wikidata[str] | None = None
    identifier_urls: Wikidata[str] | None = None
    number_of_identifiers: Derived[int] | None = Field(None, description="Number of external-database identifiers. Counted over `identifier_properties`.")
    floruit_year: Derived[int] | None = Field(None, description="The single year that represents the individual's activity: the midpoint of the window, or the only known year. This is what dating an individual relies on, since birth and death are often missing.")
    floruit_start: Derived[int] | None = Field(None, description="First year of the activity window. By convention an individual is active from age 30 to age 60, truncated by an early death.")
    floruit_end: Derived[int] | None = Field(None, description="Last year of the activity window. NULL when only one year is known.")
    floruit_label: Derived[str] | None = Field(None, description="The window as written, e.g. '1892-1964', or a single year when start equals end.")
    floruit_method: Derived[Literal["birth_only_property", "birth_only_description", "birth_only_cv", "birth_only_wikipedia", "birth_death_property", "birth_death_description", "birth_death_cv", "birth_death_wikipedia", "birth_death_estimated_birth", "birth_century", "birth_death_century", "death_century", "floruit_property", "floruit_property_century", "floruit_property_decade", "floruit_description", "floruit_wikipedia", "floruit_wikipedia_span", "works_span", "works_single", "under_30", "no_data"]] | None = Field(None, description="How the window was derived, as <anchor>_<evidence>: which dates were available and how they were read.")
    floruit_source: Derived[Literal["wikidata_property", "wikidata_description", "works", "life_expectancy", "cv_database", "wikipedia", "none"]] | None = Field(None, description="Where the dates came from: a Wikidata property, the Wikidata description, the works, the life-expectancy model, CVDB, or Wikipedia.")
    floruit_precision_class: Derived[Literal["year", "decade", "century"]] | None = Field(None, description="How precisely the window is known: to the year, the decade, or only the century. Use it to exclude vague individuals from an analysis.")
    floruit_estimated: Derived[bool] | None = Field(None, description="True if the window rests on the life-expectancy model rather than on attested dates.")
    floruit_birth_used: Derived[str] | None = Field(None, description="The birth date actually used as input, as an ISO string, whichever source it came from.")
    floruit_death_used: Derived[str] | None = Field(None, description="The death date actually used as input, as an ISO string, whichever source it came from.")
    floruit_floruit_used: Derived[str] | None = Field(None, description="The floruit date actually used as input, as an ISO string, whichever source it came from.")
    works_period_start: Derived[int] | None = Field(None, description="First year over which the individual produced works. The year of a work is its publication date, else its inception date.")
    works_period_end: Derived[int] | None = Field(None, description="Last year over which the individual produced works.")
    number_of_works: Derived[int] | None = Field(None, description="Number of works credited to the individual. Counted over `Work`.")
    description_dates_raw: Derived[str] | None = Field(None, description="Raw date substring matched in the Wikidata description before parsing. Kept so the extraction can be audited.")
    description_dates_span: Derived[str] | None = Field(None, description="Year span parsed out of the Wikidata description, e.g. '1937-2016'.")
    description_birth_year: Derived[int] | None = Field(None, description="Birth year parsed out of the Wikidata description, for individuals Wikidata leaves undated.")
    description_death_year: Derived[int] | None = Field(None, description="Death year parsed out of the Wikidata description.")
    description_floruit_year: Derived[int] | None = Field(None, description="Floruit year parsed out of the Wikidata description.")
    birth_from_cv: External[str] | None = Field(None, description="Birth date from the cross-verified database, used where Wikidata has none.")
    death_from_cv: External[str] | None = Field(None, description="Death date from the cross-verified database, used where Wikidata has none.")
    birth_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Birth year read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    death_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Death year read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    floruit_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Floruit read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    estimated_birthdate: Derived[str] | None = Field(None, description="Birth date estimated from the death date, iterating from birth = death - 70 against the birth-bin table to avoid the survivorship bias of a death-bin lookup.")
    estimated_deathdate: Derived[str] | None = Field(None, description="Death date estimated from the birth date. Never set when the estimate would fall in the last 5 years, or when the birth year would exceed 1950.")
    life_expectancy_lookup_source: Derived[Literal["birth_bin", "category+birth_bin:Leadership", "category+birth_bin:Culture", "category+birth_bin:Sports/Games", "category+birth_bin:Discovery/Science", "category+birth_bin:Other"]] | None = Field(None, description="Which lookup produced the estimate: the 50-year birth bin within a CVDB occupation category, or the birth bin alone as a fallback.")
    life_expectancy_median_used: Derived[float] | None = Field(None, description="Median life expectancy in years applied. The medians are estimated in-sample from Cultura individuals that have both dates at year precision — they are not a published life table.")
    in_pantheon_2: External[bool] | None = Field(None, description="True if the individual appears in the Pantheon 2.0 dataset.")
    in_cross_verified_db: External[bool] | None = Field(None, description="True if the individual appears in the cross-verified database.")
    citizenship_polities: tuple[Polity, ...] = Field((), description="Historical polities reached through the countries of citizenship rather than through a place, one entry per polity.")


class Work(Model):
    qid: QID | None = Field(None, description="Wikidata item id of the work, e.g. 'Q12418'.")
    label_en: Wikidata[str] | None = None
    description_en: Wikidata[str] | None = None
    creator: Wikidata[QID]
    role: Wikidata[Literal["author", "composer", "creator", "director", "editor", "illustrator", "performer", "producer", "screenwriter"]] | None = None
    instance_of: Wikidata[str] | None = None
    inception: Wikidata[str] | None = None
    inception_year: Derived[int] | None = Field(None, description="Inception year alone, parsed out of `inception`. Negative for BCE.")
    publication: Wikidata[str] | None = None
    publication_year: Derived[int] | None = Field(None, description="Publication year alone, parsed out of `publication`. Negative for BCE.")

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value | {"value": ROLE_FROM_PROPERTY.get(value["value"], value["value"])} if isinstance(value, dict) and isinstance(value.get("value"), str) else value


TABLES: dict[str, type[Model]] = {"individuals": Individual, "works": Work}
