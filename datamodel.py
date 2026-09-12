import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HERE = Path(__file__).parent


class Source(BaseModel):
    date_of_extraction: date = Field(..., description="Day the value was obtained from this source. Mandatory whatever the source: one that is edited continuously — Wikidata above all — cannot be reproduced without it.")


class Wikidata(Source):
    name: Literal["Wikidata"] = Field("Wikidata", description="Which of the four shapes this source is. It rides with the value, so a store that flattens the union — DuckDB collapses it to one struct, PostgreSQL to one table — can still tell them apart.")
    qid: str | None = Field(None, description="The Wikidata item in question, e.g. 'Q937': the item the value points at when the value is a qid, or the item the row is when this stands as a row's wikidata_entity.")
    label_en: str | None = Field(None, description="English label of that item, pipe-joined in the same order when the value is several qids. Wikidata rdfs:label. It saves every qid-valued field an id / label twin.")
    description_en: str | None = Field(None, description="English one-line description of that item. Wikidata schema:description.")
    property: str | None = Field(None, description="Wikidata property the value was read from, e.g. 'P569'. Non-property Wikidata sources keep their RDF term, e.g. 'rdfs:label'. Empty when this stands as a row's identity rather than as the source of a value.")
    property_definition: str | None = Field(None, description="What that property means, e.g. 'date on which the subject was born'. Read from properties.json and carried with the value, which is why no field in this schema describes itself: the definition is data, not schema.")

    @model_validator(mode="after")
    def name_the_item_or_the_property(self) -> "Wikidata":
        assert self.qid or self.property, "a Wikidata source must name the item it read, the property it read, or both"
        return self


class Dataset(Source):
    name: Literal["Dataset"] = Field("Dataset", description="Which of the four shapes this source is. It rides with the value, so a store that flattens the union — DuckDB collapses it to one struct, PostgreSQL to one table — can still tell them apart.")
    platform: Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"] = Field(..., description="Dataset the value was taken from.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset, as listed in sources.json.")


class Derived(Source):
    name: Literal["Derived"] = Field("Derived", description="Which of the four shapes this source is. It rides with the value, so a store that flattens the union — DuckDB collapses it to one struct, PostgreSQL to one table — can still tell them apart.")
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Fields the value was computed from, as 'Model.field'.")
    rule: str = Field(..., description="The rule applied to those fields, in one sentence.")


class AIAnswer(Source):
    name: Literal["AIAnswer"] = Field("AIAnswer", description="Which of the four shapes this source is. It rides with the value, so a store that flattens the union — DuckDB collapses it to one struct, PostgreSQL to one table — can still tell them apart.")
    model: str = Field(..., description="Exact model id that produced the value.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim.")


class Information(BaseModel):
    value: str | int | float | bool | None = Field(None, description="The value itself. Multi-valued fields are pipe-joined in the source's order.")
    source: Wikidata | Dataset | Derived | AIAnswer = Field(..., discriminator="name", description="Where the value came from, in the shape that source requires, and the day it was obtained. When it is Wikidata it also carries the property, what that property means, and the English label of the item. Wikidata is one source among four — no field in this schema is tied to it.")


PROPERTIES: dict[str, dict[str, str]] = json.loads((HERE / "properties.json").read_text())

ROLE_FROM_PROPERTY: dict[str, str] = {pid: p["credit_role"] for pid, p in PROPERTIES.items() if "credit_role" in p}

SOURCES: dict[str, dict[str, str]] = json.loads((HERE / "sources.json").read_text())


def urban_settlement_answer() -> "Information":
    return Information(source=AIAnswer(model="google/gemini-3-flash-preview", prompt=(HERE / "prompts/urban_settlement.txt").read_text().strip(), date_of_extraction=date(2026, 4, 23)))


def wikipedia_dates_answer() -> "Information":
    return Information(source=AIAnswer(model="google/gemini-2.5-flash-lite", prompt=(HERE / "prompts/wikipedia_dates.txt").read_text().strip(), date_of_extraction=date(2026, 5, 6)))


