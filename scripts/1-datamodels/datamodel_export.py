from pydantic import BaseModel, Field


class ExportedPolity(BaseModel):
    cliopatria_id: int | None = Field(None, description="The polity's Cliopatria id, PolityMatch.polity.cliopatria_id.")
    name: str | None = Field(None, description="The polity's name as Cliopatria spells it, PolityMatch.polity.name.")
    seshat_ids: list[str] = Field([], description="The Seshat Databank ids of the polity's territories overlapping the stage, oldest first, PolityMatch.seshat_ids; empty where Seshat has not coded it. Each id's page is http://seshat-db.org/core/polity/<id>.")
    years_spent_in_polity: int | None = Field(None, description="Years of the stage spent inside the polity, each year counted once, PolityMatch.years_spent_in_polity.")
    certainty: str | None = Field(None, description="'certain' when the location is a direct witness of the stage, 'unsure' for a fallback field, PolityMatch.certainty.")


class ExportedIndividualCSV(BaseModel):
    wikidata_id: str = Field(..., description="The individual's Wikidata qid, 'Q937'. Individual.entity.qid.")
    label: str | None = Field(None, description="The English label, or the label in another language for an individual with none. Individual.entity.label_en, else label_non_en.")
    birth_date: str | None = Field(None, description="IndividualEnriched.birth_date: the Wikidata birth, else the estimate from the cohort's age at death. Written as an ISO date, '1879-03-14', when stated to the day or month, and as the year otherwise; negative before the common era. Empty for an individual with only coarse dates.")
    death_date: str | None = Field(None, description="IndividualEnriched.death_date, written as birth_date is.")
    pre_active_life_range: str | None = Field(None, description="Years from birth to the start of the active life, 'start/end' (ISO 8601 interval), IndividualEnriched.birth_date.year / start_of_active_life.year; '-450/-420' before the common era.")
    active_life_range: str | None = Field(None, description="Years of the active life, 'start/end', IndividualEnriched.start_of_active_life.year / end_of_active_life.year.")
    post_active_life_range: str | None = Field(None, description="Years from the end of the active life to death, 'start/end', IndividualEnriched.end_of_active_life.year / death_date.year.")
    pre_active_life_polities: str | None = Field(None, description="The polities matched over pre_active_life_range, IndividualEnriched.pre_active_life_polity, longest overlap first, as a JSON list of ExportedPolity: [{\"cliopatria_id\": 12, \"name\": \"Roman Republic\", \"seshat_ids\": [\"it_roman_rep_1\"], \"years_spent_in_polity\": 20, \"certainty\": \"certain\"}]. Empty when none is matched.")
    active_life_polities: str | None = Field(None, description="The polities matched over active_life_range, IndividualEnriched.active_life_polity, as pre_active_life_polities is.")
    post_active_life_polities: str | None = Field(None, description="The polities matched over post_active_life_range, IndividualEnriched.post_active_life_polity, as pre_active_life_polities is.")
    occupations: str | None = Field(None, description="The English labels of Individual.occupation, read from the Occupation table, joined by ' | '.")
    number_of_works: int = Field(..., description="How many distinct works Wikidata credits to the individual, Individual.work counted once per work_qid whatever the crediting property (P50 author, P170 creator, P175 performer...); 0 for an individual with none.")
