from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AIAnswer(BaseModel):
    model_name: str | None = Field(None, description="Exact model id that produced the value.")
    prompt_id: str | None = Field(None, description="Name of the prompt file in scripts/prompts/ that was sent.")


class Provenance(BaseModel):
    raw: tuple[str, ...] = Field((), description="Fields of datamodel_raw.py the value was read from, as 'Model.field'.")
    inputs: tuple[str, ...] = Field((), description="Computed fields of this schema the value was built from.")
    rule: str | None = Field(None, description="For a computed value, the rule that produced it, in one sentence.")
    ai_answer: AIAnswer | None = Field(None, description="Set when a language model produced the value: which model and prompt.")
    retrieved_on: date | None = Field(None, description="Day the source was read.")


class Date(BaseModel):
    iso: str | None = Field(None, description="ISO date, '1879-03-14'; a leading minus is before the common era. Empty for a bare year.")
    year: int | None = Field(None, description="The year alone; negative before the common era.")
    precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely the source states the date.")
    field_provenance: dict[str, Provenance] = Field({}, description="Where this one date came from: no rule for a stated date, a rule for one the project worked out.")


class WikidataEntity(BaseModel):
    qid: str = Field(..., description="Wikidata identifier, 'Q937'; the join key between tables.")
    label_en: str | None = Field(None, description="English (or 'mul') label.")
    label_non_en: str | None = Field(None, description="Label in another language, only where there is no English one.")
    label_language: str | None = Field(None, description="Language code of the label the item has: 'en', 'mul', 'ru'...")
    description: str | None = Field(None, description="English one-line Wikidata description.")


class WikidataProperty(BaseModel):
    pid: str = Field(..., description="Property identifier, 'P569'.")
    label_en: str | None = Field(None, description="English label, 'date of birth'.")
    description: str | None = Field(None, description="What the property means, in Wikidata's words.")


class Coordinates(BaseModel):
    latitude: float | None = Field(None, description="Decimal degrees, negative south of the equator.")
    longitude: float | None = Field(None, description="Decimal degrees, negative west of Greenwich.")


class ExistencePeriod(BaseModel):
    inception: Date | None = Field(None, description="When it came into being, P571.")
    dissolution: Date | None = Field(None, description="When it ceased to exist, P576; empty if it still exists.")


class PresentDayState(BaseModel):
    name: str | None = Field(None, description="State name in English, 'Russia'.")
    iso_3166_1_alpha_3_code: str | None = Field(None, description="ISO 3166-1 alpha-3 code, 'RUS'.")
    continent: str | None = Field(None, description="Continent, with 'Latin America' and 'Middle East' regrouped from lists in data/ai_outputs/ (enrichment step 07).")
    is_western: bool | None = Field(None, description="Whether the state counts as Western, from a list in data/ai_outputs/ (enrichment step 07).")


