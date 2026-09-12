"""Cultura data model — the single source of truth for the database schema.

This file defines the schema the DuckDB database is generated FROM. It is no
longer a flat mirror of the current `data/humans_clean.duckdb`: the 18 flat
tables become three — `Individual`, `Work`, `Occupation` — because a Wikidata
item is modelled once, as an `Entity`, instead of being spread over an id column
and a label column.

Everything else lives nested inside `Individual`: `Place` (birthplace,
deathplace), `Citizenship`, `WritingLanguage`, `ExternalIdentifier` with its
`IdentifierType`, `Floruit`, and `Polity` with its periods and modern countries.
Those nested models are already separate classes, so promoting any of them back
to its own table later is a one-line change to `TABLES`.

    Property      a Wikidata property: its id, its name, its definition.
    Entity        a Wikidata item: its qid, its English label and description.
    Wikidata[T]   a value read from a property — carries the property and the
                  extraction date. Wikidata is edited continuously, so the date
                  is mandatory and a Wikidata field needs no description: the
                  property definition already says what the value means.
    External[T]   a value from another dataset (Pantheon 2.0, CVDB, Cliopatria,
                  Wikipedia) — carries the platform and the extraction date.
    Derived[T]    a value computed from other fields — carries those fields and
                  the rule.
    AIAnswer[T]   a value produced by a language model — carries the exact model
                  id and the exact prompt, both mandatory.

What the restructuring removes: every `*_en` / `*_id` twin (one `Entity` instead),
the `individuals_keys` table (it held only the ids of labels on `individuals`),
the `individual_writing_languages` join table (a tuple of `WritingLanguage`), and
the `wikidata_properties_definition` table (superseded by `PROPERTIES`).

Nothing is dropped silently: `LEGACY_COLUMNS` maps each of the 196 columns of the
live database to its place in this model, and the self-check asserts the map is
complete.

Self-check: `python datamodel.py`
"""

from datetime import date
from typing import Annotated, Generic, Literal, TypeVar, get_args

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

T = TypeVar("T")

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Property(Model):
    id: str = Field(..., description="Wikidata property id, e.g. 'P569'. Non-property sources keep their RDF term, e.g. 'rdfs:label'.")
    name: str = Field(..., description="Label of the property, e.g. 'date of birth'.")
    definition: str = Field(..., description="What the property means, e.g. 'date on which the subject was born'. This is why a Wikidata field carries no separate description.")


class Entity(Model):
    qid: QID | None = Field(None, description="Wikidata item id, e.g. 'Q937'. NULL when the item was named in a source but never resolved to Wikidata.")
    label_en: str | None = Field(None, description="English label of the item. Wikidata rdfs:label.")
    description_en: str | None = Field(None, description="English one-line description of the item. Wikidata schema:description.")
    date_of_extraction: date = Field(..., description="Day the item was read from Wikidata.")


class Wikidata(Model, Generic[T]):
    property: Property = Field(..., description="Property the value was read from.")
    value: T | None = Field(None, description="The value itself, exactly as read from Wikidata.")
    date_of_extraction: date = Field(..., description="Day the value was pulled from Wikidata. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")


ExternalPlatform = Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"]


class External(Model, Generic[T]):
    platform: ExternalPlatform = Field(..., description="Dataset the value was taken from.")
    value: T | None = Field(None, description="The value itself, as read from that dataset.")
    dataset_version: str | None = Field(None, description="Version or release of the dataset.")
    date_of_extraction: date = Field(..., description="Day the value was taken from the dataset.")


class Derived(Model, Generic[T]):
    value: T | None = Field(None, description="The computed value.")
    derived_from: tuple[str, ...] = Field(..., min_length=1, description="Fields the value was computed from, as 'Model.field'.")
    rule: str = Field(..., description="The rule applied to those fields, in one sentence.")
    computed_on: date | None = Field(None, description="Day the computation was run.")


class AIAnswer(Model, Generic[T]):
    value: T | None = Field(None, description="The value the model returned.")
    model: str = Field(..., description="Exact model id that produced the value.")
    prompt: str = Field(..., description="Exact prompt sent to the model, verbatim.")
    answered_on: date | None = Field(None, description="Day the model was queried.")


LABEL = Property(id="rdfs:label", name="label (English)", definition="the English label of the item")
DESCRIPTION = Property(id="schema:description", name="description (English)", definition="the English one-line description of the item")
SITELINK = Property(id="schema:about", name="Wikimedia sitelink", definition="a Wikipedia article about the item, in one language edition")
P17 = Property(id="P17", name="country", definition="sovereign state that the item is located in")
P19 = Property(id="P19", name="place of birth", definition="most specific known birth location of a person")
P20 = Property(id="P20", name="place of death", definition="most specific known death location of a person")
P21 = Property(id="P21", name="sex or gender", definition="sex or gender identity of the subject")
P27 = Property(id="P27", name="country of citizenship", definition="country that recognises the subject as its citizen")
P30 = Property(id="P30", name="continent", definition="continent the item is part of")
P31 = Property(id="P31", name="instance of", definition="class of which the subject is a particular example and member")
P36 = Property(id="P36", name="capital", definition="seat of government of the country or administrative division")
P106 = Property(id="P106", name="occupation", definition="occupation of a person")
P279 = Property(id="P279", name="subclass of", definition="the subject is a subclass of the object; all its instances are instances of the object")
P298 = Property(id="P298", name="ISO 3166-1 alpha-3 code", definition="three-letter country code of the modern country")
P569 = Property(id="P569", name="date of birth", definition="date on which the subject was born")
P570 = Property(id="P570", name="date of death", definition="date on which the subject died")
P571 = Property(id="P571", name="inception", definition="time when the item began to exist")
P576 = Property(id="P576", name="dissolved, abolished or demolished date", definition="date the item ceased to exist")
P577 = Property(id="P577", name="publication date", definition="date a work was first published or released")
P625 = Property(id="P625", name="coordinate location", definition="latitude and longitude of the item")
P856 = Property(id="P856", name="official website", definition="URL of the official website of the item")
P1317 = Property(id="P1317", name="floruit", definition="date when the person was known to be active or alive")
P1629 = Property(id="P1629", name="subject item of this property", definition="the item that this property is about, e.g. the organization issuing an identifier")
P4876 = Property(id="P4876", name="number of records", definition="total number of records held by a database")
P6886 = Property(id="P6886", name="writing language", definition="language in which the writer has written their work")
EXTERNAL_ID = Property(id="(any external-ID property)", name="external identifier", definition="an identifier for the subject in an external database")

