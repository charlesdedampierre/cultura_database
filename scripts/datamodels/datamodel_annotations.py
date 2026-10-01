from typing import Literal

from pydantic import BaseModel, Field

import datamodel_in_duckdb as D
from datamodel_in_duckdb import Date, PeakProductivity, WikidataEntity


class AIAnswer(D.AIAnswer):
    value: str | None = Field(None, description="The answer the model gave — 'Florence', '1260-1298', 'Republic of Pisa'.")
    value_as_written: str | None = Field(None, description="The answer exactly as the biography writes it — 'Firenze', 'città peloritana', 'XIII secolo'.")
    value_as_written_translated_english: str | None = Field(None, description="The same in English — 'Florence', '13th century'.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="How sure the model says it is. Medium or low on a polity usually means the exact one is missing from Cliopatria and a larger one above it was taken.")
    reasoning: str | None = Field(None, description="The model's own account of its answer, in one to three sentences.")
    verbatim: tuple[str, ...] = Field((), description="Extracts copied word for word from the Treccani biography, in Italian, that support the answer.")
    verbatim_translated_english: tuple[str, ...] = Field((), description="The same extracts translated into English, index-aligned with verbatim.")
    quotes_in_text: bool | None = Field(None, description="Every extract in verbatim is a word-for-word substring of the biography, after whitespace is normalised. False means the model paraphrased or invented a quote.")
    value_in_quote: bool | None = Field(None, description="value_as_written appears inside at least one extract, so the extracts really support the answer.")


class Location(BaseModel):
    name: str | None = Field(None, description="The most granular place the individual was active in, under its English name where one exists — 'Florence', 'Messina'.")
    location_type: Literal["city", "region", "other"] | None = Field(None, description="What kind of place it is. A city can be matched to a polity's territory far more surely than a region.")
    ai_answer: AIAnswer | None = Field(None, description="The model's answer for the place, with its evidence.")


class ProductivityWindow(BaseModel):
    start: Date | None = Field(None, description="First date of activity the biography states, with its precision: 'XIII secolo' is a date at century precision, not the year 1201.")
    middle: tuple[Date, ...] = Field((), description="Single dated moments of activity the text gives between or instead of a start and an end — a treatise written in 1235, offices held in 1274 and 1289.")
    end: Date | None = Field(None, description="Last date of activity the biography states.")
    ai_answer: AIAnswer | None = Field(None, description="The model's answer for the period, with its evidence.")


class Polity(BaseModel):
    cliopatria_id: int | None = Field(None, description="The polity's id in Cliopatria, the join key to Polity in the database.")
    name: str | None = Field(None, description="The polity's name as Cliopatria writes it — 'Republic of Pisa'.")
    ai_answer: AIAnswer | None = Field(None, description="For a polity a model chose — the smallest one in the candidate list that governed the location for the largest share of the window — its answer. Empty for the polities Cultura assigned.")


class CulturaComparison(BaseModel):
    productivity_window: PeakProductivity | None = Field(None, description="Cultura's productivity window for the individual, as IndividualEnriched.peak_productivity holds it.")
    polities: tuple[Polity, ...] = Field((), description="Every polity Cultura assigned the individual, as IndividualEnriched.polity lists them.")
    productivity_window_validated: bool | None = Field(None, description="The biography's window agrees with Cultura's: it lies inside it, or at least half of it overlaps it. Empty where either side has no dates.")
    polity_validated: bool | None = Field(None, description="The polity the model chose is one of Cultura's, by Cliopatria id.")


class HumanAnnotation(BaseModel):
    location_ok: bool | None = Field(None, description="The annotator agrees the biography places the individual's activity in the location. Empty until annotated.")
    peak_productivity_window_ok: bool | None = Field(None, description="The annotator agrees with the productivity window.")
    polity_ok: bool | None = Field(None, description="The annotator agrees with the polity the model chose.")
    notes: str | None = Field(None, description="Anything the three verdicts do not say — why one is False, a doubt, a better polity.")


class TreccaniAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual, by qid and label — the join key to Individual and IndividualEnriched.")
    treccani_url: str = Field(..., description="The individual's biography in the Dizionario Biografico degli Italiani on treccani.it (Wikidata P1986). It is the only text the model read.")
    location: Location = Field(default_factory=Location, description="Where the biography says the individual was active.")
    productivity_window: ProductivityWindow = Field(default_factory=ProductivityWindow, description="When the biography says the individual was active.")
    polity: Polity = Field(default_factory=Polity, description="The Cliopatria polity a model matched to that location and window.")
    cultura: CulturaComparison = Field(default_factory=CulturaComparison, description="What Cultura holds for the same individual, and whether it agrees with the biography.")
    human: HumanAnnotation = Field(default_factory=HumanAnnotation, description="The annotator's verdict.")
