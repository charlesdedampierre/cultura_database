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
    name: str | None = Field(None, description="The polity's name as Cliopatria spells it — 'Ottoman Empire', 'Magadha - Shaishunaga dynasty'. Its own spelling, not Wikidata's.")
    type: Literal["POLITY", "RELATION"] | None = Field(None, description="'POLITY' for a polity in its own right, 'RELATION' for a dependency between two of them. A relation is not somewhere a person can be born, so filter on it before counting.")
    start: int | None = Field(None, description="First year the polity held ground, the earliest of its territories.")
    end: int | None = Field(None, description="Last year it held any. Empty for one that still exists.")
    wikidata_id: str | None = Field(None, description="The qid Cliopatria resolved for the polity, where it resolved one — the join out to Wikidata and to this project's other tables.")
    wikipedia_url: str | None = Field(None, description="Its English Wikipedia article. Cliopatria publishes the title and this is the URL built from it.")


class Individual(BaseModel):
    qid: str = Field(..., description="The individual's Wikidata item. Raw: IndividualWikidata.qid.")
    label: str | None = Field(None, description="English label, unquoted — the raw file gives it as the RDF literal '\"Claus Hammel\"@en'. Raw: IndividualWikidata.label.")
    description: str | None = Field(None, description="English one-line description, unquoted. Raw: IndividualWikidata.description.")
    date_of_birth: str | None = Field(None, description="P569 as an ISO string, '1879-03-14' — Wikidata's '1879-03-14T00:00:00Z' without the stamp, which is not a time of day. Raw: IndividualWikidata.date_of_birth.")
    date_of_birth_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely P569 is stated, as a word rather than the numeric code. Raw: IndividualWikidata.date_of_birth_precision.")
    date_of_death: str | None = Field(None, description="P570, on the same terms. Raw: IndividualWikidata.date_of_death.")
    date_of_death_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="Raw: IndividualWikidata.date_of_death_precision.")
    floruit: str | None = Field(None, description="P1317, a date a source states the individual was active. Rare, and a date rather than a range — not IndividualEnriched.peak_productivity_*, which this project computes. Raw: IndividualWikidata.floruit.")
    floruit_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="Raw: IndividualWikidata.floruit_precision.")
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


class IndividualEnriched(BaseModel):
    wikidata_id: str = Field(..., description="The individual, and the key back to every source: IndividualWikidata, CrossVerifiedPerson and PantheonPerson in datamodel_raw.py all carry it. Nothing else on this row was read from anywhere — every field below was computed by this project, and `origins` says from what and how.")

    birth_date: Date | None = Field(None, description="Date of birth as one value: the ISO string, the year read off it, and the precision. Built from IndividualWikidata.date_of_birth and .date_of_birth_precision, which arrive as two separate files and are one fact.")
    death_date: Date | None = Field(None, description="Date of death, on the same terms.")
    floruit_date: Date | None = Field(None, description="The P1317 date, on the same terms. Still a date Wikidata states, not the range below.")
    peak_productivity_start: int | None = Field(None, description="First year of the range this project takes the individual to have been at work. By convention that is from age 30 to age 60, truncated by an early death — so it is a claim about a life stage, not a record of anything observed.")
    peak_productivity_midpoint: int | None = Field(None, description="The single year that stands for the range, its middle. This is what to date an individual by in a distribution over time: birth and death are missing for most people before 1500, and a birth year dates someone decades before they did anything. It is the floruit as defined in the paper, and deliberately not called floruit — Wikidata has a property of that name, P1317, which is a date a source states rather than a range this project computes, and it is on IndividualWikidata.")
    peak_productivity_end: int | None = Field(None, description="Last year of the range.")
    peak_productivity_is_estimated: bool | None = Field(None, description="True when the range rests on an estimated birth or death year rather than an attested one. The range is still usable; it is simply softer, and this says so rather than leaving it to be discovered.")

    polity: Polity | None = Field(None, description="The historical polity the individual most belonged to. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods — theirs are in datamodel_raw.py.")
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

    origins: dict[str, Origin] = Field({}, description="How every value on this row was computed, keyed by field name. Every entry carries a rule and the inputs it was applied to — that is what separates this table from the three it joins.")
