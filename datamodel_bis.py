"""Cultura, as it is published: one row per individual, every value attributable.

A row is flat and directly readable — `individual.birth_year` is an integer, not
a wrapper you have to unpack. Where a value came from lives beside it, in
`origins`, keyed by the field name:

    einstein.birth_year            1879
    einstein.origins["birth_year"] Origin(dataset='wikidata', reference='P569', …)

    einstein.floruit               1919
    einstein.origins["floruit"]    Origin(dataset='cultura', inputs=('birth_year', 'death_year'),
                                          rule='midpoint of the window an individual is active over…')

Nothing in this file is taken on trust. Every field is either read from a named
dataset or computed here, and `origins` says which for every one of them, with
the property or column it was read from, or the inputs and the rule it was
computed with. A field with no entry in `origins` is a field with no value.

Five datasets feed it. Wikidata is the backbone; the cross-verified database of
Laouenan et al. (2022) and Pantheon 2.0 supply dates and occupations Wikidata
lacks; Wikipedia articles read by a language model supply dates neither has;
and Cliopatria supplies the historical polities. `Origin.dataset` names which,
and `sources.json` records the exact release and the day it was read.

Where they disagree, this file publishes one answer and says how it was chosen:
`origins` carries the rule. The candidates themselves are not published here —
they are in the working model, `datamodel.py`, where a birth date is a list of
every date every source offered.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Origin(BaseModel):
    dataset: Literal["wikidata", "cross_verified_database", "pantheon_2", "wikipedia", "cliopatria", "cultura"] = Field(..., description="Which dataset the value was read from, or 'cultura' when this project computed it. sources.json records the release of each one and the day it was read.")
    reference: str | None = Field(None, description="What it was read from inside that dataset: a Wikidata property id such as 'P569', a column name such as 'level1_main_occ', or a Cliopatria field. Empty for a computed value.")
    inputs: tuple[str, ...] = Field((), description="For a computed value, the fields of this row it was computed from, so the computation can be checked against the row that carries it. Empty for a value that was read.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the dataset was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class Individual(BaseModel):
    wikidata_id: str | None = Field(None, description="The individual's Wikidata item, 'Q937'. The join key to Wikidata and to every other dataset here. Empty for an individual a dataset named but never resolved to Wikidata.")
    name: str | None = Field(None, description="English name.")
    description: str | None = Field(None, description="English one-line description, e.g. 'German-born theoretical physicist'.")

    birth_year: int | None = Field(None, description="Year of birth, negative before the common era. Read from a dataset where one gives it, otherwise estimated — `origins` says which, and an estimated year should be excluded from any analysis that depends on exact dating.")
    death_year: int | None = Field(None, description="Year of death, on the same terms.")
    birth_date: str | None = Field(None, description="Full date of birth as an ISO string, '1879-03-14', when a source gives one. Empty when only the year is known, which is the common case before 1800.")
    death_date: str | None = Field(None, description="Full date of death, on the same terms.")
    dating_precision: Literal["day", "year", "decade", "century"] | None = Field(None, description="How precisely this individual is dated, taking the coarsest of the two years. Filter on it: 'century' individuals will distort any distribution over time.")

    floruit: int | None = Field(None, description="The single year that represents the individual's activity — what to date them by when birth and death are missing, which they are for most people before 1500. By convention an individual is active from age 30 to age 60, truncated by an early death, and this is the middle of that window.")
    floruit_start: int | None = Field(None, description="First year of the activity window.")
    floruit_end: int | None = Field(None, description="Last year of the activity window.")
    floruit_is_estimated: bool | None = Field(None, description="True when the window rests on an estimated birth or death year rather than an attested one. The floruit is still usable; it is simply softer, and this says so.")

    birthplace: str | None = Field(None, description="Place of birth as named by the source. Often a city, sometimes a country, sometimes a hospital — see `birthplace_is_settlement`.")
    birthplace_wikidata_id: str | None = Field(None, description="Its Wikidata item, for joining to any other dataset.")
    birthplace_latitude: float | None = Field(None, description="Decimal degrees.")
    birthplace_longitude: float | None = Field(None, description="Decimal degrees.")
    birthplace_country: str | None = Field(None, description="The country the birthplace is in today, so individuals can be aggregated on present-day borders. Not the country at the time: for that, see `polity`.")
    birthplace_country_iso: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, 'DEU'.")
    birthplace_is_settlement: bool | None = Field(None, description="True when the birthplace is a populated place rather than a hospital, a building or an administrative region. Wikidata names all of these as places of birth, and a study of urbanisation needs to tell them apart.")

    deathplace: str | None = Field(None, description="Place of death, on the same terms as the birthplace.")
    deathplace_wikidata_id: str | None = None
    deathplace_latitude: float | None = None
    deathplace_longitude: float | None = None
    deathplace_country: str | None = Field(None, description="The country the deathplace is in today.")
    deathplace_country_iso: str | None = None

    polity: str | None = Field(None, description="The historical polity the individual most belonged to — 'Kingdom of France', 'Ottoman Empire'. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here.")
    polity_years: int | None = Field(None, description="Years of the activity window spent inside that polity. A small number means the match is incidental — someone who died abroad — and a number close to the window means a life spent inside it.")
    polity_count: int | None = Field(None, description="How many polities the individual overlaps at all. More than one is normal for a long life in a contested region, and is a reason to treat `polity` as the dominant one rather than the only one.")
    citizenships: tuple[str, ...] = Field((), description="Countries of citizenship as Wikidata states them, in its order, historical states included — 'Kingdom of Prussia' as readily as 'Germany'.")

    occupations: tuple[str, ...] = Field((), description="Occupations as Wikidata states them, in its order: 'physicist', 'theoretical physicist'.")
    occupation_domain: Literal["Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other", "Missing"] | None = Field(None, description="The coarse grouping used by the cross-verified database, carried here so results can be compared with that literature. 'Missing' means the individual's occupations map to none of them.")
    occupation_field: str | None = Field(None, description="Finer grouping from the same source — 'Academia', 'Politics', 'Culture-core'.")
    is_scientist: bool | None = Field(None, description="True when any occupation descends from 'scientist' (Q901) through Wikidata's subclass tree. Computed, not asserted by a source.")
    is_artist: bool | None = Field(None, description="True when any occupation descends from 'artist' (Q483501), on the same terms.")

    number_of_works: int | None = Field(None, description="Works credited to the individual in Wikidata — books, paintings, films, compositions. A count of what Wikidata records, not of what they made.")
    works_first_year: int | None = Field(None, description="Year of their earliest dated work, by publication date where there is one and creation date otherwise.")
    works_last_year: int | None = Field(None, description="Year of their latest dated work.")

    wikipedia_editions: int | None = Field(None, description="Number of Wikipedia language editions carrying an article about the individual, from 1 to 228. The simplest measure of reach here.")
    western_editions: int | None = Field(None, description="How many of those editions are in Western languages.")
    non_western_editions: int | None = Field(None, description="How many are not.")
    notability: float | None = Field(None, description="The geometric mean of the two counts, 0 to about 282. A geometric mean rewards reach that crosses the divide: someone read in 100 Western and 100 non-Western editions scores 100, someone read in 200 Western and none scores 0. It is the ranking used throughout this project, and it is deliberately not a page-view count.")

    is_human: bool | None = Field(None, description="False for the rows that are not people — fictional characters, deities, legendary creatures. Wikidata classes them among humans and this project does not remove them, so filter on this before counting.")
    in_pantheon: bool | None = Field(None, description="True when the individual also appears in Pantheon 2.0, which makes the two datasets comparable row by row.")
    in_cross_verified_database: bool | None = Field(None, description="True when they also appear in the cross-verified database of Laouenan et al. (2022).")

    origins: dict[str, Origin] = Field({}, description="Where every value on this row came from, keyed by field name. A field with no entry here has no value. This is what makes the row auditable: nothing in it is an assertion without a stated source or a stated rule.")
