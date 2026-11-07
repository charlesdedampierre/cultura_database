from typing import Literal

from pydantic import BaseModel, Field

YearPrecision = Literal["year", "decade", "century", "millennium"]
Source = Literal["wikidata", "estimated"]
SEPARATOR_NOTE = "separated by ' | '"


class ExportedIndividualCSV(BaseModel):
    wikidata_id: str = Field(..., description="The individual's Wikidata qid, 'Q937'. Individual.entity.qid.")
    label: str | None = Field(None, description="The English label, else the label in another language. Individual.entity.label_en, else label_non_en.")
    sex_or_gender: str | None = Field(None, description="'male', 'female', 'trans woman', 'trans man' or 'non-binary', else the Wikidata qid of the value. Individual.sex_or_gender.")
    birth_year: str = Field(..., description="Year of birth, negative before the common era, '-450'; for a date known only to the century or millennium, its label, '20th AC', '4th BC', '2nd millennium AC'. IndividualEnriched.birth_date.year (else coarse_label): Wikidata, else estimated from the cohort's age at death.")
    birth_precision: YearPrecision | None = Field(None, description="Precision of birth_year; a date stated to the day or month counts as 'year'. IndividualEnriched.birth_date.precision.")
    birth_source: Source | None = Field(None, description="'wikidata' when stated in Wikidata, 'estimated' when imputed from the cohort. IndividualEnriched.birth_date.source.")
    death_year: str = Field(..., description="Year of death, written as birth_year is. IndividualEnriched.death_date.year (else coarse_label).")
    death_precision: YearPrecision | None = Field(None, description="Precision of death_year, as birth_precision. IndividualEnriched.death_date.precision.")
    death_source: Source | None = Field(None, description="As birth_source. IndividualEnriched.death_date.source.")
    active_life_start: int = Field(..., description="First year of the active life. IndividualEnriched.start_of_active_life.year.")
    active_life_end: int | None = Field(None, description="Last year of the active life. IndividualEnriched.end_of_active_life.year.")
    active_life_start_precision: YearPrecision | None = Field(None, description="Precision of active_life_start, as birth_precision. IndividualEnriched.start_of_active_life.precision.")
    active_life_end_precision: YearPrecision | None = Field(None, description="Precision of active_life_end, as birth_precision. IndividualEnriched.end_of_active_life.precision.")
    active_life_source: Literal["dated works and positions", "estimated"] | None = Field(None, description="'dated works and positions' when read from the individual's dated works and positions held, 'estimated' when imputed from the activity ages of the cohort. IndividualEnriched.start_of_active_life.source.")
    occupations: str = Field(..., description=f"English labels of the Wikidata occupations (P106), {SEPARATOR_NOTE}. Individual.occupation, labels from the Occupation table.")
    occupation_domain: Literal["Culture", "Discovery/Science", "Leadership", "Sports/Games"] | None = Field(None, description="Occupational domain of the cohort analysis: the most frequent Occupation.meta_occupation among the individual's occupations, 'Other' left out, ties to the first listed; empty when none.")
    is_scientist: bool | None = Field(None, description="True when an occupation descends from scientist, Q901. Individual.is_scientist.")
    is_artist: bool | None = Field(None, description="True when an occupation descends from artist, Q483501. Individual.is_artist.")
    main_seshat_polity_id: str = Field(..., description="Seshat id of the main polity of the active life: the active-life polity with the most years and a Seshat id, then its Seshat polity whose years overlap the active life most. PolityMatch.seshat.id; page https://seshat-db.com/core/polity/<id>.")
    main_seshat_polity: str | None = Field(None, description="Seshat long name of main_seshat_polity_id, 'French Kingdom - Late Valois'; empty for an id the Seshat API does not list. PolityMatch.seshat.long_name.")
    pre_active_life_seshat_ids: str | None = Field(None, description=f"Every Seshat id over the years from birth to the start of the active life, polities with the most years first, oldest first within a polity, each once, {SEPARATOR_NOTE}. IndividualEnriched.pre_active_life_polity.seshat.id.")
    pre_active_life_seshat_polities: str | None = Field(None, description=f"Seshat long names of pre_active_life_seshat_ids, same order, 'no Seshat name' for an id the API does not list, {SEPARATOR_NOTE}.")
    active_life_seshat_ids: str = Field(..., description="As pre_active_life_seshat_ids, over the active life. IndividualEnriched.active_life_polity.seshat.id.")
    active_life_seshat_polities: str = Field(..., description="Seshat long names of active_life_seshat_ids, as pre_active_life_seshat_polities.")
    post_active_life_seshat_ids: str | None = Field(None, description="As pre_active_life_seshat_ids, from the end of the active life to death. IndividualEnriched.post_active_life_polity.seshat.id.")
    post_active_life_seshat_polities: str | None = Field(None, description="Seshat long names of post_active_life_seshat_ids, as pre_active_life_seshat_polities.")
    number_of_works: int = Field(..., description="Distinct works Wikidata credits to the individual (P50 author, P170 creator, P175 performer...), Individual.work counted once per work_qid; 0 for none.")