CREDIT_PROPERTIES: dict[str, Property] = {
    "author": Property(id="P50", name="author", definition="main creator of a written work"),
    "composer": Property(id="P86", name="composer", definition="person who wrote the music"),
    "creator": Property(id="P170", name="creator", definition="maker of this creative work"),
    "director": Property(id="P57", name="director", definition="director of a film or performance"),
    "editor": Property(id="P98", name="editor", definition="person who edited the work"),
    "illustrator": Property(id="P110", name="illustrator", definition="person who drew the illustrations"),
    "performer": Property(id="P175", name="performer", definition="performer of the work"),
    "producer": Property(id="P162", name="producer", definition="producer of the work"),
    "screenwriter": Property(id="P58", name="screenwriter", definition="author of the screenplay"),
}

PROPERTIES: dict[str, Property] = {p.id: p for p in (LABEL, DESCRIPTION, SITELINK, P17, P19, P20, P21, P27, P30, P31, P36, P106, P279, P298, P569, P570, P571, P576, P577, P625, P856, P1317, P1629, P4876, P6886, EXTERNAL_ID, *CREDIT_PROPERTIES.values())}

RELATIONSHIP_FROM_PROPERTY: dict[str, str] = {p.id: role for role, p in CREDIT_PROPERTIES.items()}

Relationship = Literal["author", "composer", "creator", "director", "editor", "illustrator", "performer", "producer", "screenwriter"]

CliopatriaOrigin = Literal["birthplace", "deathplace", "country_of_citizenship"]

CliopatriaMethod = Literal["merge_with_polygon", "merge_with_url"]

FloruitMethod = Literal[
    "birth_only_property",
    "birth_only_description",
    "birth_only_cv",
    "birth_only_wikipedia",
    "birth_death_property",
    "birth_death_description",
    "birth_death_cv",
    "birth_death_wikipedia",
    "birth_death_estimated_birth",
    "birth_century",
    "birth_death_century",
    "death_century",
    "floruit_property",
    "floruit_property_century",
    "floruit_property_decade",
    "floruit_description",
    "floruit_wikipedia",
    "floruit_wikipedia_span",
    "works_span",
    "works_single",
    "under_30",
    "no_data",
]

FloruitSource = Literal["wikidata_property", "wikidata_description", "works", "life_expectancy", "cv_database", "wikipedia", "none"]

PrecisionClass = Literal["year", "decade", "century"]

LifeExpectancyLookupSource = Literal["birth_bin", "category+birth_bin:Leadership", "category+birth_bin:Culture", "category+birth_bin:Sports/Games", "category+birth_bin:Discovery/Science", "category+birth_bin:Other"]

MetaOccupation = Literal["scientist", "artist"]

Level1Occupation = Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]

PolityType = Literal["POLITY", "RELATION"]

WIKIDATA_EXTRACTION_DATES: dict[str, date] = {
    "core_individual_facts": date(2026, 2, 13),
    "genders_writing_languages_countries": date(2026, 2, 14),
    "modern_country_resolution": date(2026, 2, 26),
    "place_entity_types": date(2026, 4, 23),
    "floruit_p1317": date(2026, 4, 28),
    "external_identifiers": date(2026, 5, 1),
    "works": date(2026, 5, 1),
    "polity_modern_countries": date(2026, 5, 3),
    "work_classes": date(2026, 5, 3),
    "non_human_classes": date(2026, 5, 5),
    "work_dates": date(2026, 5, 5),
    "place_dates": date(2026, 5, 8),
}

EXTERNAL_DATASET_VERSIONS: dict[ExternalPlatform, str] = {
    "pantheon_2": "Pantheon 2.0, person_2025_update.csv, extracted 2026-05-04",
    "cross_verified_db": "CVDB, Laouenan et al. 2022, 2,291,817 rows, extracted 2026-05-04",
    "cliopatria": "Cliopatria V3 GeoJSON, Zenodo record 13363121, downloaded 2026-04-23",
    "wikipedia": "MediaWiki Action API, 475,514 pages downloaded 2026-05-06",
}

URBAN_SETTLEMENT_MODEL = "google/gemini-3-flash-preview"

URBAN_SETTLEMENT_PROMPT = """You classify Wikidata P31 (instance-of) classes.
For each class you receive (id + English label), decide whether it denotes
an URBAN SETTLEMENT: a populated place (any size) that a researcher studying
urbanisation would count as a "city-like" location on a map.

urban_settlement = true  ->  city, town, village, hamlet, borough, suburb,
    neighborhood, metropolis, megacity, commune, municipality, comune,
    frazione, Ortsteil, human settlement, populated place, locality,
    census-designated place, unincorporated community, etc.
    Anything that is fundamentally "a place where people live as a settlement"
    including small/rural ones, and sub-city units like districts/quarters.

urban_settlement = false ->  country, sovereign state, U.S. state,
    federal subject, region, province, county, district-as-admin-division
    (when it is the whole admin unit, not a settlement), island without a
    settlement focus, building type (hospital, castle, château, station),
    street, road, bridge, square, park, monument, cemetery, natural
    feature, event, organization, company, ethnic group, geopolitical
    entity, etc. Also false for things like "former country", "historical
    state", "dissolved municipality" (dissolved => no longer a place on
    today's map) UNLESS the label clearly still refers to a settlement.

If a label is ambiguous (e.g. contains "settlement" + "administrative"),
prefer true if it is primarily a populated place, false if primarily an
admin region. When in doubt for mixed admin/settlement classes that CONTAIN
a settlement (e.g. "commune of France", "municipality of X"), return true.

Return STRICT JSON with the exact schema:
{
  "results": [
    {"id": "Q...", "urban_settlement": true, "reason": "short phrase"},
    ...
  ]
}
No prose outside the JSON. Include every id you were given, in the same order."""

WIKIPEDIA_DATES_MODEL = "google/gemini-2.5-flash-lite"

