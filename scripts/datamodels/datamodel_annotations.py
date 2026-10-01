from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import WikidataEntity


class AIAnswer(BaseModel):
    answer: str | None = Field(None, description="The model's answer, in English — 'Florence', '1260-1298'.")
    answer_as_written_in_text: str | None = Field(None, description="The answer as the text writes it — 'Firenze', 'XIII secolo'.")
    answer_as_written_in_text_english: str | None = Field(None, description="answer_as_written_in_text in English.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="How sure the model says it is.")
    reasoning: str | None = Field(None, description="The model's justification, in one to three sentences.")
    source_verbatim: tuple[str, ...] = Field((), description="Word-for-word extracts of the text the answer comes from.")
    source_verbatim_english: tuple[str, ...] = Field((), description="source_verbatim in English, in the same order.")
    source_verbatim_not_invented: bool | None = Field(None, description="Automatic check: every extract in source_verbatim exists word for word in the text, so the model did not paraphrase or invent it.")
    answer_supported_by_source_verbatim: bool | None = Field(None, description="Automatic check: answer_as_written_in_text appears in at least one extract of source_verbatim, so the quotes really back the answer.")
    model_name: str | None = Field(None, description="The model that answered — 'google/gemini-3.5-flash'.")
    prompt_id: str | None = Field(None, description="The prompt's name and version — 'treccani_floruit_location_v6'.")
    prompt: str | None = Field(None, description="The full prompt sent for this individual.")


class HumanAnnotation(BaseModel):
    location_ok: bool | None = Field(None, description="The annotator agrees with the location.")
    peak_productivity_window_ok: bool | None = Field(None, description="The annotator agrees with the productivity window.")
    notes: str | None = Field(None, description="Free comments from the annotator.")


class TreccaniAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual, by qid and label.")
    treccani_url: str = Field(..., description="The biography on treccani.it (Wikidata P1986).")
    treccani_text_path: str = Field("annotations/treccani_validation/_cache/dbi_pages.jsonl", description="The file holding the downloaded text, one JSON line per individual.")
    location_ai_extracted: AIAnswer = Field(default_factory=AIAnswer, description="Where the individual was active, found in the text by a language model.")
    productivity_window_ai_extracted: AIAnswer = Field(default_factory=AIAnswer, description="When the individual was active, found in the text by a language model.")
    human: HumanAnnotation = Field(default_factory=HumanAnnotation, description="The annotator's verdict on the two answers.")
