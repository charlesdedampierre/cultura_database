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


class Wikidata(Model):
    property: str = Field(..., description="Wikidata property the value was read from, e.g. 'P569'. Non-property Wikidata sources keep their RDF term, e.g. 'rdfs:label'.")
    description: str | None = Field(None, description="What the property means, e.g. 'date on which the subject was born'. Read from properties.json and carried with the value, which is why no field in this schema describes itself: the description is data, not schema.")
    date_of_extraction: date = Field(..., description="Day the value was pulled from Wikidata. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")


class Dataset(Model):
    platform: Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"] = Field(..., description="Dataset the value was taken from.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset, as listed in sources.json.")
    date_of_extraction: date = Field(..., description="Day the value was taken from the dataset.")


class Derived(Model):
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Fields the value was computed from, as 'Model.field'.")
    rule: str = Field(..., description="The rule applied to those fields, in one sentence.")
    computed_on: date | None = Field(None, description="Day the computation was run.")


class AIAnswer(Model):
    model: str = Field(..., description="Exact model id that produced the value.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim.")
    answered_on: date | None = Field(None, description="Day the model was queried.")


class Source(Model, Generic[T]):
    value: T | None = Field(None, description="The value itself, as it stands in its origin. Multi-valued fields are pipe-joined in the origin's order.")
    origin: Wikidata | Dataset | Derived | AIAnswer = Field(..., description="Where the value came from, in the shape that origin requires: a Wikidata property, another dataset, a computation over other fields, or a language model. Wikidata is one origin among four — no field in this schema is tied to it.")
    label_en: str | None = Field(None, description="English label of `value` when the value is a qid, pipe-joined in the same order when it is several. It travels with the value, so no field needs an id / label twin.")


PROPERTIES: dict[str, dict[str, str]] = json.loads((HERE / "properties.json").read_text())

ROLE_FROM_PROPERTY: dict[str, str] = {pid: p["credit_role"] for pid, p in PROPERTIES.items() if "credit_role" in p}

SOURCES: dict[str, dict[str, str]] = json.loads((HERE / "sources.json").read_text())


def urban_settlement_answer() -> "Source[bool]":
    return Source[bool](origin=AIAnswer(model="google/gemini-3-flash-preview", prompt=(HERE / "prompts/urban_settlement.txt").read_text().strip(), answered_on=date(2026, 4, 23)))


def wikipedia_dates_answer() -> "Source[str]":
    return Source[str](origin=AIAnswer(model="google/gemini-2.5-flash-lite", prompt=(HERE / "prompts/wikipedia_dates.txt").read_text().strip(), answered_on=date(2026, 5, 6)))


class Date(Model):
    iso: Source[str] | None = Field(None, description="The date as an ISO string; a negative year means BCE.")
    precision: Source[int] | None = Field(None, description="Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium. Only a date read from Wikidata states it; elsewhere it is inferred from how the date was written.")
    year: Source[int] | None = Field(None, description="The year alone, parsed out of `iso` when there is one. Negative for BCE. A source that gives only a year fills this and leaves `iso` empty.")


def wikipedia_date() -> "Date":
    return Date(iso=wikipedia_dates_answer())