WIKIPEDIA_DATES_PROMPT = """You are an expert historian extracting biographical dates.

Given an English (or foreign-language) Wikipedia article about a person,
extract the following information ONLY when it is explicitly stated in
the article:
 - Birthdate
 - DeathDate
 - Floruit_date — the years during which the person was active in their
   primary occupation (career, public life, scholarly work, reign, etc.)
 - Dates — additional years from events the INDIVIDUAL personally
   participated in DURING THEIR LIFETIME (works they published, offices
   they held, battles they fought, awards they received, marriages,
   education, appointments, relocations, etc.).

==============================================================
CRITICAL RULES (from recent annotation feedback — read carefully)
==============================================================

A. STATED, NOT INFERRED.
   Every date you return must be present in the article text (in the
   prose, an infobox, a category, a dated section header, etc.).
   Do NOT invent a Floruit_date.start by guessing when a career
   "probably" began. Do NOT extrapolate from phrases like "in her
   teenage years", "in recent years", "since the early days", or
   future plans. If you cannot point to the exact year in the text,
   do NOT emit it.

B. SINGLE-DATE FLORUIT.
   If only ONE active-life year is mentioned, set
     Floruit_date.start = that year
     Floruit_date.end   = null
   Do NOT duplicate the same year as both start and end
   (i.e. NEVER return 1898–1898).

C. CENTURY-LEVEL FLORUIT IS ACCEPTABLE.
   If the article only places the person in a century (e.g. "18th
   century scholar", "fl. 12th century"), still emit the floruit.
   Use the canonical bucket bounds:
     18th century → start=1701, end=1800
     12th century → start=1101, end=1200
     5th century BCE → start=-500, end=-401
   AND set `precision`: "century". The `precision` field MUST be
   "century" — never label a century-level inference as "year"
   precision. The same applies to "decade" and "millennium".

D. PRESERVE THE STATED GRANULARITY.
   If the article literally says "18th century", return
   precision="century"; do NOT silently rewrite it into a year-precision
   1700–1799 range. The precision tag is what conveys the bucket.

E. STATED ANCHOR DATES COUNT.
   If the article gives stated years that anchor the individual's
   career (e.g. "played in the club's 2004 season", "served under
   President X 2010-2015"), include them — both in `Dates` and as
   evidence for Floruit_date. Do NOT return all-null when stated
   year anchors exist in the text. Stated years tied to the
   individual are extraction targets, even if the article does not
   spell out "X was active from Y to Z".

==============================================================

Return JSON with EXACTLY this shape. `precision` is ALWAYS one of the
strings "year", "decade", "century", "millennium", or null — never a
combination, never an ordinal like "15th".

{
  "Birthdate":    { "year": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "DeathDate":    { "year": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "Floruit_date": { "start": <int or null>, "end": <int or null>, "precision": "year"|"decade"|"century"|"millennium"|null },
  "Dates":        [ { "year": <int>, "label": "<what it refers to>" }, ... ]
}

Worked example — Leonardo da Vinci (year-precision):
{
  "Birthdate":    { "year": 1452, "precision": "year" },
  "DeathDate":    { "year": 1519, "precision": "year" },
  "Floruit_date": { "start": 1472, "end": 1519, "precision": "year" },
  "Dates": [
    { "year": 1472, "label": "admitted to the Florentine painters' guild" },
    { "year": 1482, "label": "moved to Milan to serve Ludovico Sforza" },
    { "year": 1503, "label": "began the Mona Lisa" },
    { "year": 1516, "label": "moved to France at the invitation of Francis I" }
  ]
}

Worked example — century-only article (rule C/D):
{
  "Birthdate":    { "year": null, "precision": null },
  "DeathDate":    { "year": null, "precision": null },
  "Floruit_date": { "start": 1701, "end": 1800, "precision": "century" },
  "Dates": []
}

Worked example — single-year activity (rule B):
{
  "Birthdate":    { "year": null, "precision": null },
  "DeathDate":    { "year": null, "precision": null },
  "Floruit_date": { "start": 1898, "end": null, "precision": "year" },
  "Dates": [
    { "year": 1898, "label": "ranked 69th in the Guangxu Wuxu imperial examination" },
    { "year": 1898, "label": "assigned as a county magistrate" }
  ]
}

INCLUSION RULES — a date belongs in `Dates` only if ALL three hold:
1. It is a SPECIFIC YEAR (4-digit integer, or negative for BCE). Never
   extract a day-of-month or month-of-year as a year. Century-only
   information (e.g. "14th century") goes into Floruit_date with
   precision="century", NOT into the Dates list.
2. The event directly involves THE INDIVIDUAL as participant, agent,
   author, honoree, or subject — not events about institutions, places,
   ancestors, descendants, colleagues, or general historical context.
3. The year falls within the individual's lifetime (between Birthdate
   and DeathDate when known; otherwise plausibly within their active
   life).

Reject (do NOT add to `Dates`) — common pitfalls:
- "commemorated on August 30" → "30" is a calendar day, NOT year 30 / -30.
- "retrieved 2020", "accessed 2024-01", "archive date 2023" → source-metadata.
- Article publication / "as of" / last-updated timestamps from the
  Wikipedia text itself.
- Events BEFORE the person was born (founding of an institution they
  later joined, prior history of a town/diocese/title).
- Events AFTER the person died (descendant deaths, posthumous
  destruction, later commemorations).
- Achievements of OTHER named people mentioned in the article.
- Awards / honors / activities of relatives, students, employer, or
  organisation that don't directly involve the individual.

Birthdate / DeathDate guards:
- A "birth year" you can't reconcile with the floruit (e.g. floruit
  starts in 1788 but you read birth=1955) is almost certainly NOT a
  birth date — most likely a citation/edit/retrieval year. Drop it.
- A "death year" in the future (after the article's apparent writing
  date) is almost certainly NOT a death date — drop it.
- Before returning null for Birthdate, scan the article for explicit
  birth cues: "born <year>", "(<year>–", "b. <year>", parenthetical
  (1942–), infobox birth fields, or non-English equivalents (né,
  geboren, 生, nacido, родился)."""


def urban_settlement_answer() -> "AIAnswer[bool]":
    return AIAnswer[bool](model=URBAN_SETTLEMENT_MODEL, prompt=URBAN_SETTLEMENT_PROMPT, answered_on=date(2026, 4, 23))


def wikipedia_dates_answer() -> "AIAnswer[str]":
    return AIAnswer[str](model=WIKIPEDIA_DATES_MODEL, prompt=WIKIPEDIA_DATES_PROMPT, answered_on=date(2026, 5, 6))


class HistoricalDate(Model):
    iso: str | None = Field(None, description="The date as an ISO string; a negative year means BCE.")
    precision: int | None = Field(None, description="Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium.")
    year: int | None = Field(None, description="The year alone, parsed out of `iso`. Negative for BCE.")


class Span(Model):
    start: int | None = Field(None, description="First year of the span. Negative for BCE.")
    end: int | None = Field(None, description="Last year of the span. NULL when only one year is known.")
    label: str | None = Field(None, description="The span as written, e.g. '1892-1964', or a single year when start equals end.")