class Date(BaseModel):
    iso: Information | None = Field(None, description="The full date, written in ISO 8601: year-month-day, e.g. '1879-03-14'. A leading minus is a date before the common era, e.g. '-0356-07-20' for Alexander the Great. Empty when the source gives only a year — then `year` alone is filled.")
    precision: Information | None = Field(None, description="Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium. A date read from Wikidata states it; elsewhere it is inferred from how the date was written, or from the coarsest input a computed date rests on. This is how precisely a date is known — use it to exclude vague individuals from an analysis.")
    year: Information | None = Field(None, description="The year alone, parsed out of `iso` when there is one. Negative for BCE. A source that gives only a year fills this and leaves `iso` empty.")


class DateRange(BaseModel):
    start: Date | None = Field(None, description="First date of the range.")
    end: Date | None = Field(None, description="Last date of the range. Empty when only one date is known.")


class Floruit(DateRange):
    mid: Date | None = Field(None, description="The single date that represents the range: its midpoint, or the only date known. This is what dating an individual relies on, since birth and death are often missing.")


class WikipediaLink(BaseModel):
    language: Information | None = Field(None, description="Language edition the article is in, as a Wikipedia site code, e.g. 'enwiki' for English. This is what the Western / non-Western notability split counts.")
    title: Information | None = Field(None, description="Title of the article in that edition.")
    url: Information | None = Field(None, description="URL of the article.")


class Polity(DateRange):
    id: Information | None = Field(None, description="Polity identifier, from the Cliopatria dataset. A polity holds different ground at different times, so it appears once per period of its borders and several entries can share an id.")
    name: Information | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    geometry: Information | None = Field(None, description="The territory held over this period, as a GeoJSON polygon. This is what decides whether a place falls inside the polity.")
    area: Information | None = Field(None, description="Area of that territory in square kilometres.")
    overlap_years: Information | None = Field(None, description="Years of the individual's activity window covered by this period. Sum them over the entries that share an id to rank the polities of a multi-polity individual. The Derived source says how the place was matched — a polygon or a shared Wikipedia URL — and the place itself is the Location this entry hangs from.")


class Location(BaseModel):
    id: Information | None = Field(None, description="The place, as the qid of its Wikidata item. Its English label and description are in the source.")
    lat: Information | None = None
    lon: Information | None = None
    entity_types: Information | None = None
    is_urban_settlement: Information | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
    country: Information | None = None
    wikipedia_link: WikipediaLink | None = Field(None, description="The place's own Wikipedia article. It is what the polity URL match reads.")
    country_wikipedia_link: WikipediaLink | None = Field(None, description="The Wikipedia article of the country the place belongs to.")
    modern_country: Information | None = Field(None, description="Modern country the place maps onto, so historical data can be aggregated on today's borders. How the mapping was resolved — point-in-polygon on the coordinates, the capital city, a QLever relation, a replaced-by link, or a legacy value of unknown provenance — is the `rule` of its Derived source.")
    modern_country_iso_a3: Information | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, e.g. 'FRA'.")
    inception: Date | None = Field(None, description="Date the place began to exist. Wikidata P571.")
    dissolution: Date | None = Field(None, description="Date the place ceased to exist. Wikidata P576.")
    polities: tuple[Polity, ...] = Field((), description="Historical polities whose territory covers this place, one entry per polity and per period of its borders, empty when the place matched none. From the Cliopatria dataset.")


class Occupation(BaseModel):
    id: Information | None = Field(None, description="The occupation, as the qid of its Wikidata item, e.g. Q169470 'physicist'. Wikidata P106 'occupation'.")
    meta_occupation: Information | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Set when the occupation is reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
    cvdb_level1: Information | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing the occupation, not an AI classification. 'Missing' means unclassified.")
    cvdb_level2: Information | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
    cvdb_level3: Information | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
    cvdb_n_votes: Information | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")


class Identifier(BaseModel):
    value: Information | None = Field(None, description="The identifier as issued by an external database. Which database it is, is the Wikidata property its source names — P214 for VIAF, P227 for GND — so it is not repeated here.")
    url: Information | None = Field(None, description="URL of the individual's record in that database.")