class Polity(Model):
    id: Source[int] | None = Field(None, description="Polity identifier, from the Cliopatria dataset.")
    name: Source[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    method: Source[Literal["merge_with_polygon", "merge_with_url"]] | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
    matched: Source[QID] | None = Field(None, description="The city or country that produced the match.")
    overlap_years: Source[int] | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")


class Location(Model):
    qid: Source[QID] | None = None
    lat: Source[float] | None = None
    lon: Source[float] | None = None
    entity_types: Source[str] | None = None
    is_urban_settlement: Source[bool] | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
    country: Source[QID] | None = None
    country_wikipedia_url: Source[str] | None = None
    modern_country: Source[str] | None = Field(None, description="Modern country the place maps onto, so historical data can be aggregated on today's borders.")
    modern_country_iso_a3: Source[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, e.g. 'FRA'.")
    modern_country_resolved_by: Source[str] | None = Field(None, description="How the mapping was resolved: 'reverse_geocode' (point-in-polygon on the coordinates), 'capital_city', 'qlever_relation', 'qlever_replaced_by', or 'unknown_legacy'.")
    inception: Date | None = Field(None, description="Date the place began to exist. Wikidata P571.")
    dissolution: Date | None = Field(None, description="Date the place ceased to exist. Wikidata P576.")
    polities: tuple[Polity, ...] = Field((), description="Historical polities whose territory covers this place, one entry per polity, empty when the place matched none. From the Cliopatria dataset.")


class Individual(Model):
    qid: QID | None = Field(None, description="Wikidata item id, e.g. 'Q937'. NULL when the item was named in a source but never resolved to Wikidata.")
    label_en: Source[str] | None = None
    description_en: Source[str] | None = None
    gender: Source[QID] | None = None
    non_human: Source[bool] | None = Field(None, description="True if the row is not actually a human (872 rows). Set from the Wikidata classes fictional character Q95074, mythical character Q4271324, deity Q178885, fictional human Q15632617, human biblical figure Q21070568, legendary creature Q24334685. Filter these out.")
    birthdate: Date | None = Field(None, description="Date of birth. Wikidata P569.")
    deathdate: Date | None = Field(None, description="Date of death. Wikidata P570.")
    floruit_declared: Date | None = Field(None, description="Floruit as stated by Wikidata, rather than the window this project resolves. Wikidata P1317.")
    birthplace: Location | None = Field(None, description="City of birth, with its coordinates, its country and its modern country. Wikidata P19 'place of birth'.")
    deathplace: Location | None = Field(None, description="City of death, with its coordinates, its country and its modern country. Wikidata P20 'place of death'.")
    citizenships: Source[str] | None = None
    citizenship_modern_countries: Source[str] | None = Field(None, description="Modern countries those citizenships map onto, pipe-joined in the same order.")
    citizenship_modern_country_iso_a3_codes: Source[str] | None = Field(None, description="ISO 3166-1 alpha-3 codes of those modern countries, pipe-joined in the same order.")
    occupations: Source[str] | None = None
    meta_occupation: Source[Literal["scientist", "artist"]] | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Set when any occupation is reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
    cvdb_level1: Source[Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]] | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing the occupation, not an AI classification. 'Missing' means unclassified.")
    cvdb_level2: Source[str] | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
    cvdb_level3: Source[str] | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
    cvdb_n_votes: Source[int] | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")
    writing_languages: Source[str] | None = None
    wikipedia_sites: Source[str] | None = None
    wikipedia_titles: Source[str] | None = None
    wikipedia_urls: Source[str] | None = None
    number_of_wikipedia_articles: Source[int] | None = Field(None, description="Number of Wikipedia articles across all languages. Counted over `wikipedia_sites`.")
    notability_western: Source[int] | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    notability_non_western: Source[int] | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    notability_general: Source[float] | None = Field(None, description="Geometric mean of the two (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")
    identifier_properties: Source[str] | None = None
    identifier_values: Source[str] | None = None
    identifier_urls: Source[str] | None = None
    number_of_identifiers: Source[int] | None = Field(None, description="Number of external-database identifiers. Counted over `identifier_properties`.")
    floruit_year: Source[int] | None = Field(None, description="The single year that represents the individual's activity: the midpoint of the window, or the only known year. This is what dating an individual relies on, since birth and death are often missing.")
    floruit_start: Source[int] | None = Field(None, description="First year of the activity window. By convention an individual is active from age 30 to age 60, truncated by an early death.")
    floruit_end: Source[int] | None = Field(None, description="Last year of the activity window. NULL when only one year is known.")
    floruit_label: Source[str] | None = Field(None, description="The window as written, e.g. '1892-1964', or a single year when start equals end.")
    floruit_method: Source[Literal["birth_only_property", "birth_only_description", "birth_only_cv", "birth_only_wikipedia", "birth_death_property", "birth_death_description", "birth_death_cv", "birth_death_wikipedia", "birth_death_estimated_birth", "birth_century", "birth_death_century", "death_century", "floruit_property", "floruit_property_century", "floruit_property_decade", "floruit_description", "floruit_wikipedia", "floruit_wikipedia_span", "works_span", "works_single", "under_30", "no_data"]] | None = Field(None, description="How the window was derived, as <anchor>_<evidence>: which dates were available and how they were read.")
    floruit_source: Source[Literal["wikidata_property", "wikidata_description", "works", "life_expectancy", "cv_database", "wikipedia", "none"]] | None = Field(None, description="Where the dates came from: a Wikidata property, the Wikidata description, the works, the life-expectancy model, CVDB, or Wikipedia.")
    floruit_precision_class: Source[Literal["year", "decade", "century"]] | None = Field(None, description="How precisely the window is known: to the year, the decade, or only the century. Use it to exclude vague individuals from an analysis.")
    floruit_estimated: Source[bool] | None = Field(None, description="True if the window rests on the life-expectancy model rather than on attested dates.")
    floruit_birthdate_used: Date | None = Field(None, description="The birth date actually used as input, whichever source it came from.")
    floruit_deathdate_used: Date | None = Field(None, description="The death date actually used as input, whichever source it came from.")
    floruit_floruit_used: Date | None = Field(None, description="The floruit date actually used as input, whichever source it came from.")
    works_period_start: Source[int] | None = Field(None, description="First year over which the individual produced works. The year of a work is its publication date, else its inception date.")
    works_period_end: Source[int] | None = Field(None, description="Last year over which the individual produced works.")
    number_of_works: Source[int] | None = Field(None, description="Number of works credited to the individual. Counted over `Work`.")
    description_dates_raw: Source[str] | None = Field(None, description="Raw date substring matched in the Wikidata description before parsing. Kept so the extraction can be audited.")
    description_dates_span: Source[str] | None = Field(None, description="Year span parsed out of the Wikidata description, e.g. '1937-2016'.")
    description_birthdate: Date | None = Field(None, description="Birth date recovered by regex from the Wikidata description, for individuals Wikidata leaves undated.")
    description_deathdate: Date | None = Field(None, description="Death date recovered by regex from the Wikidata description.")
    description_floruit: Date | None = Field(None, description="Floruit recovered by regex from the Wikidata description.")
    birthdate_from_cv: Date | None = Field(None, description="Birth date from the cross-verified database, used where Wikidata has none.")
    deathdate_from_cv: Date | None = Field(None, description="Death date from the cross-verified database, used where Wikidata has none.")
    birthdate_from_wikipedia: Date | None = Field(default_factory=wikipedia_date, description="Birth date read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    deathdate_from_wikipedia: Date | None = Field(default_factory=wikipedia_date, description="Death date read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    floruit_from_wikipedia: Date | None = Field(default_factory=wikipedia_date, description="Floruit read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    estimated_birthdate: Date | None = Field(None, description="Birth date estimated from the death date, iterating from birth = death - 70 against the birth-bin table to avoid the survivorship bias of a death-bin lookup.")
    estimated_deathdate: Date | None = Field(None, description="Death date estimated from the birth date. Never set when the estimate would fall in the last 5 years, or when the birth year would exceed 1950.")
    life_expectancy_lookup_source: Source[Literal["birth_bin", "category+birth_bin:Leadership", "category+birth_bin:Culture", "category+birth_bin:Sports/Games", "category+birth_bin:Discovery/Science", "category+birth_bin:Other"]] | None = Field(None, description="Which lookup produced the estimate: the 50-year birth bin within a CVDB occupation category, or the birth bin alone as a fallback.")
    life_expectancy_median_used: Source[float] | None = Field(None, description="Median life expectancy in years applied. The medians are estimated in-sample from Cultura individuals that have both dates at year precision — they are not a published life table.")
    in_pantheon_2: Source[bool] | None = Field(None, description="True if the individual appears in the Pantheon 2.0 dataset.")
    in_cross_verified_db: Source[bool] | None = Field(None, description="True if the individual appears in the cross-verified database.")
    citizenship_polities: tuple[Polity, ...] = Field((), description="Historical polities reached through the countries of citizenship rather than through a place, one entry per polity.")


class Work(Model):
    qid: QID | None = Field(None, description="Wikidata item id of the work, e.g. 'Q12418'.")
    label_en: Source[str] | None = None
    description_en: Source[str] | None = None
    creator: Source[QID]
    role: Source[Literal["author", "composer", "creator", "director", "editor", "illustrator", "performer", "producer", "screenwriter"]] | None = None
    instance_of: Source[str] | None = None
    inception: Date | None = Field(None, description="Date the work was created. Wikidata P571.")
    publication: Date | None = Field(None, description="Date the work was first published or released. Wikidata P577.")

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value | {"value": ROLE_FROM_PROPERTY.get(value["value"], value["value"])} if isinstance(value, dict) and isinstance(value.get("value"), str) else value


TABLES: dict[str, type[Model]] = {"individuals": Individual, "works": Work}