class Sitelink(BaseModel):
    url: str = Field(..., description="Wikimedia edition URL, 'https://fr.wikipedia.org'; not all are Wikipedias.")
    label_en: str | None = Field(None, description="Edition name in English, 'French Wikipedia'.")
    language: str | None = Field(None, description="Language of the edition, as a qid.")
    is_western: bool | None = Field(None, description="Whether a Wikipedia edition counts as Western, from lists in data/ai_outputs/ (enrichment step 07); empty for other sites.")
    number_of_articles: int | None = Field(None, description="How many individuals in Cultura the edition has a page on.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class YearRange(BaseModel):
    start_year: int | None = Field(None, description="First year of the range.")
    end_year: int | None = Field(None, description="Last year of the range.")


class Territory(BaseModel):
    start_year: int | None = Field(None, description="First year the polity held this ground.")
    end_year: int | None = Field(None, description="Last year it held it.")
    area: float | None = Field(None, description="Area in square kilometres.")
    geometry: str | None = Field(None, description="GeoJSON Polygon or MultiPolygon as a string, WGS 84 longitude/latitude.")
    seshat_id: str | None = Field(None, description="Polity's Seshat Databank id over this span, where Seshat coded it.")
    present_day_states: tuple[PresentDayState, ...] = Field((), description="States holding this ground today.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class PolityLink(BaseModel):
    cliopatria_id: int | None = Field(None, description="Linked polity's id in the Polity table.")
    name: str | None = Field(None, description="Linked polity's name.")
    hierarchy_type: Literal["composite_polity", "allegiance", "alliance", "vassalage", "personal_union"] | None = Field(None, description="Kind of meta polity the link goes through.")
    start_year: int | None = Field(None, description="First year of the link.")
    end_year: int | None = Field(None, description="Last year of the link.")


class Polity(BaseModel):
    cliopatria_id: int | None = Field(None, description="Polity id, assigned by this project when Cliopatria was loaded.")
    name: str | None = Field(None, description="Name as Cliopatria spells it, 'Ottoman Empire'.")
    meta_polities: tuple[PolityLink, ...] = Field((), description="Meta polities this polity directly belonged to, with the years.")
    child_polities: tuple[PolityLink, ...] = Field((), description="Polities this meta polity was made of, with the years; empty on a base polity.")
    existence_wikidata: ExistencePeriod | None = Field(None, description="Inception and dissolution according to Wikidata.")
    entity: WikidataEntity | None = Field(None, description="Wikidata item Cliopatria resolved for the polity, if any.")
    sitelink: Sitelink | None = Field(None, description="English Wikipedia article.")
    territories: tuple[Territory, ...] = Field((), description="Ground held, one entry per change of borders, oldest first.")
    world: tuple[str, ...] = Field((), description="Cultural worlds the polity belongs to, from lists in data/ai_outputs/ (enrichment step 07).")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class WorksPeriod(BaseModel):
    first_year: int | None = Field(None, description="Year of the earliest cleaned work date (inception, else publication); estimated as birth year + age_at_first_work when no work is dated.")
    last_year: int | None = Field(None, description="Year of the latest cleaned work date; estimated as birth year + age_at_last_work when no work is dated.")
    age_at_first_work: int | None = Field(None, description="first_year minus the birth year.")
    age_at_last_work: int | None = Field(None, description="last_year minus the birth year.")
    source: Literal["dated works", "estimated"] | None = Field(None, description="'dated works' when read from the individual's works, 'estimated' when imputed from the mean ages of their cohort (notebooks_dates/02_works_periods).")
    field_provenance: dict[str, Provenance] = Field({}, description="Rule of each value, keyed by field: how the dated works were cleaned, or which cohort mean estimated it.")


class Notability(BaseModel):
    number_of_western_editions: int | None = Field(None, description="Western Wikipedia editions with a page on the individual.")
    number_of_non_western_editions: int | None = Field(None, description="Non-Western Wikipedia editions with a page on the individual.")
    cross_cultural_score: float | None = Field(None, description="Geometric mean of the two counts; 0 when either is 0.")


class PolityMatch(BaseModel):
    polity: Polity | None = Field(None, description="Matched polity: id, name, world and meta_polities only.")
    years_spent_in_polity: int | None = Field(None, description="Years of the flourishing range inside this polity, each year counted once.")
    assignation_method: Literal["polygon_of_birthplace", "polygon_of_deathplace", "polygon_of_country_of_citizenship", "url_of_birthplace", "url_of_deathplace", "url_of_country_of_citizenship"] | None = Field(None, description="Which location and which test made the match.")
    seshat_ids: tuple[str, ...] = Field((), description="Seshat ids of the polity's territories overlapping the flourishing range.")


class Place(BaseModel):
    entity: WikidataEntity = Field(..., description="Place's Wikidata item; cities, states and buildings share this table.")
    coordinates: Coordinates | None = Field(None, description="Point location, P625.")
    country: WikidataEntity | None = Field(None, description="Country Wikidata declares the place to be in, P17.")
    instance_of: tuple[WikidataEntity, ...] = Field((), description="Classes of the place, P31.")
    existence: ExistencePeriod | None = Field(None, description="Years the place existed.")
    present_day_state: PresentDayState | None = Field(None, description="State holding the ground today, from a reverse geocoder on the coordinates.")
    sitelink: Sitelink | None = Field(None, description="English Wikipedia article.")
    is_settlement: bool | None = Field(None, description="Whether the place is a populated place, from an AI classification of its classes (enrichment step 01).")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class Occupation(BaseModel):
    entity: WikidataEntity = Field(..., description="Occupation's Wikidata item.")
    subclass_of: tuple[WikidataEntity, ...] = Field((), description="Parent occupations, P279.")
    meta_occupation: Literal["Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other"] | None = Field(None, description="Cross-Verified level-1 domain of the occupation, from an AI classification of its label (enrichment step 12).")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class Identifier(BaseModel):
    property: WikidataProperty = Field(..., description="Property carrying the identifier, 'P214' for VIAF.")
    formatter_url: str | None = Field(None, description="URL template with $1 for the value, P1630.")
    issuer: WikidataEntity | None = Field(None, description="Organisation issuing the identifiers, P1629.")
    issuer_country: PresentDayState | None = Field(None, description="Country of the issuer.")
    official_website: str | None = Field(None, description="Website of the property or of its issuer, P856.")
    number_of_records: int | None = Field(None, description="How many records the database holds, P4876.")
    inception: Date | None = Field(None, description="When the database was founded, P571.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class IndividualIdentifier(BaseModel):
    qid: str = Field(..., description="Individual, joining to Individual.entity.qid.")
    pid: str = Field(..., description="Database, joining to Identifier.property.pid; a pair can recur with several values.")
    value: str | None = Field(None, description="Identifier as the database issued it.")
    url: str | None = Field(None, description="Record URL built from the formatter URL.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class IndividualSitelink(BaseModel):
    qid: str = Field(..., description="Entity the page is about.")
    url: str = Field(..., description="Page URL.")
    site_url: str | None = Field(None, description="Edition, joining to Sitelink.url.")
    title: str | None = Field(None, description="Article title in that edition.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class Work(BaseModel):
    entity: WikidataEntity = Field(..., description="Work's Wikidata item, its title as the label.")
    instance_of: tuple[WikidataEntity, ...] = Field((), description="Classes of the work, P31.")
    inception: Date | None = Field(None, description="When the work was made, P571.")
    publication_date: Date | None = Field(None, description="When it was first published, P577.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class IndividualWork(BaseModel):
    qid: str = Field(..., description="Individual credited.")
    work_qid: str = Field(..., description="Work, joining to Work.entity.qid.")
    credit_property: WikidataProperty | None = Field(None, description="Property that credits them: P50 author, P170 creator, P175 performer...")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class Individual(BaseModel):
    entity: WikidataEntity = Field(..., description="Individual's Wikidata item.")
    birth_date: tuple[Date, ...] = Field((), description="Every birth date, one per source, in order: Wikidata property, Wikidata description, life-expectancy estimate (enrichment step 13).")
    death_date: tuple[Date, ...] = Field((), description="Every death date, on the same terms.")
    floruit_date: tuple[Date, ...] = Field((), description="Every floruit date: Wikidata property, then Wikidata description.")
    place_of_birth: Place | None = Field(None, description="Birthplace, P19: qid and name only.")
    place_of_death: Place | None = Field(None, description="Deathplace, P20: qid and name only.")
    sex_or_gender: str | None = Field(None, description="P21, as a qid.")
    occupation: tuple[Occupation, ...] = Field((), description="Occupations, P106, as qids; labels are in the Occupation table.")
    country_of_citizenship: tuple[Place, ...] = Field((), description="Countries of citizenship, P27, historical states included.")
    writing_language: tuple[str, ...] = Field((), description="Writing languages, P6886, as qids.")
    external_id: tuple[IndividualIdentifier, ...] = Field((), description="Records held by external databases.")
    sitelink: tuple[IndividualSitelink, ...] = Field((), description="Wikimedia pages about the individual, one per edition.")
    work: tuple[IndividualWork, ...] = Field((), description="Works credited to the individual.")
    works_period: WorksPeriod | None = Field(None, description="Years spanned by their dated works.")
    is_human: bool | None = Field(None, description="False when a place they are tied to is fictional (enrichment step 04).")
    is_scientist: bool | None = Field(None, description="True when an occupation descends from scientist, Q901.")
    is_artist: bool | None = Field(None, description="True when an occupation descends from artist, Q483501.")
    field_provenance: dict[str, Provenance] = Field({}, description="Source or rule of each value, keyed by column.")


class IndividualEnriched(BaseModel):
    entity: WikidataEntity = Field(..., description="Individual, joining to Individual.entity.qid.")

    flourishing_year_range: YearRange | None = Field(None, description="Years the individual flourished, from the new date pipeline.")

    polity: tuple[PolityMatch, ...] = Field((), description="Every polity matched during the flourishing range, longest overlap first (enrichment step 10).")
    polity_count: int | None = Field(None, description="Number of polities matched, len(polity).")

    notability: Notability | None = Field(None, description="Western and non-Western Wikipedia coverage and the cross-cultural score (enrichment step 08).")

    field_provenance: dict[str, Provenance] = Field({}, description="Rule and inputs of each value, keyed by column.")


TABLES = {"individual": Individual, "individual_enriched": IndividualEnriched, "polity": Polity, "place": Place, "occupation": Occupation, "work": Work, "identifier": Identifier, "individual_identifier": IndividualIdentifier, "sitelink": Sitelink, "wikidata_property": WikidataProperty, "individual_sitelink": IndividualSitelink, "individual_work": IndividualWork}
