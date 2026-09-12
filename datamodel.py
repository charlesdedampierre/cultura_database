import json
from datetime import date
from pathlib import Path
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

HERE = Path(__file__).parent

T = TypeVar("T")

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Source(Model):
    date_of_extraction: date = Field(..., description="Day the value was obtained from this source. Mandatory whatever the source: one that is edited continuously — Wikidata above all — cannot be reproduced without it.")


class Wikidata(Source):
    qid: QID | None = Field(None, description="The Wikidata item in question: the item the value points at when the value is a qid, or the item the row is when this stands as a row's wikidata_entity.")
    label_en: str | None = Field(None, description="English label of that item, pipe-joined in the same order when the value is several qids. Wikidata rdfs:label. It saves every qid-valued field an id / label twin.")
    description_en: str | None = Field(None, description="English one-line description of that item. Wikidata schema:description.")
    property: str | None = Field(None, description="Wikidata property the value was read from, e.g. 'P569'. Non-property Wikidata sources keep their RDF term, e.g. 'rdfs:label'. Empty when this stands as a row's identity rather than as the source of a value.")
    property_definition: str | None = Field(None, description="What that property means, e.g. 'date on which the subject was born'. Read from properties.json and carried with the value, which is why no field in this schema describes itself: the definition is data, not schema.")

    @model_validator(mode="after")
    def name_the_item_or_the_property(self) -> "Wikidata":
        assert self.qid or self.property, "a Wikidata source must name the item it read, the property it read, or both"
        return self


class Dataset(Source):
    platform: Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"] = Field(..., description="Dataset the value was taken from.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset, as listed in sources.json.")


class Derived(Source):
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Fields the value was computed from, as 'Model.field'.")
    rule: str = Field(..., description="The rule applied to those fields, in one sentence.")


class AIAnswer(Source):
    model: str = Field(..., description="Exact model id that produced the value.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim.")


class Information(Model, Generic[T]):
    value: T | None = Field(None, description="The value itself. Multi-valued fields are pipe-joined in the source's order.")
    source: Wikidata | Dataset | Derived | AIAnswer = Field(..., description="Where the value came from, in the shape that source requires, and the day it was obtained. When it is Wikidata it also carries the property, what that property means, and the English label of the item. Wikidata is one source among four — no field in this schema is tied to it.")


PROPERTIES: dict[str, dict[str, str]] = json.loads((HERE / "properties.json").read_text())

ROLE_FROM_PROPERTY: dict[str, str] = {pid: p["credit_role"] for pid, p in PROPERTIES.items() if "credit_role" in p}

SOURCES: dict[str, dict[str, str]] = json.loads((HERE / "sources.json").read_text())


def urban_settlement_answer() -> "Information[bool]":
    return Information[bool](source=AIAnswer(model="google/gemini-3-flash-preview", prompt=(HERE / "prompts/urban_settlement.txt").read_text().strip(), date_of_extraction=date(2026, 4, 23)))


def wikipedia_dates_answer() -> "Information[str]":
    return Information[str](source=AIAnswer(model="google/gemini-2.5-flash-lite", prompt=(HERE / "prompts/wikipedia_dates.txt").read_text().strip(), date_of_extraction=date(2026, 5, 6)))


class Date(Model):
    iso: Information[str] | None = Field(None, description="The full date, written in ISO 8601: year-month-day, e.g. '1879-03-14'. A leading minus is a date before the common era, e.g. '-0356-07-20' for Alexander the Great. Empty when the source gives only a year — then `year` alone is filled.")
    precision: Information[int] | None = Field(None, description="Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium. A date read from Wikidata states it; elsewhere it is inferred from how the date was written, or from the coarsest input a computed date rests on. This is how precisely a date is known — use it to exclude vague individuals from an analysis.")
    year: Information[int] | None = Field(None, description="The year alone, parsed out of `iso` when there is one. Negative for BCE. A source that gives only a year fills this and leaves `iso` empty.")