class Notability(BaseModel):
    total: Information | None = Field(None, description="Number of Wikipedia articles across all languages, western plus non-western. Counted over `wikipedia_links`.")
    western: Information | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    non_western: Information | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    general: Information | None = Field(None, description="Geometric mean of the two (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")


class Individual(BaseModel):
    id: Information | None = Field(None, description="The individual, as the qid of their Wikidata item. Their English label and description are in the source. Empty when the row was named by a source that never resolved them to Wikidata.")

    birthdates: tuple[Date, ...] = Field((), description="Every birth date known for the individual, one per source: Wikidata P569, the Wikidata description read by regex, the cross-verified database, or the Wikipedia article read by a language model. A date this project computes rather than reads is a candidate like any other, and its `rule` says how. Each Date names its own source, so which candidate is which is read off it rather than off a field name. Empty when no source gives one.")
    deathdates: tuple[Date, ...] = Field((), description="Every death date known for the individual, one per source, as for `birthdates`.")
    floruits: tuple[Floruit, ...] = Field((), description="Every activity window known for the individual, one per source: stated outright by Wikidata P1317, recovered by regex from the Wikidata description, read out of the Wikipedia article by a language model, or resolved by this project from the birth and death dates it holds — by convention an individual is active from age 30 to age 60, truncated by an early death. Each Date inside names its own source, so which window is which is read off it rather than off a field name.")
    works_period: DateRange | None = Field(None, description="The range over which the individual produced works. The date of a work is its publication date, else its inception date.")

    birthplace: Location | None = Field(None, description="City of birth, with its coordinates, its country and its modern country. Wikidata P19 'place of birth'.")
    deathplace: Location | None = Field(None, description="City of death, with its coordinates, its country and its modern country. Wikidata P20 'place of death'.")
    citizenships: tuple[Location, ...] = Field((), description="Countries of citizenship, in Wikidata order, historical entities included — each a place, with its modern country and the polities it falls in. Wikidata P27 'country of citizenship'.")

    occupations: tuple[Occupation, ...] = Field((), description="Occupations, in Wikidata order, each with its meta-occupation and its CVDB ontology. Wikidata P106 'occupation'.")
    wikipedia_links: tuple[WikipediaLink, ...] = Field((), description="Wikipedia articles about the individual, one per language edition. These are what the notability scores count.")
    identifiers: tuple[Identifier, ...] = Field((), description="The individual's records in external databases, one entry per database.")

    notability: Notability | None = Field(None, description="Wikipedia coverage of the individual, counted over `wikipedia_links`. Fame in this project is how many language editions carry an article, and how far that reach crosses the Western / non-Western divide.")
    gender: Information | None = Field(None, description="Gender as its source gives it: a Wikidata item id from P21, whose English label is in the source, or a plain word from a dataset that has no item for it. Free vocabulary — 48 distinct values in the data, a few of them unresolved.")
    non_human: Information | None = Field(None, description="True if the row is not actually a human (872 rows). Set from the Wikidata classes fictional character Q95074, mythical character Q4271324, deity Q178885, fictional human Q15632617, human biblical figure Q21070568, legendary creature Q24334685. Filter these out.")
    writing_languages: Information | None = None

    in_pantheon_2: Information | None = Field(None, description="True if the individual appears in the Pantheon 2.0 dataset.")
    in_cross_verified_db: Information | None = Field(None, description="True if the individual appears in the cross-verified database.")

    number_of_works: Information | None = Field(None, description="Number of works credited to the individual. Counted over `Work`.")
    number_of_identifiers: Information | None = Field(None, description="Number of external-database identifiers. Counted over `identifiers`.")


class Work(BaseModel):
    wikidata_entity: Wikidata | None = Field(None, description="The Wikidata item this row is: its qid, its English label and description, and the day it was read. NULL when the row was named in a source but never resolved to Wikidata.")
    creator: Information
    role: Information | None = None
    instance_of: Information | None = None
    inception: Date | None = Field(None, description="Date the work was created. Wikidata P571.")
    publication: Date | None = Field(None, description="Date the work was first published or released. Wikidata P577.")


TABLES: dict[str, type[BaseModel]] = {"individuals": Individual, "works": Work}
