from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import Date, WikidataEntity


class AIAnswer(BaseModel):
    model_name: str | None = Field(None, description="The exact model id that answered — 'google/gemini-3.5-flash'. The same prompt to another model, or a later version, gives different answers.")
    prompt_id: str | None = Field(None, description="The name of the prompt, with its version — 'treccani_floruit_location_v6' — so answers from two versions of a prompt are never mixed.")
    prompt: str | None = Field(None, description="The prompt sent to the model, in full, as it was for this individual — instructions and biography — so the question can be read without the code that built it.")
    value: str | None = Field(None, description="The answer the model gave — 'Florence', '1260-1298', 'Republic of Pisa'.")
    value_as_written: str | None = Field(None, description="The answer exactly as the biography writes it — 'Firenze', 'città peloritana', 'XIII secolo'.")
    value_as_written_translated_english: str | None = Field(None, description="The same in English — 'Florence', '13th century'.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="How sure the model says it is. Medium or low on a polity usually means the exact one is missing from Cliopatria and a larger one above it was taken.")
    reasoning: str | None = Field(None, description="The model's own account of its answer, in one to three sentences.")
    verbatim: tuple[str, ...] = Field((), description="Extracts copied word for word from the Treccani biography, in Italian, that support the answer.")
    verbatim_translated_english: tuple[str, ...] = Field((), description="The same extracts translated into English, index-aligned with verbatim.")
    quotes_in_text: bool | None = Field(None, description="Every extract in verbatim is a word-for-word substring of the biography, after whitespace is normalised. False means the model paraphrased or invented a quote.")
    value_in_quote: bool | None = Field(None, description="value_as_written appears inside at least one extract, so the extracts really support the answer.")


class ProductivityWindow(AIAnswer):
    start: Date | None = Field(None, description="First date of activity the biography states, with its precision: 'XIII secolo' is a date at century precision, not the year 1201.")
    middle: tuple[Date, ...] = Field((), description="Single dated moments of activity the text gives between or instead of a start and an end — a treatise written in 1235, offices held in 1274 and 1289.")
    end: Date | None = Field(None, description="Last date of activity the biography states.")


class HumanAnnotation(BaseModel):
    location_ok: bool | None = Field(None, description="The annotator agrees the biography places the individual's activity in the location. Empty until annotated.")
    peak_productivity_window_ok: bool | None = Field(None, description="The annotator agrees with the productivity window.")
    notes: str | None = Field(None, description="Anything the two verdicts do not say — why one is False, a doubt.")


class TreccaniAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual, by qid and label — the join key to Individual.")
    treccani_url: str = Field(..., description="The individual's biography in the Dizionario Biografico degli Italiani on treccani.it (Wikidata P1986). It is the only text the model read.")
    treccani_text_path: str = Field("annotations/treccani_validation/_cache/dbi_pages.jsonl", description="Where the downloaded biography is kept, relative to the repository root: a JSON-lines file with one line per individual, {wikidata_id, dbi_url, text}. The text is the article as treccani.it served it, reduced to plain text; it is what the model read, cut at 25 000 characters, and what quotes_in_text is checked against.")
    location_ai_extracted: AIAnswer = Field(default_factory=AIAnswer, description="Extracted from the biography by a language model: where the biography says the individual was active: the most granular place, under its English name where one exists, with its evidence.")
    productivity_window_ai_extracted: ProductivityWindow = Field(default_factory=ProductivityWindow, description="Extracted from the biography by a language model: when the biography says the individual was active, with its evidence.")
    human: HumanAnnotation = Field(default_factory=HumanAnnotation, description="The annotator's verdict.")