class Coordinates(Model):
    lat: float | None = Field(None, description="Latitude in degrees.")
    lon: float | None = Field(None, description="Longitude in degrees.")


class ModernCountry(Model):
    name: str | None = Field(None, description="Modern country the historical entity maps onto, so historical data can be aggregated on today's borders.")
    iso_a3_code: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country, e.g. 'FRA'.")
    resolved_by: str | None = Field(None, description="How the mapping was resolved: 'reverse_geocode' (point-in-polygon on the coordinates), 'capital_city', 'qlever_relation', 'qlever_replaced_by', or 'unknown_legacy'.")


class Notability(Model):
    western: int | None = Field(None, description="Number of Western-language Wikipedia editions covering the individual (0-228).")
    non_western: int | None = Field(None, description="Number of non-Western-language Wikipedia editions covering the individual.")
    general: float | None = Field(None, description="Geometric mean of the two (0 to ~282). The project's canonical ranking metric: it rewards fame that crosses the Western / non-Western divide.")


class DescriptionDates(Model):
    raw: str | None = Field(None, description="Raw date substring matched in the Wikidata description before parsing. Kept so the extraction can be audited.")
    span: str | None = Field(None, description="Year span parsed out of the description, e.g. '1937-2016'.")
    birth_year: int | None = Field(None, description="Birth year parsed out of the description.")
    death_year: int | None = Field(None, description="Death year parsed out of the description.")
    floruit_year: int | None = Field(None, description="Floruit year parsed out of the description.")


class LifeExpectancyEstimate(Model):
    birthdate: str | None = Field(None, description="Birth date estimated from the death date, iterating from birth = death - 70 against the birth-bin table to avoid the survivorship bias of a death-bin lookup.")
    deathdate: str | None = Field(None, description="Death date estimated from the birth date. Never set when the estimate would fall in the last 5 years, or when the birth year would exceed 1950.")
    lookup_source: LifeExpectancyLookupSource | None = Field(None, description="Which lookup produced the estimate: the 50-year birth bin within a CVDB occupation category, or the birth bin alone as a fallback.")
    median_used: float | None = Field(None, description="Median life expectancy in years applied. The medians are estimated in-sample from Cultura individuals that have both dates at year precision — they are not a published life table.")


class Floruit(Model):
    year: int | None = Field(None, description="The single year that represents the individual's activity: the midpoint of the window, or the only known year.")
    period: Span | None = Field(None, description="The activity window. By convention an individual is active from age 30 to age 60, truncated by an early death.")
    method: FloruitMethod | None = Field(None, description="How the window was derived, as <anchor>_<evidence>: which dates were available and how they were read.")
    source: FloruitSource | None = Field(None, description="Where the dates came from: a Wikidata property, the Wikidata description, the works, the life-expectancy model, CVDB, or Wikipedia.")
    precision_class: PrecisionClass | None = Field(None, description="How precisely the window is known: to the year, the decade, or only the century. Use it to exclude vague individuals from an analysis.")
    estimated: bool | None = Field(None, description="True if the window rests on the life-expectancy model rather than on attested dates.")
    birth_used: HistoricalDate | None = Field(None, description="The birth date actually used as input, whichever source it came from.")
    death_used: HistoricalDate | None = Field(None, description="The death date actually used as input, whichever source it came from.")
    floruit_used: HistoricalDate | None = Field(None, description="The floruit date actually used as input, whichever source it came from.")
    works_period: Span | None = Field(None, description="Span of years over which the individual produced works. The year of a work is its publication date, else its inception date.")


class PolityMatch(Model):
    polity: "Polity" = Field(..., description="The historical polity the individual is attached to, with its periods and modern countries.")
    origin: CliopatriaOrigin | None = Field(None, description="Which attribute placed the individual in the polity: their birthplace, their deathplace, or their country of citizenship.")
    matched: Entity | None = Field(None, description="The city or country that produced the match.")
    method: CliopatriaMethod | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
    floruit_year: int | None = Field(None, description="Floruit year used to test the overlap with the polity's periods.")
    floruit_period: Span | None = Field(None, description="Activity window used for the overlap test.")
    overlap_years: int | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")


class PolityMatchRoutes(Model):
    floruit_year: int | None = Field(None, description="Floruit year used when testing the candidate matches.")
    polygon_birthplace: bool | None = Field(None, description="True if the birth place falls inside some polity polygon.")
    polygon_deathplace: bool | None = Field(None, description="True if the death place falls inside some polity polygon.")
    polygon_country_of_citizenship: bool | None = Field(None, description="True if the country of citizenship falls inside some polity polygon.")
    url_birthplace: bool | None = Field(None, description="True if the birth place matched a polity by Wikipedia URL.")
    url_deathplace: bool | None = Field(None, description="True if the death place matched a polity by Wikipedia URL.")
    url_country_of_citizenship: bool | None = Field(None, description="True if the country of citizenship matched a polity by Wikipedia URL.")


class WikipediaArticle(Model):
    site: Wikidata[str] | None = None
    title: Wikidata[str] | None = None
    url: Wikidata[str] | None = None


class ExternalIdentifier(Model):
    type: "IdentifierType" = Field(..., description="The external database the identifier belongs to, and the Wikidata property carrying it.")
    value: Wikidata[str] | None = None
    url: Wikidata[str] | None = None


class CvdbOntology(Model):
    level1: External[Level1Occupation] | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing this occupation, not an AI classification. 'Missing' means unclassified.")
    level2: External[str] | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
    level3: External[str] | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
    n_votes: Derived[int] | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")


