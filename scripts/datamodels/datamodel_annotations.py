"""Datamodel of the annotation sets.

TreccaniAnnotation is one row of the Treccani validation: an individual with a biography in
the Dizionario Biografico degli Italiani, what a language model read from that biography in
two steps (floruit and location, then the Cliopatria polity), the automatic checks on that
reading, what Cultura holds for the same individual, and the human verdict. Its fields were
drawn from annotations/treccani_validation/treccani_validation_sample20.tsv.
"""

from typing import Literal

from pydantic import BaseModel, Field

from datamodel_in_duckdb import AIAnswer, PeakProductivity, WikidataEntity


class SampleStratum(BaseModel):
    region: Literal["North", "Center", "South & Islands"] = Field(..., description="Where in Italy the individual was born, by the latitude of the birthplace: North from 44°, Center from 41.5°, South & Islands below. The sample is stratified on it so that one part of the peninsula cannot stand for all of it.")
    period_bin: Literal["<1300", "1300-1500", "1500-1650", "1650-1800", "1800+"] = Field(..., description="The period the individual's Cultura floruit falls in. The sample draws the same number of individuals from each bin, spreading regions inside a bin where it can.")
    seed: int = Field(..., description="The random seed the sample was drawn with. The same seed on the same database gives the same individuals.")


class Evidence(BaseModel):
    verbatim: tuple[str, ...] = Field((), description="Extracts copied word for word from the Treccani biography, in Italian, that support the answer. Copied rather than paraphrased, so each one can be checked against the text by a substring search.")
    english: tuple[str, ...] = Field((), description="The same extracts translated into English by the model, index-aligned with verbatim, for an annotator who does not read Italian.")


class FloruitExtraction(BaseModel):
    location: str | None = Field(None, description="The most granular place the individual was active in, under its English name where one exists — 'Florence', 'Messina'.")
    location_original: str | None = Field(None, description="The same place exactly as the biography writes it — 'Firenze', 'città peloritana'. Kept apart from location so the check that it appears in the quoted evidence is a plain string match.")
    location_type: Literal["city", "region", "other"] | None = Field(None, description="What kind of place location is. A city can be matched to a polity's territory far more surely than a region.")
    start_year: int | None = Field(None, description="First year of activity the biography states, negative before the common era. Empty where the text gives no start.")
    middle_years: tuple[int, ...] = Field((), description="Single dated years of activity the text gives between or instead of a start and an end — a treatise written in 1235, offices held in 1274 and 1289.")
    end_year: int | None = Field(None, description="Last year of activity the biography states.")
    dates_precise: bool | None = Field(None, description="True where the biography gives years, False where it only speaks in centuries or vaguer terms ('XIII secolo'). A window from imprecise dates should be judged as a century, not as years.")
    period_as_written: str | None = Field(None, description="The period of activity exactly as the text puts it — '1260-1298', 'XIII secolo'.")
    period_en: str | None = Field(None, description="The same period in English — '13th century'.")
    location_evidence: Evidence = Field(default_factory=Evidence, description="The extracts that place the individual's activity in location.")
    floruit_evidence: Evidence = Field(default_factory=Evidence, description="The extracts that date the individual's activity.")
    reasoning: str | None = Field(None, description="The model's own account, in one to three sentences, of how it chose the place and the period.")
    ai_answer: AIAnswer | None = Field(None, description="The model and prompt that produced this extraction — step 1 of the pipeline.")


class EvidenceCheck(BaseModel):
    location_quotes_in_text: bool | None = Field(None, description="Every location extract is a word-for-word substring of the biography, after whitespace is normalised. False means the model paraphrased or invented a quote.")
    floruit_quotes_in_text: bool | None = Field(None, description="Every floruit extract is a word-for-word substring of the biography.")
    location_name_in_quote: bool | None = Field(None, description="location_original appears inside at least one location extract, so the place is actually supported by what was quoted.")
    dates_in_quote: bool | None = Field(None, description="period_as_written appears inside at least one floruit extract, so the dates are actually supported by what was quoted.")
    evidence_verified: bool | None = Field(None, description="All four checks above hold. A row with this False should not be annotated before the extraction is rerun.")


class PolityRef(BaseModel):
    cliopatria_id: int | None = Field(None, description="The polity's id in Cliopatria, the join key to Polity in the database.")
    name: str | None = Field(None, description="The polity's name as Cliopatria writes it — 'Republic of Pisa', 'Holy Roman Empire'.")


class PolityMapping(BaseModel):
    polity: PolityRef | None = Field(None, description="The Cliopatria polity the model chose for location during the extracted period, from a candidate list it was given: the smallest, most local one that governed the place for the largest share of the period. Empty where no candidate could plausibly fit.")
    confidence: Literal["high", "medium", "low"] | None = Field(None, description="How sure the model says it is. Medium or low usually means the exact polity — a city-state, a duchy — is missing from Cliopatria and a larger one above it was taken instead.")
    reasoning: str | None = Field(None, description="The model's account of the choice, in one to three sentences.")
    ai_answer: AIAnswer | None = Field(None, description="The model and prompt that produced this mapping — step 2 of the pipeline.")


class CulturaComparison(BaseModel):
    peak_productivity: PeakProductivity | None = Field(None, description="Cultura's productivity window for the individual, as IndividualEnriched holds it — years, precision and label, and the rule that produced them.")
    polities: tuple[PolityRef, ...] = Field((), description="Every polity Cultura assigned the individual, as IndividualEnriched.polity lists them.")
    llm_floruit_min: int | None = Field(None, description="The earliest year in the extraction, over start_year, middle_years and end_year.")
    llm_floruit_max: int | None = Field(None, description="The latest year in the extraction, over the same three.")
    floruit_validated: bool | None = Field(None, description="True when the years the biography gives agree with Cultura's window: the extracted span lies inside it, or at least half of the span overlaps it. Empty where either side has no years.")
    polity_validated: bool | None = Field(None, description="True when the polity the model chose is one of Cultura's, by Cliopatria id or, failing that, by name.")


class HumanAnnotation(BaseModel):
    location_ok: bool | None = Field(None, description="The annotator agrees the biography places the individual's activity in location. Empty until annotated.")
    floruit_ok: bool | None = Field(None, description="The annotator agrees with the extracted period of activity.")
    polity_ok: bool | None = Field(None, description="The annotator agrees with the polity the model chose.")
    notes: str | None = Field(None, description="Anything the three verdicts do not say — why one is False, a doubt, a better polity.")


class TreccaniAnnotation(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual, by qid and label — the join key to Individual and IndividualEnriched.")
    dbi_url: str = Field(..., description="The individual's biography on treccani.it, the Dizionario Biografico degli Italiani (Wikidata P1986). It is the only text the model read.")
    sample: SampleStratum = Field(..., description="Which cell of the stratified sample the individual was drawn from.")
    extraction: FloruitExtraction = Field(default_factory=FloruitExtraction, description="Step 1: the place and the period of activity the model read from the biography, with its evidence.")
    evidence_check: EvidenceCheck = Field(default_factory=EvidenceCheck, description="The automatic checks that the step 1 evidence is really in the biography.")
    polity_mapping: PolityMapping = Field(default_factory=PolityMapping, description="Step 2: the Cliopatria polity the model matched to that place and period.")
    cultura: CulturaComparison = Field(default_factory=CulturaComparison, description="What Cultura holds for the same individual, and whether it agrees with the biography.")
    human: HumanAnnotation = Field(default_factory=HumanAnnotation, description="The annotator's verdict on the extraction and the mapping.")
