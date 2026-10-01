from typing import Literal

from pydantic import BaseModel, Field

Precision = Literal["day", "month", "year", "decade", "century", "millennium"]


class ExportedIndividualCSV(BaseModel):
    wikidata_id: str = Field(..., description="The individual's Wikidata qid, 'Q937'. Individual.entity.qid.")
    wikidata_url: str = Field(..., description="The individual's Wikidata page, 'https://www.wikidata.org/wiki/Q937'.")
    label: str | None = Field(None, description="The English label, or the label in another language for an individual with none. Individual.entity.label_en, else label_non_en.")
    birth_date: str | None = Field(None, description="The birth date the peak activity window prefers: the first entry of Individual.birth_date stated to the decade or finer, else the first entry, in the list's order (Wikidata property, then Wikidata description, then life-expectancy estimate). Written as an ISO date, '1879-03-14', when stated to the day or month, and as the year otherwise; negative before the common era.")
    birth_precision: Precision | None = Field(None, description="How finely birth_date is known. A year at precision century stands for its whole century.")
    death_date: str | None = Field(None, description="The death date, chosen and written as birth_date is, from Individual.death_date.")
    death_precision: Precision | None = Field(None, description="How finely death_date is known.")
    activity_start: int | None = Field(None, description="First year of the peak activity window, IndividualEnriched.peak_productivity.start_year.")
    activity_end: int | None = Field(None, description="Last year of the peak activity window, IndividualEnriched.peak_productivity.end_year.")
    polities: str | None = Field(None, description="The names of the polities the individual is matched to during the window, IndividualEnriched.polity, joined by ' | '.")
    polity_ids: str | None = Field(None, description="Their Cliopatria ids, in the same order as polities, joined by ' | '.")
    time_spent_in_polity: str | None = Field(None, description="How many years of the activity window each polity covers, PolityMatch.years_spent_in_polity, each calendar year counted once, in the same order as polities, joined by ' | '.")
    seshat_ids: str | None = Field(None, description="The Seshat Databank ids of each polity over the window, PolityMatch.seshat_ids, in the same order as polities, joined by ' | '; a polity whose territories changed id during the window lists them oldest first, joined by ';', and one Seshat has not coded is left empty between its separators. Empty when no polity has one. Each id's page is http://seshat-db.org/core/polity/<id>.")
    meta_polities: str | None = Field(None, description="The meta polities those polities belonged to during the window, once each, joined by ' | '.")
    meta_polity_ids: str | None = Field(None, description="Their Cliopatria ids, in the same order as meta_polities, joined by ' | '.")
    occupations: str | None = Field(None, description="The English labels of Individual.occupation, read from the Occupation table, joined by ' | '.")