class Polity(Model):
    id: Information[int] | None = Field(None, description="Polity identifier, from the Cliopatria dataset.")
    name: Information[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    method: Information[Literal["merge_with_polygon", "merge_with_url"]] | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
    matched: Information[QID] | None = Field(None, description="The city or country that produced the match.")
    overlap_years: Information[int] | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")


class Location(Model):
    qid: Information[QID] | None = None
    lat: Information[float] | None = None
    lon: Information[float] | None = None
    entity_types: Information[str] | None = None
    is_urban_settlement: Information[bool] | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
    country: Information[QID] | None = None
    wikipedia_url: Information[str] | None = None
    country_wikipedia_url: Information[str] | None = None
    modern_country: Information[str] | None = Field(None, description="Modern country the place maps onto, so historical data can be aggregated on today's borders.")
    modern_country_iso_a3: Information[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, e.g. 'FRA'.")
    modern_country_resolved_by: Information[str] | None = Field(None, description="How the mapping was resolved: 'reverse_geocode' (point-in-polygon on the coordinates), 'capital_city', 'qlever_relation', 'qlever_replaced_by', or 'unknown_legacy'.")
    inception: Date | None = Field(None, description="Date the place began to exist. Wikidata P571.")
    dissolution: Date | None = Field(None, description="Date the place ceased to exist. Wikidata P576.")
    polities: tuple[Polity, ...] = Field((), description="Historical polities whose territory covers this place, one entry per polity, empty when the place matched none. From the Cliopatria dataset.")


class Occupation(Model):
    qid: Information[QID] | None = Field(None, description="The occupation item, e.g. Q169470 'physicist'. Wikidata P106 'occupation'.")
    meta_occupation: Information[Literal["scientist", "artist"]] | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Set when the occupation is reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
    cvdb_level1: Information[Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]] | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing the occupation, not an AI classification. 'Missing' means unclassified.")
    cvdb_level2: Information[str] | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
    cvdb_level3: Information[str] | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
    cvdb_n_votes: Information[int] | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")


class Identifier(Model):
    value: Information[str] | None = Field(None, description="The identifier as issued by an external database. Which database it is, is the Wikidata property its source names — P214 for VIAF, P227 for GND — so it is not repeated here.")
    url: Information[str] | None = Field(None, description="URL of the individual's record in that database.")


class WikipediaLink(Model):
    language: Information[str] | None = Field(None, description="Language edition the article is in, as a Wikipedia site code, e.g. 'enwiki' for English. This is what the Western / non-Western notability split counts.")
    title: Information[str] | None = Field(None, description="Title of the article in that edition.")
    url: Information[str] | None = Field(None, description="URL of the article.")


class Notability(Model):
    total: Information[int] | None = Field(None, description="Number of Wikipedia articles across all languages, western plus non-western. Counted over `wikipedia_links`.")
    western: Information[int] | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    non_western: Information[int] | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    general: Information[float] | None = Field(None, description="Geometric mean of the two (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")


class Individual(Model):
    wikidata_entity: Wikidata | None = Field(None, description="The Wikidata item this row is: its qid, its English label and description, and the day it was read. NULL when the row was named in a source but never resolved to Wikidata.")
    gender: Information[QID] | None = None
    non_human: Information[bool] | None = Field(None, description="True if the row is not actually a human (872 rows). Set from the Wikidata classes fictional character Q95074, mythical character Q4271324, deity Q178885, fictional human Q15632617, human biblical figure Q21070568, legendary creature Q24334685. Filter these out.")
    birthdates: tuple[Date, ...] = Field((), description="Every birth date known for the individual, one per source: Wikidata P569, the Wikidata description read by regex, the cross-verified database, the Wikipedia article read by a language model, or estimated from the death date against a life-expectancy table. Each Date names its own source, so which candidate is which is read off it rather than off a field name. Empty when no source gives one.")
    deathdates: tuple[Date, ...] = Field((), description="Every death date known for the individual, one per source, as for `birthdates`.")
    declared_floruits: tuple[Date, ...] = Field((), description="Every floruit a source states outright — Wikidata P1317, the Wikidata description, the Wikipedia article read by a language model — as against `floruit_year`, the window this project resolves from all the dates it has.")
    birthplace: Location | None = Field(None, description="City of birth, with its coordinates, its country and its modern country. Wikidata P19 'place of birth'.")
    deathplace: Location | None = Field(None, description="City of death, with its coordinates, its country and its modern country. Wikidata P20 'place of death'.")
    citizenships: tuple[Location, ...] = Field((), description="Countries of citizenship, in Wikidata order, historical entities included — each a place, with its modern country and the polities it falls in. Wikidata P27 'country of citizenship'.")
    occupations: tuple[Occupation, ...] = Field((), description="Occupations, in Wikidata order, each with its meta-occupation and its CVDB ontology. Wikidata P106 'occupation'.")
    writing_languages: Information[str] | None = None
    wikipedia_links: tuple[WikipediaLink, ...] = Field((), description="Wikipedia articles about the individual, one per language edition. These are what the notability scores count.")
    notability: Notability | None = Field(None, description="Wikipedia coverage of the individual, counted over `wikipedia_links`. Fame in this project is how many language editions carry an article, and how far that reach crosses the Western / non-Western divide.")
    identifiers: tuple[Identifier, ...] = Field((), description="The individual's records in external databases, one entry per database.")
    number_of_identifiers: Information[int] | None = Field(None, description="Number of external-database identifiers. Counted over `identifiers`.")
    floruit_year: Date | None = Field(None, description="The single date that represents the individual's activity: the midpoint of the window, or the only known year. This is what dating an individual relies on, since birth and death are often missing. Which dates fed it, and from which source, is its own `derived_from`.")
    floruit_start: Date | None = Field(None, description="First date of the activity window. By convention an individual is active from age 30 to age 60, truncated by an early death.")
    floruit_end: Date | None = Field(None, description="Last date of the activity window. NULL when only one year is known.")
    works_period_start: Date | None = Field(None, description="First date at which the individual produced works. The date of a work is its publication date, else its inception date.")
    works_period_end: Date | None = Field(None, description="Last date at which the individual produced works.")
    number_of_works: Information[int] | None = Field(None, description="Number of works credited to the individual. Counted over `Work`.")
    life_expectancy_lookup_source: Information[Literal["birth_bin", "category+birth_bin:Leadership", "category+birth_bin:Culture", "category+birth_bin:Sports/Games", "category+birth_bin:Discovery/Science", "category+birth_bin:Other"]] | None = Field(None, description="Which lookup produced the estimated date in `birthdates` or `deathdates`: the 50-year birth bin within a CVDB occupation category, or the birth bin alone as a fallback.")
    life_expectancy_median_used: Information[float] | None = Field(None, description="Median life expectancy in years applied. The medians are estimated in-sample from Cultura individuals that have both dates at year precision — they are not a published life table.")
    in_pantheon_2: Information[bool] | None = Field(None, description="True if the individual appears in the Pantheon 2.0 dataset.")
    in_cross_verified_db: Information[bool] | None = Field(None, description="True if the individual appears in the cross-verified database.")


class Work(Model):
    wikidata_entity: Wikidata | None = Field(None, description="The Wikidata item this row is: its qid, its English label and description, and the day it was read. NULL when the row was named in a source but never resolved to Wikidata.")
    creator: Information[QID]
    role: Information[Literal["author", "composer", "creator", "director", "editor", "illustrator", "performer", "producer", "screenwriter"]] | None = None
    instance_of: Information[str] | None = None
    inception: Date | None = Field(None, description="Date the work was created. Wikidata P571.")
    publication: Date | None = Field(None, description="Date the work was first published or released. Wikidata P577.")

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value | {"value": ROLE_FROM_PROPERTY.get(value["value"], value["value"])} if isinstance(value, dict) and isinstance(value.get("value"), str) else value


TABLES: dict[str, type[Model]] = {"individuals": Individual, "works": Work}
