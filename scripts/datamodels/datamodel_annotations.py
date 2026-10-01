from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import WikidataEntity


class AIAnswer(BaseModel):
    value: str | None = Field(None, description="The model's answer, in English — 'Florence', '1260-1298'.")
    value_as_written: str | None = Field(None, description="The answer as the text writes it — 'Firenze', 'XIII secolo'.")
    value_as_written_translated_english: str | None = Field(None, description="value_as_written in English.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="How sure the model says it is.")
    reasoning: str | None = Field(None, description="The model's justification, in one to three sentences.")
    verbatim: tuple[str, ...] = Field((), description="Word-for-word extracts from the text supporting the answer.")
    verbatim_translated_english: tuple[str, ...] = Field((), description="The extracts in English, in the same order.")
    quotes_in_text: bool | None = Field(None, description="Every extract is found word for word in the text.")
    value_in_quote: bool | None = Field(None, description="value_as_written appears in at least one extract.")
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
