from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import WikidataEntity


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


class StagePolity(BaseModel):
    place: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual lived over the stage, as the reference says it.")
    cliopatria_polity: AIAnswer = Field(default_factory=AIAnswer, description="The Cliopatria polity of the database linked to the place over the stage's years; the answer is its name.")
    cliopatria_id: int | None = Field(None, description="The linked polity's id in the polity table.")


class BiographyData(BaseModel):
    birth_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual was born, according to the reference.")
    death_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual died, according to the reference.")
    first_work_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual's first work or first recorded activity took place.")
    last_work_date: AIAnswer = Field(default_factory=AIAnswer, description="When the individual's last work or last recorded activity took place.")
    early_stage_polity: StagePolity = Field(default_factory=StagePolity, description="The polity the individual lived in from birth to the first work.")
    active_stage_polity: StagePolity = Field(default_factory=StagePolity, description="The polity the individual lived in from the first to the last work.")
    late_stage_polity: StagePolity = Field(default_factory=StagePolity, description="The polity the individual lived in from the last work to death.")


class AnswerReview(BaseModel):
    is_correct: bool | None = Field(None, description="The annotator judges the answer correct.")
    note: str | None = Field(None, description="The annotator's comment.")


class StagePolityReview(BaseModel):
    place: AnswerReview = Field(default_factory=AnswerReview, description="Review of the place.")
    cliopatria_polity: AnswerReview = Field(default_factory=AnswerReview, description="Review of the polity linked to the place.")


class BiographyReview(BaseModel):
    birth_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the birth date.")
    death_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the death date.")
    first_work_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the first work date.")
    last_work_date: AnswerReview = Field(default_factory=AnswerReview, description="Review of the last work date.")
    early_stage_polity: StagePolityReview = Field(default_factory=StagePolityReview, description="Review of the early-stage polity.")
    active_stage_polity: StagePolityReview = Field(default_factory=StagePolityReview, description="Review of the active-stage polity.")
    late_stage_polity: StagePolityReview = Field(default_factory=StagePolityReview, description="Review of the late-stage polity.")


class ReferenceAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual.")
    reference_database: str = Field(..., description="The reference the biography comes from: 'treccani', 'cbdb'...")
    reference_id: str | None = Field(None, description="The individual's id in the reference.")
    reference_url: str | None = Field(None, description="The biography's page in the reference, if online.")
    reference_text_path: str | None = Field(None, description="The file holding the downloaded text or record.")
    biography: BiographyData = Field(default_factory=BiographyData, description="What the reference says, field by field, with the same names as IndividualEnriched.")
    human: BiographyReview = Field(default_factory=BiographyReview, description="The annotator's review of each field.")
