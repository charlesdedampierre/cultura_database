from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Origin(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was built from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.birth', 'PolityCliopatria.geometry'. Every source the project reads is in that file in full, so this is the link back to the data exactly as it arrived, and from there to a Wikidata property and its definition.")
    inputs: tuple[str, ...] = Field((), description="For a value computed from another computed one, the fields of this table it was built on — the floruit from its start and end. Values read from a source name those in `raw` instead.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class IndividualEnriched(BaseModel):
    wikidata_id: str = Field(..., description="The individual, and the key back to every source: IndividualWikidata, CrossVerifiedPerson and PantheonPerson in datamodel_raw.py all carry it. Nothing else on this row was read from anywhere — every field below was computed by this project, and `origins` says from what and how.")

    birth_year: int | None = Field(None, description="The birth year this project publishes. It is here, rather than left to be read off IndividualWikidata.date_of_birth, because Wikidata dates most individuals after 1500 and few before it: for the rest this is taken from another source or estimated, and `origins` says which. `origins` says which, and an estimated year should be left out of any analysis that depends on exact dating.")
    death_year: int | None = Field(None, description="The death year, on the same terms.")

    floruit: int | None = Field(None, description="The single year that represents the individual's activity — what to date them by when birth and death are missing, which they are for most people before 1500. By convention an individual is active from age 30 to age 60, truncated by an early death, and this is the middle of that window.")
    floruit_start: int | None = Field(None, description="First year of the activity window.")
    floruit_end: int | None = Field(None, description="Last year of the activity window.")
    floruit_is_estimated: bool | None = Field(None, description="True when the window rests on an estimated year rather than an attested one. The floruit is still usable; it is simply softer, and this says so.")

    birthplace_modern_country: str | None = Field(None, description="The country holding the birthplace's ground today, found by point-in-polygon on its coordinates — not what Wikidata declares, which is on IndividualWikidata and is often a state that no longer exists. Use this to aggregate on present-day borders, and `polity` for the state of the time.")
    birthplace_modern_country_iso: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country. Always filled where the country is, since a country that holds ground today has a code.")
    birthplace_is_settlement: bool | None = Field(None, description="True when the birthplace is a populated place rather than a hospital, a building or an administrative region. Wikidata names all of these as places of birth, and a study of urbanisation needs to tell them apart.")
    deathplace_modern_country: str | None = None
    deathplace_modern_country_iso: str | None = None

    polity: str | None = Field(None, description="The historical polity the individual most belonged to. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods, on their own rows.")
    polity_years: int | None = Field(None, description="Years of the activity window spent inside that polity. A small number means the match is incidental — someone who died abroad.")
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
