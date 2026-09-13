from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Origin(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was built from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.birth', 'PolityCliopatria.geometry'. Every source the project reads is in that file in full, so this is the link back to the data exactly as it arrived, and from there to a Wikidata property and its definition.")
    inputs: tuple[str, ...] = Field((), description="For a value computed from another computed one, the fields of this table it was built on — the floruit from its start and end. Values read from a source name those in `raw` instead.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class Date(BaseModel):
    iso: str | None = Field(None, description="The date as an ISO string, '1879-03-14'. Wikidata's own stamp, '1879-03-14T00:00:00Z', is removed: it is not a time of day. A leading minus is a date before the common era, '-0356-07-20'.")
    year: int | None = Field(None, description="The year alone, read off `iso`. Negative before the common era. It is what nearly every analysis uses, and reading it off the string each time is a needless step.")
    precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely the source states the date, as a word rather than Wikidata's numeric code. A date known only to the century still reads as a full ISO string, so this is the only way to know it is not one.")


class Polity(BaseModel):
    id: int | None = Field(None, description="Cliopatria's identifier for the polity. Several rows share it: a polity held different ground at different times, and this table has one row per change of borders — 13 755 rows for 1 633 polities, 8.4 spans each. Nothing in Cliopatria numbers a span, so a row is identified by this and `start`.")
    name: str | None = Field(None, description="The polity's name as Cliopatria spells it — 'Ottoman Empire', 'Magadha - Shaishunaga dynasty'. Its own spelling, not Wikidata's. Repeated on every row that shares an id.")
    type: Literal["POLITY", "RELATION"] | None = Field(None, description="'POLITY' for a polity in its own right, 'RELATION' for a dependency between two of them — 13 370 against 385. A relation is not somewhere a person can be born, so filter on it before counting.")
    start: int | None = Field(None, description="First year of this span. Negative before the common era.")
    end: int | None = Field(None, description="Last year of this span.")
    area: float | None = Field(None, description="Area of the ground held over this span, in square kilometres. Read the rows of one id in order and you watch an empire move: the Greek City-States go 64 106, then 89 420, then 129 112 km².")
    geometry: str | None = Field(None, description="The ground itself, as GeoJSON — a Polygon on 6 522 rows, a MultiPolygon on 7 233, never a Point: a polity holds an area, the smallest in Cliopatria being 87 km². This is what decides whether a place falls inside the polity, and it is the heaviest column in the published set, which is why the polities are a table of their own rather than embedded in each individual.")
    modern_countries: tuple[str, ...] = Field((), description="ISO 3166-1 alpha-3 codes of the states holding that ground today, 'DEU', 'POL' — how a historical polity is aggregated onto present-day borders. Cliopatria resolves these per polity rather than per span, so the same codes repeat on every row of one id until they are recomputed from each polygon.")
    wikidata_id: str | None = Field(None, description="The qid Cliopatria resolved for the polity, where it resolved one — the join out to Wikidata and to the other tables here.")
    wikipedia_url: str | None = Field(None, description="Its English Wikipedia article. Cliopatria publishes the title and this is the URL built from it; matching a place to a polity by URL is the other half of the method, the first being the polygon.")


class WikidataProperty(BaseModel):
    pid: str = Field(..., description="The property's identifier, 'P569'. Non-property sources keep their RDF term, 'rdfs:label'. Every column of Individual is named after one of these, and Origin.raw reaches them.")
    label: str | None = Field(None, description="The property's English label, 'date of birth'. Lowercased with non-alphanumeric runs turned into underscores, it is the column name in Individual.")
    definition: str | None = Field(None, description="What the property means, in Wikidata's own words — 'date on which the subject was born'. Stored once here rather than repeated on every value, which is why no column of this schema describes itself.")


class Place(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, as Individual.place_of_birth and .place_of_death name it.")
    label: str | None = Field(None, description="English name, 'Ulm'.")
    latitude: float | None = Field(None, description="Decimal degrees, the latitude half of P625.")
    longitude: float | None = Field(None, description="Decimal degrees.")
    country: str | None = Field(None, description="P17, the country Wikidata declares the place to be in, as a qid. For a historical place this is often a state that no longer exists — Königsberg is declared in the Kingdom of Prussia. Join it to CountryOfCitizenship.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the place as qids — 'city', 'hospital', 'quarter'. P19 names all of these as places of birth.")
    inception: int | None = Field(None, description="Year the place began to exist, P571.")
    dissolution: int | None = Field(None, description="Year it ceased to exist, P576. A birthplace with one has since been razed or absorbed.")
    modern_country: str | None = Field(None, description="The state holding this ground today, by name, from a reverse geocoder on the coordinates — not what Wikidata declares. Königsberg is declared in Prussia and geocodes to Russia. Computed, unlike everything above it.")
    modern_country_iso: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that state. Empty where the geocoder found none, which happens at sea and in Antarctica.")
    is_settlement: bool | None = Field(None, description="True when the place is a populated place rather than a hospital, a building or an administrative region. A language model read the P31 classes, not the places, so a place is a settlement when any of its classes is. Computed.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column. An entry with a rule was computed — the last three columns — and one without was read.")


class CountryOfCitizenship(BaseModel):
    qid: str = Field(..., description="The state's Wikidata item, as Individual.country_of_citizenship names it. Historical states are here as readily as present ones.")
    label: str | None = Field(None, description="English name, 'Kingdom of Prussia'.")
    description: str | None = Field(None, description="English one-line description.")
    instance_of: tuple[str, ...] = Field((), description="P31, as qids — 'sovereign state', 'former country'. This is what tells a state that still exists from one that does not, without asking a geocoder.")
    latitude: float | None = None
    longitude: float | None = None
    continent: str | None = Field(None, description="P30, as a qid.")
    iso_3166_1_alpha_3_code: str | None = Field(None, description="P298. Only a state that exists today has one, so an empty code is itself the signal that this is a historical entity.")
    wikipedia_url: str | None = Field(None, description="Its English Wikipedia article, which is how a state is matched to a Cliopatria polity when the polygons do not settle it.")
    inception: int | None = Field(None, description="Year the state came into being, P571.")
    dissolution: int | None = Field(None, description="Year it ceased to exist, P576.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Occupation(BaseModel):
    qid: str = Field(..., description="The occupation's Wikidata item, as Individual.occupation names it.")
    label: str | None = Field(None, description="English name, 'astronomer'.")
    description: str | None = Field(None, description="English one-line description.")
    subclass_of: tuple[str, ...] = Field((), description="P279, as qids. This is the tree IndividualEnriched.is_scientist and .is_artist walk, so it is here rather than left implicit in the flags.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Identifier(BaseModel):
    pid: str = Field(..., description="The Wikidata property that carries the identifier, 'P214' for VIAF. This is what an external database is: Wikidata has 10 329 such properties and nothing else names them.")
    label: str | None = Field(None, description="The database's name, 'VIAF ID', 'ISBN-13'.")
    formatter_url: str | None = Field(None, description="P1630, the template that turns an identifier into a link — 'https://viaf.org/viaf/$1', with $1 standing for the value. It is why IndividualIdentifier need not store a URL per row.")
    issuer: str | None = Field(None, description="P1629, the qid of the organisation that issues the identifiers — a national library, a museum.")
    issuer_country: str | None = Field(None, description="P17 of that issuer, as a qid. Use it to weigh how national a database's coverage is: a French library indexes French lives more densely, and a count of identifiers is not a count of importance.")
    official_website: str | None = Field(None, description="P856 of the database.")
    number_of_records: int | None = Field(None, description="P4876, how many records it holds. Together with the count of individuals carrying one of its identifiers, this says what share of the database Cultura reaches.")
    inception: int | None = Field(None, description="Year the database was founded, P571.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class IndividualIdentifier(BaseModel):
    qid: str = Field(..., description="The individual, joining to Individual.qid.")
    pid: str = Field(..., description="Which database, joining to Identifier.pid. The pair is the key: an individual has at most one identifier per database.")
    value: str | None = Field(None, description="The identifier as that database issued it, '75121530'. A string, never a number: many carry leading zeros or letters.")
    url: str | None = Field(None, description="The record's URL where Wikidata gives one. It is otherwise Identifier.formatter_url with the value substituted, so this column is mostly empty by design.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Sitelink(BaseModel):
    qid: str = Field(..., description="The individual, joining to Individual.qid.")
    language: str | None = Field(None, description="The edition the article is in, as its host — 'fr.wikipedia.org'. An individual has up to 228, and it is the count of these, split Western against non-Western, that IndividualEnriched.notability is built on.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped.")
    url: str | None = Field(None, description="The article's URL, percent-encoded as Wikidata gives it.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Work(BaseModel):
    qid: str = Field(..., description="The work's Wikidata item. A few keys in the source are lexeme URIs rather than qids.")
    creator: str | None = Field(None, description="The individual credited, joining to Individual.qid. A work with several creators has one row per creator.")
    credit_property: str | None = Field(None, description="The property that credits them — 'P50' author, 'P170' creator, 'P175' performer. It is what stops an actor and a director counting as having written the same film. Join it to WikidataProperty for its name.")
    label: str | None = Field(None, description="The work's English title, 'Mona Lisa'.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the work as qids — 'painting', 'film', 'novel'.")
    inception: Date | None = Field(None, description="When the work was made, P571.")
    publication_date: Date | None = Field(None, description="When it was first published or released, P577. The year of a work is this where there is one and the inception otherwise, which is how IndividualEnriched.works_first_year is built.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Individual(BaseModel):
    qid: str = Field(..., description="The individual's Wikidata item. Raw: IndividualWikidata.qid.")
    label: str | None = Field(None, description="English label, unquoted — the raw file gives it as the RDF literal '\"Claus Hammel\"@en'. Raw: IndividualWikidata.label.")
    description: str | None = Field(None, description="English one-line description, unquoted. Raw: IndividualWikidata.description.")
    birth_date: Date | None = Field(None, description="Date of birth as one value: the ISO string, the year read off it, and the precision. Built from IndividualWikidata.date_of_birth and .date_of_birth_precision, which arrive as two separate files and are one fact.")
    death_date: Date | None = Field(None, description="Date of death, on the same terms.")
    floruit_date: Date | None = Field(None, description="The P1317 date, on the same terms. Still a date Wikidata states, not IndividualEnriched.peak_productivity_*, which this project computes.")
    place_of_birth: str | None = Field(None, description="P19, as the place's qid. Often a city, sometimes a country, sometimes a hospital — P19 makes no promise. Join it to PlaceWikidata for the name and the coordinates. Raw: IndividualWikidata.place_of_birth.")
    place_of_death: str | None = Field(None, description="P20, as a qid. Raw: IndividualWikidata.place_of_death.")
    sex_or_gender: str | None = Field(None, description="P21, as a qid. A free vocabulary in practice: 48 distinct values in the data. Raw: IndividualWikidata.sex_or_gender.")
    occupation: tuple[str, ...] = Field((), description="P106, qids in Wikidata's order. Join them to OccupationWikidata for the labels. Raw: IndividualWikidata.occupation.")
    country_of_citizenship: tuple[str, ...] = Field((), description="P27, qids in Wikidata's order, historical states included. Join them to CountryWikidata. Raw: IndividualWikidata.country_of_citizenship.")
    writing_language: tuple[str, ...] = Field((), description="P6886, qids. Raw: IndividualWikidata.writing_language.")
    external_id: dict[str, str] = Field({}, description="A map of Wikidata property to identifier: {'P214': '75121530'} is VIAF. Which database it is, is the property and nothing else. Raw: IndividualWikidata.external_id.")
    sitelink: tuple[str, ...] = Field((), description="The URL of every Wikipedia article about the individual, one per language edition, up to 228. Raw: IndividualWikidata.sitelink.")
    work: tuple[str, ...] = Field((), description="The qid of every work credited to the individual. Raw: IndividualWikidata.work, which also carries the credit property this drops.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by field name. Every entry names a raw field and carries no rule: the values here are the raw ones unquoted and stripped of their stamps, nothing more. Any change of shape — a date joined to its precision, a qid resolved to a label — is on IndividualEnriched.")


class IndividualEnriched(Individual):

    peak_productivity_start: int | None = Field(None, description="First year of the range this project takes the individual to have been at work. By convention that is from age 30 to age 60, truncated by an early death — so it is a claim about a life stage, not a record of anything observed.")
    peak_productivity_midpoint: int | None = Field(None, description="The single year that stands for the range, its middle. This is what to date an individual by in a distribution over time: birth and death are missing for most people before 1500, and a birth year dates someone decades before they did anything. It is the floruit as defined in the paper, and deliberately not called floruit — Wikidata has a property of that name, P1317, which is a date a source states rather than a range this project computes, and it is on IndividualWikidata.")
    peak_productivity_end: int | None = Field(None, description="Last year of the range.")
    peak_productivity_is_estimated: bool | None = Field(None, description="True when the range rests on an estimated birth or death year rather than an attested one. The range is still usable; it is simply softer, and this says so rather than leaving it to be discovered.")

    polity: Polity | None = Field(None, description="The historical polity the individual most belonged to, carrying its id and its name only — the ground it held is in the Polity table, which a polygon repeated on thirteen million rows would otherwise dwarf. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods — theirs are in datamodel_raw.py.")
    polity_years: int | None = Field(None, description="Years of the peak-productivity range spent inside that polity. A small number means the match is incidental — someone who died abroad.")
    polity_count: int | None = Field(None, description="How many polities the individual overlaps at all. More than one is normal for a long life in a contested region.")

    is_scientist: bool | None = Field(None, description="True when any occupation descends from 'scientist' (Q901) through Wikidata's subclass tree.")
    is_artist: bool | None = Field(None, description="True when any occupation descends from 'artist' (Q483501).")

    works_first_year: int | None = Field(None, description="Year of their earliest dated work, by publication date where there is one and creation date otherwise.")
    works_last_year: int | None = None

    western_editions: int | None = Field(None, description="How many of the language editions covering the individual are in Western languages.")
    non_western_editions: int | None = Field(None, description="How many are not.")
    notability: float | None = Field(None, description="The geometric mean of the two counts, 0 to about 282. A geometric mean rewards reach that crosses the divide: someone read in 100 Western and 100 non-Western editions scores 100, someone read in 200 Western and none scores 0. Compare it with CVDB's visibility and Pantheon's hpi, which rank the same people differently.")

    is_human: bool | None = Field(None, description="False for the rows that are not people — fictional characters, deities, legendary creatures. Wikidata classes them among humans, so filter on this before counting.")

    origins: dict[str, Origin] = Field({}, description="Where every value on this row came from, keyed by field name — the inherited ones as well as the computed ones. An entry with a rule was computed by this project; an entry without one was read from the raw field it names. On a row that carries both, that is the only way to tell which values are Wikidata's and which are ours.")


TABLES = {"individual": Individual, "individual_enriched": IndividualEnriched, "polity": Polity, "place": Place, "country_of_citizenship": CountryOfCitizenship, "occupation": Occupation, "work": Work, "identifier": Identifier, "individual_identifier": IndividualIdentifier, "sitelink": Sitelink, "wikidata_property": WikidataProperty}
