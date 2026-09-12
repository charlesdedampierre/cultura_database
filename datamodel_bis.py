"""Cultura, as it is published: one row per source, plus one row of what we made of them.

Four tables, all joined on `wikidata_id`:

    IndividualWikidata    what Wikidata says
    IndividualCV          what the cross-verified database of Laouenan et al. (2022) adds to it
    IndividualPantheon    what Pantheon 2.0 adds to it
    IndividualEnriched    what this project computed from them

Wikidata is the backbone, so it carries the names, the dates, the places, the
occupations. The other two carry only what it does not have: CVDB the
uncertainty windows around a year and its own occupation ontology, Pantheon the
GeoNames identifiers and its popularity index. Nothing is repeated across the
three, which is what makes the question "where does this come from" answerable
by looking at which table a column is in.

The source tables are cleaned, not corrected. A date is an ISO string rather
than Wikidata's '1879-03-14T00:00:00Z', a place is its English name rather than
a bare qid — but nothing is chosen, reconciled or filled in.

The fourth table is where this project's judgement lives, and nowhere else. It
holds the floruit, the polity, the notability score, the modern country under a
historical place — each with the rule that produced it, in `origins`.

The split exists so that a researcher can take the sources without taking our
conclusions, or run their own method against ours on the same individuals. A
table that mixed a birth date with a floruit would invite treating both as
given, and only one is.

Every table carries an `origins` map, keyed by field name, naming the fields of
datamodel_raw.py the value was read from — the link back to the data exactly as
it arrived. On IndividualEnriched every entry carries the inputs and the rule
instead, because nothing there was read.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Origin(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was read from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.death'. A raw field is named after its Wikidata property, so this also reaches the property's definition. Empty for a value computed here.")
    inputs: tuple[str, ...] = Field((), description="For a computed value, the published fields it was computed from, as 'Table.field', so the computation can be checked against the rows that carry them.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class IndividualWikidata(BaseModel):
    wikidata_id: str = Field(..., description="The individual's Wikidata item, and the key every other table joins on.")
    name: str | None = Field(None, description="English label.")
    description: str | None = Field(None, description="English one-line description, e.g. 'German-born theoretical physicist'.")
    birth_date: str | None = Field(None, description="Date of birth as an ISO string, '1879-03-14'. Only as precise as Wikidata states it — see `birth_precision`.")
    birth_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely Wikidata states the birth date. A date known only to the century still appears as a full ISO string, so this is the only way to know it is not one.")
    death_date: str | None = Field(None, description="Date of death, on the same terms.")
    death_precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = None
    floruit_date: str | None = Field(None, description="A date Wikidata states the individual was active, P1317. Rare, and not the same thing as the floruit this project computes.")
    birthplace: str | None = Field(None, description="Place of birth by name. Often a city, sometimes a country, sometimes a hospital — P19 makes no promise.")
    birthplace_wikidata_id: str | None = None
    birthplace_latitude: float | None = None
    birthplace_longitude: float | None = None
    deathplace: str | None = None
    deathplace_wikidata_id: str | None = None
    deathplace_latitude: float | None = None
    deathplace_longitude: float | None = None
    gender: str | None = Field(None, description="Sex or gender by name. A free vocabulary in practice: 48 distinct values in the data.")
    citizenships: tuple[str, ...] = Field((), description="Countries of citizenship in Wikidata's order, historical states included — 'Kingdom of Prussia' as readily as 'Germany'.")
    occupations: tuple[str, ...] = Field((), description="Occupations in Wikidata's order: 'physicist', 'theoretical physicist'.")
    writing_languages: tuple[str, ...] = Field((), description="Languages the individual wrote in.")
    wikipedia_editions: int | None = Field(None, description="Number of language editions carrying an article, 1 to 228. Counted over the sitelinks Wikidata lists, not over what this project fetched.")
    origins: dict[str, Origin] = Field({}, description="Which raw Wikidata field each value came from, keyed by field name. No entry here carries a rule: nothing on this row was computed.")


class IndividualCV(BaseModel):
    wikidata_id: str = Field(..., description="The qid this dataset resolved, and the key it joins on. Only what this dataset adds is here: its name, gender, dates, occupations and citizenships are on IndividualWikidata already.")
    birth_min: int | None = Field(None, description="Lower bound of the birth-year uncertainty window. Cultura's own model has a precision code but no window, so this is something only this source carries.")
    birth_max: int | None = Field(None, description="Upper bound.")
    death_min: int | None = Field(None, description="Lower bound of the death-year window.")
    death_max: int | None = Field(None, description="Upper bound.")
    approx_birth: str | None = Field(None, description="Approximation flag — circa, decade, century.")
    approx_death: str | None = None
    occupation_domain: Literal["Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other", "Missing"] | None = Field(None, description="Top-level occupation domain. The grouping this literature uses, which is why it is worth carrying even though Wikidata has its own occupations.")
    occupation_field: str | None = Field(None, description="Sub-domain — 'Culture-core', 'Politics', 'Academia'.")
    polity_1: str | None = Field(None, description="Primary historical-state attachment. This dataset's own answer to the question Cliopatria answers for Cultura: two independent methods, comparable row by row.")
    polity_2: str | None = None
    visibility: float | None = Field(None, description="Composite log-visibility score over five criteria. This dataset's ranking metric, as Pantheon's hpi and Cultura's notability are theirs — three answers to the same question.")
    visibility_rank: int | None = Field(None, description="Rank on that score; lower is more visible.")
    origins: dict[str, Origin] = Field({}, description="Which column of CrossVerifiedPerson each value came from, keyed by field name.")


class IndividualPantheon(BaseModel):
    wikidata_id: str = Field(..., description="The qid this dataset resolved, and the key it joins on. Only what this dataset adds is here: its name, gender, dates and place names are on IndividualWikidata already.")
    birthplace_geonames_id: int | None = Field(None, description="The GeoNames identifier. The one place in the published set where a place is identified outside Wikidata, which makes it useful for checking the Wikidata resolution.")
    birthplace_country: str | None = Field(None, description="Modern country of the birthplace, by name.")
    birthplace_polity: str | None = Field(None, description="The historical polity holding the birthplace, from GeaCron — a third answer to the polity question, after Cliopatria and CVDB.")
    deathplace_geonames_id: int | None = None
    deathplace_country: str | None = None
    deathplace_polity: str | None = None
    effective_editions: float | None = Field(None, description="An effective number of editions: always smaller than the count and never whole — 223 editions give 26.6 — because it discounts editions that carry little. Pantheon's answer to the problem Cultura's geometric mean addresses.")
    hpi: float | None = Field(None, description="Historical Popularity Index, Pantheon's ranking metric.")
    is_group: bool | None = Field(None, description="True when the row is not one person. Filter these out.")
    origins: dict[str, Origin] = Field({}, description="Which column of PantheonPerson each value came from, keyed by field name.")


class IndividualEnriched(BaseModel):
    wikidata_id: str = Field(..., description="The key back to the three source tables. Nothing else on this row was read from anywhere: every field below was computed by this project, and `origins` says how.")

    birth_year: int | None = Field(None, description="The birth year this project publishes, chosen among what the sources offer or estimated when none does. `origins` says which, and an estimated year should be left out of any analysis that depends on exact dating.")
    death_year: int | None = Field(None, description="The death year, on the same terms.")
    dating_precision: Literal["day", "year", "decade", "century"] | None = Field(None, description="How precisely the individual is dated, taking the coarser of the two years. Filter on it: 'century' individuals will distort any distribution over time.")

    floruit: int | None = Field(None, description="The single year that represents the individual's activity — what to date them by when birth and death are missing, which they are for most people before 1500. By convention an individual is active from age 30 to age 60, truncated by an early death, and this is the middle of that window.")
    floruit_start: int | None = Field(None, description="First year of the activity window.")
    floruit_end: int | None = Field(None, description="Last year of the activity window.")
    floruit_is_estimated: bool | None = Field(None, description="True when the window rests on an estimated year rather than an attested one. The floruit is still usable; it is simply softer, and this says so.")

    birthplace_country: str | None = Field(None, description="The country the birthplace is in today, so individuals can be aggregated on present-day borders. Not the country at the time: for that, see `polity`.")
    birthplace_country_iso: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country.")
    birthplace_is_settlement: bool | None = Field(None, description="True when the birthplace is a populated place rather than a hospital, a building or an administrative region. Wikidata names all of these as places of birth, and a study of urbanisation needs to tell them apart.")
    deathplace_country: str | None = None
    deathplace_country_iso: str | None = None

    polity: str | None = Field(None, description="The historical polity the individual most belonged to. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods, on their own rows.")
    polity_years: int | None = Field(None, description="Years of the activity window spent inside that polity. A small number means the match is incidental — someone who died abroad.")
    polity_count: int | None = Field(None, description="How many polities the individual overlaps at all. More than one is normal for a long life in a contested region.")

    is_scientist: bool | None = Field(None, description="True when any occupation descends from 'scientist' (Q901) through Wikidata's subclass tree.")
    is_artist: bool | None = Field(None, description="True when any occupation descends from 'artist' (Q483501).")

    number_of_works: int | None = Field(None, description="Works credited to the individual in Wikidata. A count of what Wikidata records, not of what they made.")
    works_first_year: int | None = Field(None, description="Year of their earliest dated work, by publication date where there is one and creation date otherwise.")
    works_last_year: int | None = None

    western_editions: int | None = Field(None, description="How many of the language editions covering the individual are in Western languages.")
    non_western_editions: int | None = Field(None, description="How many are not.")
    notability: float | None = Field(None, description="The geometric mean of the two counts, 0 to about 282. A geometric mean rewards reach that crosses the divide: someone read in 100 Western and 100 non-Western editions scores 100, someone read in 200 Western and none scores 0. Compare it with CVDB's visibility and Pantheon's hpi, which rank the same people differently.")

    is_human: bool | None = Field(None, description="False for the rows that are not people — fictional characters, deities, legendary creatures. Wikidata classes them among humans, so filter on this before counting.")

    origins: dict[str, Origin] = Field({}, description="How every value on this row was computed, keyed by field name. Every entry carries a rule and the inputs it was applied to — that is what separates this table from the three it joins.")
