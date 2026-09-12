from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

class Origin(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was built from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.birth', 'PolityCliopatria.geometry'. Every source the project reads is in that file in full, so this is the link back to the data exactly as it arrived, and from there to a Wikidata property and its definition.")
    inputs: tuple[str, ...] = Field((), description="For a value computed from another computed one, the fields of this table it was built on — the floruit from its start and end. Values read from a source name those in `raw` instead.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")

class Individual(BaseModel):
    wikidata_id: str = Field(..., description="The individual's Wikidata item. The key every other table joins on. Raw: IndividualWikidata.qid.")
    name: str | None = Field(None, description="English label, unquoted — the raw file gives it as the RDF literal '\"Claus Hammel\"@en'. Raw: IndividualWikidata.label.")
    description: str | None = Field(None, description="English one-line description, unquoted, e.g. 'German-born theoretical physicist'. Raw: IndividualWikidata.description.")
    birth_date: str | None = Field(None, description="Date of birth as an ISO string, '1879-03-14' — Wikidata's '1879-03-14T00:00:00Z' without the stamp, which is not a time of day. Only as precise as `birth_precision` says. Raw: IndividualWikidata.date_of_birth.")
    birth_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely Wikidata states the birth date, as a word rather than the raw code — 11 is a day, 9 a year, 7 a century. A date known only to the century still reads as a full ISO string, so this is the only way to know it is not one. Raw: IndividualWikidata.date_of_birth_precision.")
    death_date: str | None = Field(None, description="Date of death, on the same terms. Raw: IndividualWikidata.date_of_death.")
    death_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="Raw: IndividualWikidata.date_of_death_precision.")
    floruit_date: str | None = Field(None, description="A date Wikidata states the individual was active, P1317. Rare, and a date rather than a range — not to be confused with IndividualEnriched.peak_productivity_*, which this project computes. Raw: IndividualWikidata.floruit.")
    floruit_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="Raw: IndividualWikidata.floruit_precision.")
    birthplace: str | None = Field(None, description="Place of birth by name. Often a city, sometimes a country, sometimes a hospital — P19 makes no promise, and EntityTypeClassification is what tells them apart. Raw: IndividualWikidata.place_of_birth resolved against PlaceWikidata.label.")
    birthplace_wikidata_id: str | None = Field(None, description="Its qid, for joining to PlaceWikidata and to PlaceModernCountry. Raw: IndividualWikidata.place_of_birth.")
    deathplace: str | None = Field(None, description="Place of death, on the same terms. Raw: IndividualWikidata.place_of_death resolved against PlaceWikidata.label.")
    deathplace_wikidata_id: str | None = Field(None, description="Raw: IndividualWikidata.place_of_death.")
    gender: str | None = Field(None, description="Sex or gender by name. A free vocabulary in practice: 48 distinct values in the data, a few of them unresolved. Raw: IndividualWikidata.sex_or_gender resolved against its own label.")
    occupations: tuple[str, ...] = Field((), description="Occupations by name, in Wikidata's order: 'physicist', 'theoretical physicist'. Raw: IndividualWikidata.occupation resolved against OccupationWikidata.label.")
    citizenships: tuple[str, ...] = Field((), description="Countries of citizenship by name, in Wikidata's order, historical states included — 'Kingdom of Prussia' as readily as 'Germany'. Raw: IndividualWikidata.country_of_citizenship resolved against CountryWikidata.label.")
    writing_languages: tuple[str, ...] = Field((), description="Languages the individual wrote in, by name. Raw: IndividualWikidata.writing_language.")
    external_ids: dict[str, str] = Field({}, description="A map of external database to identifier, keyed by the Wikidata property that carries it: {'P214': '75121530'} is VIAF. Wikidata has 10 329 such properties, and Property says what each one is. Raw: IndividualWikidata.external_id.")
    wikipedia_articles: tuple[str, ...] = Field((), description="The URL of every Wikipedia article about the individual, one per language edition, up to 228. Raw: IndividualWikidata.sitelink.")
    works: tuple[str, ...] = Field((), description="The qid of every work credited to the individual. The property that credits them — P50 author, P170 creator, P175 performer — is in the raw pair and not kept here. Raw: IndividualWikidata.work.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by field name. Every entry here names a raw field and carries no rule: nothing on this row was computed, only unquoted, resolved to a label, or stripped of a stamp.")


class IndividualEnriched(BaseModel):
    wikidata_id: str = Field(..., description="The individual, and the key back to every source: IndividualWikidata, CrossVerifiedPerson and PantheonPerson in datamodel_raw.py all carry it. Nothing else on this row was read from anywhere — every field below was computed by this project, and `origins` says from what and how.")

    peak_productivity_start: int | None = Field(None, description="First year of the range this project takes the individual to have been at work. By convention that is from age 30 to age 60, truncated by an early death — so it is a claim about a life stage, not a record of anything observed.")
    peak_productivity_midpoint: int | None = Field(None, description="The single year that stands for the range, its middle. This is what to date an individual by in a distribution over time: birth and death are missing for most people before 1500, and a birth year dates someone decades before they did anything. It is the floruit as defined in the paper, and deliberately not called floruit — Wikidata has a property of that name, P1317, which is a date a source states rather than a range this project computes, and it is on IndividualWikidata.")
    peak_productivity_end: int | None = Field(None, description="Last year of the range.")
    peak_productivity_is_estimated: bool | None = Field(None, description="True when the range rests on an estimated birth or death year rather than an attested one. The range is still usable; it is simply softer, and this says so rather than leaving it to be discovered.")

    polity: str | None = Field(None, description="The historical polity the individual most belonged to. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods, on their own rows.")
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
