from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import Polity, WikidataEntity


class AIAnswer(BaseModel):
    answer: str | None = Field(None, description="The model's answer, in English.")
    answer_as_written_in_text: str | None = Field(None, description="The answer as written in the source.")
    answer_as_written_in_text_english: str | None = Field(None, description="The same, in English.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="The model's confidence.")
    reasoning: str | None = Field(None, description="The model's justification.")
    source: str | None = Field(None, description="What the model read: a URL, a file or a table.")
    source_verbatim: tuple[str, ...] = Field((), description="Word-for-word extracts of the source behind the answer.")
    source_verbatim_english: tuple[str, ...] = Field((), description="The extracts, in English.")
    source_verbatim_not_invented: bool | None = Field(None, description="Check: every extract exists in the source.")
    answer_supported_by_source_verbatim: bool | None = Field(None, description="Check: the answer appears in the extracts.")
    model_name: str | None = Field(None, description="The model used; empty when the value was read from a structured field, not by a model.")
    prompt_id: str | None = Field(None, description="The prompt's name.")
    prompt: str | None = Field(None, description="The full prompt sent.")
    cost_estimated: float | None = Field(None, description="Cost of the query, in US dollars.")


class BiographyData(BaseModel):
    birth_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual was born, according to the biography database.")
    death_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual died, according to the biography database.")
    first_work_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual's first work or first recorded activity took place.")
    last_work_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual's last work or last recorded activity took place.")
    early_stage_place: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual lived from birth to the first work, as the biography database says it.")
    early_stage_polity: Polity | None = Field(None, description="The Cliopatria polity of the polity table linked to early_stage_place over the stage's years.")
    active_stage_place: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual lived from the first to the last work, as the biography database says it.")
    active_stage_polity: Polity | None = Field(None, description="The Cliopatria polity of the polity table linked to active_stage_place over the stage's years.")
    late_stage_place: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual lived from the last work to death, as the biography database says it.")
    late_stage_polity: Polity | None = Field(None, description="The Cliopatria polity of the polity table linked to late_stage_place over the stage's years.")


class AnswerReview(BaseModel):
    is_correct: bool | None = Field(None, description="The annotator judges the answer correct.")
    note: str | None = Field(None, description="The annotator's comment.")


class BiographyReview(BaseModel):
    birth_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the birth date.")
    death_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the death date.")
    first_work_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the first work date.")
    last_work_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the last work date.")
    early_stage_place: AnswerReview = Field(default_factory=AnswerReview, description="Review of the early-stage place.")
    early_stage_polity: AnswerReview = Field(default_factory=AnswerReview, description="Review of the early-stage polity linked to the place.")
    active_stage_place: AnswerReview = Field(default_factory=AnswerReview, description="Review of the active-stage place.")
    active_stage_polity: AnswerReview = Field(default_factory=AnswerReview, description="Review of the active-stage polity linked to the place.")
    late_stage_place: AnswerReview = Field(default_factory=AnswerReview, description="Review of the late-stage place.")
    late_stage_polity: AnswerReview = Field(default_factory=AnswerReview, description="Review of the late-stage polity linked to the place.")


class BiographyDatabase(BaseModel):
    name: str = Field(..., description="Short name of the biography database: 'treccani', 'cbdb'...")
    description: str | None = Field(None, description="What the biography database is and what it covers, in one sentence.")
    url: str | None = Field(None, description="The biography database's home page.")


class BiographyDatabaseValidation(BaseModel):
    wikidata_entity: WikidataEntity = Field(..., description="The individual of the Cultura database being validated.")
    biography_database: BiographyDatabase = Field(..., description="The external biography database the biography comes from.")
    biography_database_id: str | None = Field(None, description="The individual's id in the biography database.")
    biography_database_url: str | None = Field(None, description="The individual's biography page in the biography database, if online.")
    biography_database_text_path: str | None = Field(None, description="The file holding the biography text or record downloaded from the biography database.")
    biography_database_extracted: BiographyData = Field(default_factory=BiographyData, description="What the biography database says, field by field, with the same names as IndividualEnriched.")
    human_review: BiographyReview = Field(default_factory=BiographyReview, description="The annotator's review of each extracted field.")