class Individual(Entity):
    birth: Wikidata[HistoricalDate] | None = None
    death: Wikidata[HistoricalDate] | None = None
    floruit_declared: Wikidata[HistoricalDate] | None = None
    birthplace: "Place | None" = Field(None, description="City of birth, with its coordinates and modern country. Wikidata P19 'place of birth'.")
    deathplace: "Place | None" = Field(None, description="City of death, with its coordinates and modern country. Wikidata P20 'place of death'.")
    citizenships: tuple["Citizenship", ...] = Field((), description="Countries of citizenship, in Wikidata order, historical entities included. Wikidata P27 'country of citizenship'.")
    occupations: tuple[Entity, ...] = Field((), description="Occupations, in Wikidata order; each joins the `Occupation` table by qid. Wikidata P106 'occupation'.")
    writing_languages: tuple["WritingLanguage", ...] = Field((), description="Languages the individual wrote in. Wikidata P6886 'writing language'.")
    gender: Entity | None = Field(None, description="Gender item, e.g. Q6581097 for male. Free vocabulary: 48 distinct values in the data, a few of them unresolved. Wikidata P21 'sex or gender'.")
    wikipedia_articles: tuple[WikipediaArticle, ...] = Field((), description="Wikipedia articles about the individual, one per language edition. These are what the notability scores count.")
    identifiers: tuple[ExternalIdentifier, ...] = Field((), description="The individual's records in external databases.")
    floruit: Floruit | None = Field(None, description="Resolved activity window. This is what dating an individual relies on, since birth and death are often missing.")
    polities: tuple[PolityMatch, ...] = Field((), description="Historical polities the individual overlaps, one entry per polity.")
    polity_match_routes: PolityMatchRoutes | None = Field(None, description="Which match routes were available, so the coverage of `polities` can be audited.")
    notability: Derived[Notability] | None = Field(None, description="Wikipedia-coverage scores, counted over `wikipedia_articles`.")
    dates_in_description: Derived[DescriptionDates] | None = Field(None, description="Years recovered by regex from the Wikidata description, for individuals Wikidata leaves undated.")
    number_of_works: Derived[int] | None = Field(None, description="Number of works credited to the individual. Counted over `Work`.")
    number_of_identifiers: Derived[int] | None = Field(None, description="Number of external-database identifiers. Counted over `identifiers`.")
    number_of_wikipedia_articles: Derived[int] | None = Field(None, description="Number of Wikipedia articles across all languages. Counted over `wikipedia_articles`.")
    birth_from_cv: External[str] | None = Field(None, description="Birth date from the cross-verified database, used where Wikidata has none.")
    death_from_cv: External[str] | None = Field(None, description="Death date from the cross-verified database, used where Wikidata has none.")
    birth_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Birth year read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    death_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Death year read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    floruit_from_wikipedia: AIAnswer[str] | None = Field(default_factory=wikipedia_dates_answer, description="Floruit read out of the Wikipedia article by a language model. Model and prompt travel with the value.")
    life_expectancy_estimate: Derived[LifeExpectancyEstimate] | None = Field(None, description="Dates imputed from a median life expectancy when only one of the two is known.")
    in_pantheon_2: External[bool] | None = Field(None, description="True if the individual appears in the Pantheon 2.0 dataset.")
    in_cross_verified_db: External[bool] | None = Field(None, description="True if the individual appears in the cross-verified database.")
    non_human: Derived[bool] | None = Field(None, description="True if the row is not actually a human (872 rows). Set from the Wikidata classes fictional character Q95074, mythical character Q4271324, deity Q178885, fictional human Q15632617, human biblical figure Q21070568, legendary creature Q24334685. Filter these out.")


class Work(Entity):
    creator: Entity = Field(..., description="The individual credited for the work; joins `Individual`.")
    role: Wikidata[Relationship] | None = None
    instance_of: tuple[Entity, ...] = Field((), description="Classes of the work, e.g. 'painting', 'film'. Wikidata P31 'instance of'.")
    inception: Wikidata[HistoricalDate] | None = None
    publication: Wikidata[HistoricalDate] | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        if isinstance(value, dict) and isinstance(value.get("value"), str):
            return value | {"value": RELATIONSHIP_FROM_PROPERTY.get(value["value"], value["value"])}
        return value


class Occupation(Entity):
    meta_occupation: Derived[MetaOccupation] | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Every occupation reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
    ontology: CvdbOntology | None = Field(None, description="Three-tier occupation ontology taken from CVDB.")
    number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals holding this occupation. Counted over `Individual`.")


class Citizenship(Entity):
    instance_of: tuple[Entity, ...] = Field((), description="Classes of the entity, e.g. 'sovereign state', 'former country'. Wikidata P31 'instance of'.")
    coordinates: Wikidata[Coordinates] | None = None
    wikipedia_url: Wikidata[str] | None = None
    modern_country: Derived[ModernCountry] | None = Field(None, description="Modern country this historical entity maps onto.")
    inception: Wikidata[HistoricalDate] | None = None
    dissolved: Wikidata[HistoricalDate] | None = None
    number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals holding this country as citizenship. Counted over `Individual`.")


class Place(Entity):
    coordinates: Wikidata[Coordinates] | None = None
    country: Entity | None = Field(None, description="Country the place belongs to according to Wikidata. Wikidata P17 'country'.")
    country_wikipedia_url: Wikidata[str] | None = None
    modern_country: Derived[ModernCountry] | None = Field(None, description="Modern country the place maps onto.")
    entity_types: tuple[Entity, ...] = Field((), description="Classes of the place, e.g. 'village', 'city in the United States'. Wikidata P31 'instance of'.")
    is_urban_settlement: AIAnswer[bool] | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
    inception: Wikidata[HistoricalDate] | None = None
    dissolution: Wikidata[HistoricalDate] | None = None


class WritingLanguage(Entity):
    number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals who wrote in this language. Counted over `Individual`.")


class IdentifierType(Model):
    property: Property = Field(..., description="Wikidata property that carries this identifier, e.g. P214 for VIAF.")
    issuer: Entity | None = Field(None, description="Organization that issues the identifiers, e.g. a national library. Wikidata P1629 'subject item of this property'.")
    issuer_country: Entity | None = Field(None, description="Country of the issuer. Use it to weigh how national a database's coverage is. Wikidata P17 'country'.")
    inception: Wikidata[HistoricalDate] | None = None
    number_of_records: Wikidata[str] | None = None
    website: Wikidata[str] | None = None
    number_of_individuals: Derived[int] | None = Field(None, description="Number of Cultura individuals carrying an identifier from this database.")


class PolityPeriod(Model):
    id: int = Field(..., description="Identifier of the period.")
    period: Span | None = Field(None, description="Years the polity held this territory.")
    area: float | None = Field(None, description="Area of the territory in square kilometres.")
    geometry: str | None = Field(None, description="Territory as a GeoJSON polygon. This is what decides whether a birth or death place falls inside the polity.")


class PolityModernCountry(Model):
    country: Entity | None = Field(None, description="Modern country the polity overlaps. Wikidata rdfs:label.")
    iso_a3_code: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of that country. Wikidata P298.")
    continent: Wikidata[str] | None = None
    sources: Derived[str] | None = Field(None, description="Wikidata property paths that produced the mapping, pipe-joined: P17, P36/P17, P1366/P17, P131/P17.")


