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
    model_name: str | None = Field(None, description="The model used.")
    prompt_id: str | None = Field(None, description="The prompt's name.")
    prompt: str | None = Field(None, description="The full prompt sent.")
    cost_estimated: float | None = Field(None, description="Cost of the query, in US dollars.")


class AnswerReview(BaseModel):
    is_correct: bool | None = Field(None, description="The annotator judges the answer correct.")
    note: str | None = Field(None, description="The annotator's comment.")


class HumanAnnotation(BaseModel):
    location_ai_extracted: AnswerReview = Field(default_factory=AnswerReview, description="Review of the location.")
    productivity_window_ai_extracted: AnswerReview = Field(default_factory=AnswerReview, description="Review of the productivity window.")
    polity_ai_matched: AnswerReview = Field(default_factory=AnswerReview, description="Review of the polity.")


class TreccaniAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual.")
    treccani_url: str = Field(..., description="The biography on treccani.it.")
    treccani_text_path: str = Field("annotations/treccani_validation/treccani_texts.parquet", description="The file holding the downloaded text.")
    location_ai_extracted: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual was active, found by AI in the text.")
    productivity_window_ai_extracted: AIAnswer = Field(default_factory=AIAnswer, description="When the individual was active, found by AI in the text.")
    polity_ai_matched: AIAnswer = Field(default_factory=AIAnswer, description="The Cliopatria polity matched by AI to the location and window.")
    human: HumanAnnotation = Field(default_factory=HumanAnnotation, description="The annotator's review.")