class Polity(Model):
    id: int = Field(..., description="Polity identifier, from the Cliopatria dataset.")
    name: External[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
    type: External[PolityType] | None = Field(None, description="POLITY for a state, RELATION for a dependency link between two polities.")
    wikipedia_url: External[str] | None = Field(None, description="English Wikipedia URL, used to match Wikidata places and countries.")
    wikidata: Entity | None = Field(None, description="The Wikidata item for the polity, resolved from its Wikipedia URL. NULL where no match was found.")
    periods: tuple[PolityPeriod, ...] = Field((), description="Territorial periods of the polity, one per change.")
    modern_countries: tuple[PolityModernCountry, ...] = Field((), description="Modern countries the polity's territory overlaps.")
    number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals matched to this polity. Counted over `Individual.polities`.")


TABLES: dict[str, type[Model]] = {
    "individuals": Individual,
    "works": Work,
    "occupations": Occupation,
}

LEGACY_COLUMNS: dict[str, str] = {
    "individuals.wikidata_id": "Individual.qid",
    "individuals.name_en": "Individual.label_en",
    "individuals.description_en": "Individual.description_en",
    "individuals.birthdate": "Individual.birth.value.iso",
    "individuals.birthdate_precision": "Individual.birth.value.precision",
    "individuals.deathdate": "Individual.death.value.iso",
    "individuals.deathdate_precision": "Individual.death.value.precision",
    "individuals.country_of_citizenship_en": "Individual.citizenships[].label_en",
    "individuals.birthcity_en": "Individual.birthplace.label_en",
    "individuals.deathcity_en": "Individual.deathplace.label_en",
    "individuals.occupations_en": "Individual.occupations[].label_en",
    "individuals.wikimedia_links_count": "Individual.number_of_wikipedia_articles",
    "individuals.gender": "Individual.gender.label_en",
    "individuals.identifiers_count": "Individual.number_of_identifiers",
    "individuals.writing_language_name_en": "Individual.writing_languages[].label_en",
    "individuals.number_of_works": "Individual.number_of_works",
    "individuals.floruit_date": "Individual.floruit_declared.value.iso",
    "individuals.floruit_precision": "Individual.floruit_declared.value.precision",
    "individuals.floruit_year": "Individual.floruit.year",
    "individuals.dates_in_description": "Individual.dates_in_description.value.span",
    "individuals.birthdate_in_description": "Individual.dates_in_description.value.birth_year",
    "individuals.deathdate_in_description": "Individual.dates_in_description.value.death_year",
    "individuals.floruit_year_in_description": "Individual.dates_in_description.value.floruit_year",
    "individuals.date_description": "Individual.dates_in_description.value.raw",
    "individuals.pantheon_2_db": "Individual.in_pantheon_2",
    "individuals.cross_verified_db": "Individual.in_cross_verified_db",
    "individuals.non_human": "Individual.non_human",
    "individuals.works_period": "Individual.floruit.works_period.label",
    "individuals.notability_western": "Individual.notability.value.western",
    "individuals.notability_non_western": "Individual.notability.value.non_western",
    "individuals.notability_general": "Individual.notability.value.general",
    "individuals.birthdate_from_CV": "Individual.birth_from_cv",
    "individuals.deathdate_from_CV": "Individual.death_from_cv",
    "individuals.birthdate_from_life_expectancy": "Individual.life_expectancy_estimate.value.birthdate",
    "individuals.deathdate_from_life_expectancy": "Individual.life_expectancy_estimate.value.deathdate",
    "individuals.life_expectancy_lookup_source": "Individual.life_expectancy_estimate.value.lookup_source",
    "individuals.life_expectancy_median_used": "Individual.life_expectancy_estimate.value.median_used",
    "individuals.birthdate_from_wikipedia": "Individual.birth_from_wikipedia",
    "individuals.deathdate_from_wikipedia": "Individual.death_from_wikipedia",
    "individuals.floruit_from_wikipedia": "Individual.floruit_from_wikipedia",
    "individuals.is_artist": "dropped: derive from Individual.occupations[] joined to Occupation.meta_occupation",
    "individuals.is_scientist": "dropped: derive from Individual.occupations[] joined to Occupation.meta_occupation",
    "individuals_keys.wikidata_id": "Individual.qid",
    "individuals_keys.birthcity_id": "Individual.birthplace.qid",
    "individuals_keys.deathcity_id": "Individual.deathplace.qid",
    "individuals_keys.country_of_citizenship_ids": "Individual.citizenships[].qid",
    "individuals_keys.occupations_ids": "Individual.occupations[].qid",
    "individuals_keys.gender_id": "Individual.gender.qid",
    "individuals_keys.writing_language_ids": "Individual.writing_languages[].qid",
    "individuals_floruit_period.wikidata_id": "Individual.qid",
    "individuals_floruit_period.name_en": "Individual.label_en",
    "individuals_floruit_period.birthdate": "Individual.floruit.birth_used.iso",
    "individuals_floruit_period.birthdate_precision": "Individual.floruit.birth_used.precision",
    "individuals_floruit_period.birth_year": "Individual.floruit.birth_used.year",
    "individuals_floruit_period.deathdate": "Individual.floruit.death_used.iso",
    "individuals_floruit_period.deathdate_precision": "Individual.floruit.death_used.precision",
    "individuals_floruit_period.death_year": "Individual.floruit.death_used.year",
    "individuals_floruit_period.floruit_date": "Individual.floruit.floruit_used.iso",
    "individuals_floruit_period.floruit_precision": "Individual.floruit.floruit_used.precision",
    "individuals_floruit_period.floruit_year": "Individual.floruit.year",
    "individuals_floruit_period.floruit_period": "Individual.floruit.period.label",
    "individuals_floruit_period.floruit_period_start": "Individual.floruit.period.start",
    "individuals_floruit_period.floruit_period_end": "Individual.floruit.period.end",
    "individuals_floruit_period.method": "Individual.floruit.method",
    "individuals_floruit_period.source": "Individual.floruit.source",
    "individuals_floruit_period.precision_class": "Individual.floruit.precision_class",
    "individuals_floruit_period.estimated": "Individual.floruit.estimated",
    "individuals_floruit_period.works_period": "Individual.floruit.works_period.label",
    "individuals_cliopatria.wikidata_id": "Individual.qid",
    "individuals_cliopatria.name_en": "Individual.label_en",
    "individuals_cliopatria.polity_id": "Individual.polities[].polity.id",
    "individuals_cliopatria.polity_name": "Individual.polities[].polity.name",
    "individuals_cliopatria.origin": "Individual.polities[].origin",
    "individuals_cliopatria.matched_name": "Individual.polities[].matched.label_en",
    "individuals_cliopatria.matched_wikidata_id": "Individual.polities[].matched.qid",
    "individuals_cliopatria.method": "Individual.polities[].method",
    "individuals_cliopatria.floruit_year": "Individual.polities[].floruit_year",
    "individuals_cliopatria.floruit_period_start": "Individual.polities[].floruit_period.start",
    "individuals_cliopatria.floruit_period_end": "Individual.polities[].floruit_period.end",
    "individuals_cliopatria.overlap_years": "Individual.polities[].overlap_years",
    "individuals_cliopatria_potential.wikidata_id": "Individual.qid",
    "individuals_cliopatria_potential.floruit_year": "Individual.polity_match_routes.floruit_year",
    "individuals_cliopatria_potential.polygon_deathplace": "Individual.polity_match_routes.polygon_deathplace",
    "individuals_cliopatria_potential.polygon_birthplace": "Individual.polity_match_routes.polygon_birthplace",
    "individuals_cliopatria_potential.polygon_country_of_citizenship": "Individual.polity_match_routes.polygon_country_of_citizenship",
    "individuals_cliopatria_potential.url_country_of_citizenship": "Individual.polity_match_routes.url_country_of_citizenship",
    "individuals_cliopatria_potential.url_deathplace": "Individual.polity_match_routes.url_deathplace",
    "individuals_cliopatria_potential.url_birthplace": "Individual.polity_match_routes.url_birthplace",
    "works.id": "dropped: surrogate key, no longer needed once a work is an Entity",
    "works.individual_id": "Work.creator.qid",
    "works.individual_name": "Work.creator.label_en",
    "works.work_id": "Work.qid",
    "works.work_name": "Work.label_en",
    "works.relationship": "Work.role.value",
    "works.instance_of": "Work.instance_of[].qid",
    "works.instance_of_en": "Work.instance_of[].label_en",
    "works.inception_date": "Work.inception.value.iso",
    "works.inception_precision": "Work.inception.value.precision",
    "works.publication_date": "Work.publication.value.iso",
    "works.publication_precision": "Work.publication.value.precision",
    "occupations.id": "Occupation.qid",
    "occupations.name_en": "Occupation.label_en",
    "occupations.meta_occupation": "Occupation.meta_occupation",
    "occupations.count": "Occupation.number_of_individuals",
    "occupations.description_en": "Occupation.description_en",
    "occupations.level1_main_occ": "Occupation.ontology.level1",
    "occupations.level2_main_occ": "Occupation.ontology.level2",
    "occupations.level3_main_occ": "Occupation.ontology.level3",
    "occupations.ontology_n_votes": "Occupation.ontology.n_votes",
    "country_of_citizenship.wikidata_id": "Individual.citizenships[].qid",
    "country_of_citizenship.name_en": "Individual.citizenships[].label_en",
    "country_of_citizenship.count": "Individual.citizenships[].number_of_individuals",
    "country_of_citizenship.description_en": "Individual.citizenships[].description_en",
    "country_of_citizenship.instance_of": "Individual.citizenships[].instance_of[].label_en",
    "country_of_citizenship.en_wikipedia_url": "Individual.citizenships[].wikipedia_url",
    "country_of_citizenship.lat": "Individual.citizenships[].coordinates.value.lat",
    "country_of_citizenship.lon": "Individual.citizenships[].coordinates.value.lon",
    "country_of_citizenship.iso_country_name": "Individual.citizenships[].modern_country.value.name",
    "country_of_citizenship.iso_a3_code": "Individual.citizenships[].modern_country.value.iso_a3_code",
    "country_of_citizenship.iso_modern_country_origin": "Individual.citizenships[].modern_country.value.resolved_by",
    "country_of_citizenship.instance_qids": "Individual.citizenships[].instance_of[].qid",
    "country_of_citizenship.instance_labels": "Individual.citizenships[].instance_of[].label_en",
    "country_of_citizenship.inception": "Individual.citizenships[].inception.value.iso",
    "country_of_citizenship.dissolved": "Individual.citizenships[].dissolved.value.iso",
    "places.id": "Individual.birthplace/deathplace.qid",
    "places.name_en": "Individual.birthplace/deathplace.label_en",
    "places.lat": "Individual.birthplace/deathplace.coordinates.value.lat",
    "places.lon": "Individual.birthplace/deathplace.coordinates.value.lon",
    "places.original_country_name": "Individual.birthplace/deathplace.country.label_en",
    "places.original_country_name_id": "Individual.birthplace/deathplace.country.qid",
    "places.en_wikipedia_url_original_country_name": "Individual.birthplace/deathplace.country_wikipedia_url",
    "places.iso_country_name": "Individual.birthplace/deathplace.modern_country.value.name",
    "places.iso_a3_code": "Individual.birthplace/deathplace.modern_country.value.iso_a3_code",
    "places.entity_type": "Individual.birthplace/deathplace.entity_types[].label_en",
    "places.entity_type_ids": "Individual.birthplace/deathplace.entity_types[].qid",
    "places.is_urban_settlement": "Individual.birthplace/deathplace.is_urban_settlement",
    "places.inception_date": "Individual.birthplace/deathplace.inception.value.iso",
    "places.inception_precision": "Individual.birthplace/deathplace.inception.value.precision",
    "places.dissolution_date": "Individual.birthplace/deathplace.dissolution.value.iso",
    "places.dissolution_precision": "Individual.birthplace/deathplace.dissolution.value.precision",
    "writing_languages.id": "Individual.writing_languages[].qid",
    "writing_languages.name": "Individual.writing_languages[].label_en",
    "writing_languages.count": "Individual.writing_languages[].number_of_individuals",
    "individual_writing_languages.wikidata_id": "Individual.qid",
    "individual_writing_languages.individual_name": "Individual.label_en",
    "individual_writing_languages.language_id": "Individual.writing_languages[].qid",
    "individual_writing_languages.language_name": "Individual.writing_languages[].label_en",
    "identifiers.wikidata_id": "Individual.qid",
    "identifiers.individual_name": "Individual.label_en",
    "identifiers.property_id": "Individual.identifiers[].type.property.id",
    "identifiers.identifier_name": "Individual.identifiers[].type.property.name",
    "identifiers.value": "Individual.identifiers[].value",
    "identifiers.url": "Individual.identifiers[].url",
    "identifier_types.property_id": "Individual.identifiers[].type.property.id",
    "identifier_types.name_en": "Individual.identifiers[].type.property.name",
    "identifier_types.count": "Individual.identifiers[].type.number_of_individuals",
    "identifier_types.description": "Individual.identifiers[].type.property.definition",
    "identifier_types.issuer_name": "Individual.identifiers[].type.issuer.label_en",
    "identifier_types.issuer_id": "Individual.identifiers[].type.issuer.qid",
    "identifier_types.issuer_instance": "Individual.identifiers[].type.issuer.description_en",
    "identifier_types.country_name": "Individual.identifiers[].type.issuer_country.label_en",
    "identifier_types.country_id": "Individual.identifiers[].type.issuer_country.qid",
    "identifier_types.inception": "Individual.identifiers[].type.inception.value.iso",
    "identifier_types.database_records": "Individual.identifiers[].type.number_of_records",
    "identifier_types.website": "Individual.identifiers[].type.website",
    "wikimedia_links.id": "dropped: surrogate key, no longer needed once articles are nested",
    "wikimedia_links.wikidata_id": "Individual.qid",
    "wikimedia_links.individual_name": "Individual.label_en",
    "wikimedia_links.site": "Individual.wikipedia_articles[].site",
    "wikimedia_links.title": "Individual.wikipedia_articles[].title",
    "wikimedia_links.url": "Individual.wikipedia_articles[].url",
    "polities_cliopatria.id": "Individual.polities[].polity.id",
    "polities_cliopatria.name": "Individual.polities[].polity.name",
    "polities_cliopatria.type": "Individual.polities[].polity.type",
    "polities_cliopatria.wikipedia_url": "Individual.polities[].polity.wikipedia_url",
    "polities_cliopatria.wikidata_id": "Individual.polities[].polity.wikidata.qid",
    "polities_cliopatria.number_individuals": "Individual.polities[].polity.number_of_individuals",
    "polities_periods_cliopatria.id": "Individual.polities[].polity.periods[].id",
    "polities_periods_cliopatria.polity_id": "Individual.polities[].polity.id",
    "polities_periods_cliopatria.polity_name": "Individual.polities[].polity.name",
    "polities_periods_cliopatria.from_year": "Individual.polities[].polity.periods[].period.start",
    "polities_periods_cliopatria.to_year": "Individual.polities[].polity.periods[].period.end",
    "polities_periods_cliopatria.area": "Individual.polities[].polity.periods[].area",
    "polities_periods_cliopatria.geometry": "Individual.polities[].polity.periods[].geometry",
    "polities_modern_countries_cliopatria.polity_id": "Individual.polities[].polity.id",
    "polities_modern_countries_cliopatria.polity_name": "Individual.polities[].polity.name",
    "polities_modern_countries_cliopatria.country_qid": "Individual.polities[].polity.modern_countries[].country.qid",
    "polities_modern_countries_cliopatria.country_name": "Individual.polities[].polity.modern_countries[].country.label_en",
    "polities_modern_countries_cliopatria.iso_a3_code": "Individual.polities[].polity.modern_countries[].iso_a3_code",
    "polities_modern_countries_cliopatria.continent": "Individual.polities[].polity.modern_countries[].continent",
    "polities_modern_countries_cliopatria.sources": "Individual.polities[].polity.modern_countries[].sources",
    "wikidata_properties_definition.property_id": "Property.id",
    "wikidata_properties_definition.property_name": "Property.name",
    "wikidata_properties_definition.description": "Property.definition",
    "wikidata_properties_definition.table_name": "dropped: PROPERTIES is declared in code, so the mapping is the field annotation itself",
    "wikidata_properties_definition.column_name": "dropped: as above",
}


def demo() -> None:
    assert len(LEGACY_COLUMNS) == 196, f"the live database has 196 columns, {len(LEGACY_COLUMNS)} are mapped"
    assert len(PROPERTIES) == 35, "26 named properties plus the 9 credit properties"

    einstein = Individual(
        qid="Q937",
        label_en="Albert Einstein",
        description_en="German-born theoretical physicist",
        date_of_extraction=date(2026, 2, 13),
        birth=Wikidata[HistoricalDate](
            property=P569,
            value=HistoricalDate(iso="1879-03-14", precision=11, year=1879),
            date_of_extraction=date(2026, 2, 13),
        ),
        occupations=(
            Entity(qid="Q169470", label_en="physicist", date_of_extraction=date(2026, 2, 13)),
            Entity(qid="Q4964182", label_en="philosopher", date_of_extraction=date(2026, 2, 13)),
        ),
        notability=Derived[Notability](
            value=Notability(western=228, non_western=54, general=110.9),
            derived_from=("Individual.wikipedia_articles",),
            rule="geometric mean of the Western and non-Western Wikipedia edition counts",
            computed_on=date(2026, 5, 6),
        ),
    )
    assert einstein.birth.value.year == 1879
    assert einstein.birth.property.definition == "date on which the subject was born"
    assert einstein.birth.date_of_extraction == date(2026, 2, 13)
    assert len(einstein.occupations) == 2
    assert einstein.death is None

    assert einstein.birth_from_wikipedia.model == WIKIPEDIA_DATES_MODEL
    assert "expert historian" in einstein.birth_from_wikipedia.prompt

    mona_lisa = Work(
        qid="Q12418",
        label_en="Mona Lisa",
        date_of_extraction=date(2026, 5, 1),
        creator=Entity(qid="Q762", label_en="Leonardo da Vinci", date_of_extraction=date(2026, 5, 1)),
        role={"property": CREDIT_PROPERTIES["creator"], "value": "P170", "date_of_extraction": "2026-05-01"},
    )
    assert mona_lisa.role.value == "creator", "a raw property id is normalized to its role label"

    for model, kwargs, why in [
        (Wikidata[str], {"property": P569, "value": "1879"}, "a Wikidata value must carry an extraction date"),
        (Entity, {"qid": "Q937"}, "an entity must carry an extraction date"),
        (Entity, {"qid": "not-a-qid", "date_of_extraction": date(2026, 2, 13)}, "a qid must look like a qid"),
        (AIAnswer[str], {"value": "1879"}, "an AI value must carry its model and prompt"),
        (Derived[int], {"value": 1, "rule": "counted"}, "a derived value must name its inputs"),
        (Individual, {"qid": "Q937", "date_of_extraction": date(2026, 2, 13), "unknown_field": 1}, "unknown fields are rejected"),
    ]:
        try:
            model(**kwargs)
        except Exception:
            pass
        else:
            raise AssertionError(f"accepted what it should reject: {why}")

    dropped = sum(1 for target in LEGACY_COLUMNS.values() if target.startswith("dropped"))
    print(f"OK — {len(TABLES)} models (was 18 tables), {len(LEGACY_COLUMNS)} legacy columns mapped, {dropped} deliberately dropped")


if __name__ == "__main__":
    demo()
