import json
from datetime import date
from pathlib import Path
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

HERE = Path(__file__).parent

T = TypeVar("T")

QID = Annotated[str, StringConstraints(pattern=r"^Q\d+$")]

ExternalPlatform = Literal["pantheon_2", "cross_verified_db", "cliopatria", "wikipedia"]

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

LifeExpectancyLookupSource = Literal[
    "birth_bin",
    "category+birth_bin:Leadership",
    "category+birth_bin:Culture",
    "category+birth_bin:Sports/Games",
    "category+birth_bin:Discovery/Science",
    "category+birth_bin:Other",
]

MetaOccupation = Literal["scientist", "artist"]

Level1Occupation = Literal["Leadership", "Culture", "Discovery/Science", "Sports/Games", "Other", "Missing"]

PolityType = Literal["POLITY", "RELATION"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Wikidata(Model, Generic[T]):
    class Property(Model):
        id: str = Field(..., description="Wikidata property id, e.g. 'P569'. Non-property sources keep their RDF term, e.g. 'rdfs:label'.")
        name: str = Field(..., description="Label of the property, e.g. 'date of birth'.")
        definition: str = Field(..., description="What the property means, e.g. 'date on which the subject was born'. This is why a Wikidata field carries no separate description.")

    class Entity(Model):
        qid: QID | None = Field(None, description="Wikidata item id, e.g. 'Q937'. NULL when the item was named in a source but never resolved to Wikidata.")
        label_en: str | None = Field(None, description="English label of the item. Wikidata rdfs:label.")
        description_en: str | None = Field(None, description="English one-line description of the item. Wikidata schema:description.")
        date_of_extraction: date = Field(..., description="Day the item was read from Wikidata.")

    class HistoricalDate(Model):
        iso: str | None = Field(None, description="The date as an ISO string; a negative year means BCE.")
        precision: int | None = Field(None, description="Wikidata precision code: 11=day, 10=month, 9=year, 8=decade, 7=century, 6=millennium.")
        year: int | None = Field(None, description="The year alone, parsed out of `iso`. Negative for BCE.")

    class Coordinates(Model):
        lat: float | None = Field(None, description="Latitude in degrees.")
        lon: float | None = Field(None, description="Longitude in degrees.")

    property: Property = Field(..., description="Property the value was read from.")
    value: T | None = Field(None, description="The value itself, exactly as read from Wikidata.")
    date_of_extraction: date = Field(..., description="Day the value was pulled from Wikidata. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")


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


PROPERTY_DATA: dict[str, dict[str, str]] = json.loads((HERE / "properties.json").read_text())

PROPERTIES: dict[str, Wikidata.Property] = {pid: Wikidata.Property(id=pid, name=p["name"], definition=p["definition"]) for pid, p in PROPERTY_DATA.items()}

ROLE_FROM_PROPERTY: dict[str, str] = {pid: p["credit_role"] for pid, p in PROPERTY_DATA.items() if "credit_role" in p}

SOURCES: dict[str, dict[str, str]] = json.loads((HERE / "sources.json").read_text())


def urban_settlement_answer() -> "AIAnswer[bool]":
    return AIAnswer[bool](model="google/gemini-3-flash-preview", prompt=(HERE / "prompts/urban_settlement.txt").read_text().strip(), answered_on=date(2026, 4, 23))


def wikipedia_dates_answer() -> "AIAnswer[str]":
    return AIAnswer[str](model="google/gemini-2.5-flash-lite", prompt=(HERE / "prompts/wikipedia_dates.txt").read_text().strip(), answered_on=date(2026, 5, 6))


class Individual(Wikidata.Entity):
    class Span(Model):
        start: int | None = Field(None, description="First year of the span. Negative for BCE.")
        end: int | None = Field(None, description="Last year of the span. NULL when only one year is known.")
        label: str | None = Field(None, description="The span as written, e.g. '1892-1964', or a single year when start equals end.")

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
        period: "Individual.Span | None" = Field(None, description="The activity window. By convention an individual is active from age 30 to age 60, truncated by an early death.")
        method: FloruitMethod | None = Field(None, description="How the window was derived, as <anchor>_<evidence>: which dates were available and how they were read.")
        source: FloruitSource | None = Field(None, description="Where the dates came from: a Wikidata property, the Wikidata description, the works, the life-expectancy model, CVDB, or Wikipedia.")
        precision_class: PrecisionClass | None = Field(None, description="How precisely the window is known: to the year, the decade, or only the century. Use it to exclude vague individuals from an analysis.")
        estimated: bool | None = Field(None, description="True if the window rests on the life-expectancy model rather than on attested dates.")
        birth_used: Wikidata.HistoricalDate | None = Field(None, description="The birth date actually used as input, whichever source it came from.")
        death_used: Wikidata.HistoricalDate | None = Field(None, description="The death date actually used as input, whichever source it came from.")
        floruit_used: Wikidata.HistoricalDate | None = Field(None, description="The floruit date actually used as input, whichever source it came from.")
        works_period: "Individual.Span | None" = Field(None, description="Span of years over which the individual produced works. The year of a work is its publication date, else its inception date.")

    class Place(Wikidata.Entity):
        coordinates: Wikidata[Wikidata.Coordinates] | None = None
        country: Wikidata.Entity | None = Field(None, description="Country the place belongs to according to Wikidata. Wikidata P17 'country'.")
        country_wikipedia_url: Wikidata[str] | None = None
        modern_country: "Derived[Individual.ModernCountry] | None" = Field(None, description="Modern country the place maps onto.")
        entity_types: tuple[Wikidata.Entity, ...] = Field((), description="Classes of the place, e.g. 'village', 'city in the United States'. Wikidata P31 'instance of'.")
        is_urban_settlement: AIAnswer[bool] | None = Field(default_factory=urban_settlement_answer, description="True if the place counts as a populated settlement rather than an administrative region or a building. A language model classified the Wikidata classes, not the places; a place is urban when any of its `entity_types` is in the urban set.")
        inception: Wikidata[Wikidata.HistoricalDate] | None = None
        dissolution: Wikidata[Wikidata.HistoricalDate] | None = None

    class Citizenship(Wikidata.Entity):
        instance_of: tuple[Wikidata.Entity, ...] = Field((), description="Classes of the entity, e.g. 'sovereign state', 'former country'. Wikidata P31 'instance of'.")
        coordinates: Wikidata[Wikidata.Coordinates] | None = None
        wikipedia_url: Wikidata[str] | None = None
        modern_country: "Derived[Individual.ModernCountry] | None" = Field(None, description="Modern country this historical entity maps onto.")
        inception: Wikidata[Wikidata.HistoricalDate] | None = None
        dissolved: Wikidata[Wikidata.HistoricalDate] | None = None
        number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals holding this country as citizenship. Counted over `Individual`.")

    class WritingLanguage(Wikidata.Entity):
        number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals who wrote in this language. Counted over `Individual`.")

    class CvdbOntology(Model):
        level1: External[Level1Occupation] | None = Field(None, description="Top tier of the CVDB occupation ontology — the grouping used in the paper's figures. The modal CVDB label over the individuals sharing this occupation, not an AI classification. 'Missing' means unclassified.")
        level2: External[str] | None = Field(None, description="Mid tier, e.g. 'Culture-core', 'Academia', 'Politics', 'Religious', 'Military', 'Nobility'. Modal label, as above.")
        level3: External[str] | None = Field(None, description="Fine tier, e.g. 'politician', 'writer', 'actor', 'painter', 'historian'. Modal label, as above.")
        n_votes: Derived[int] | None = Field(None, description="Number of CVDB individuals that voted for the modal label. Low values mark a weakly supported classification.")

    class Occupation(Wikidata.Entity):
        meta_occupation: Derived[MetaOccupation] | None = Field(None, description="Coarse split into scientist or artist, NULL for everything that is neither. Every occupation reachable from Q901 'scientist' or Q483501 'artist' through the P279 subclass closure.")
        ontology: "Individual.CvdbOntology | None" = Field(None, description="Three-tier occupation ontology taken from CVDB.")
        number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals holding this occupation. Counted over `Individual`.")

    class IdentifierType(Model):
        property: Wikidata.Property = Field(..., description="Wikidata property that carries this identifier, e.g. P214 for VIAF.")
        issuer: Wikidata.Entity | None = Field(None, description="Organization that issues the identifiers, e.g. a national library. Wikidata P1629 'subject item of this property'.")
        issuer_country: Wikidata.Entity | None = Field(None, description="Country of the issuer. Use it to weigh how national a database's coverage is. Wikidata P17 'country'.")
        inception: Wikidata[Wikidata.HistoricalDate] | None = None
        number_of_records: Wikidata[str] | None = None
        website: Wikidata[str] | None = None
        number_of_individuals: Derived[int] | None = Field(None, description="Number of Cultura individuals carrying an identifier from this database.")

    class ExternalIdentifier(Model):
        type: "Individual.IdentifierType" = Field(..., description="The external database the identifier belongs to, and the Wikidata property carrying it.")
        value: Wikidata[str] | None = None
        url: Wikidata[str] | None = None

    class WikipediaArticle(Model):
        site: Wikidata[str] | None = None
        title: Wikidata[str] | None = None
        url: Wikidata[str] | None = None

    class PolityPeriod(Model):
        id: int = Field(..., description="Identifier of the period.")
        period: "Individual.Span | None" = Field(None, description="Years the polity held this territory.")
        area: float | None = Field(None, description="Area of the territory in square kilometres.")
        geometry: str | None = Field(None, description="Territory as a GeoJSON polygon. This is what decides whether a birth or death place falls inside the polity.")

    class PolityModernCountry(Model):
        country: Wikidata.Entity | None = Field(None, description="Modern country the polity overlaps. Wikidata rdfs:label.")
        iso_a3_code: Derived[str] | None = Field(None, description="ISO 3166-1 alpha-3 code of that country. Wikidata P298.")
        continent: Wikidata[str] | None = None
        sources: Derived[str] | None = Field(None, description="Wikidata property paths that produced the mapping, pipe-joined: P17, P36/P17, P1366/P17, P131/P17.")

    class Polity(Model):
        id: int = Field(..., description="Polity identifier, from the Cliopatria dataset.")
        name: External[str] | None = Field(None, description="Name of the polity, e.g. 'Ottoman Empire'.")
        type: External[PolityType] | None = Field(None, description="POLITY for a state, RELATION for a dependency link between two polities.")
        wikipedia_url: External[str] | None = Field(None, description="English Wikipedia URL, used to match Wikidata places and countries.")
        wikidata: Wikidata.Entity | None = Field(None, description="The Wikidata item for the polity, resolved from its Wikipedia URL. NULL where no match was found.")
        periods: "tuple[Individual.PolityPeriod, ...]" = Field((), description="Territorial periods of the polity, one per change.")
        modern_countries: "tuple[Individual.PolityModernCountry, ...]" = Field((), description="Modern countries the polity's territory overlaps.")
        number_of_individuals: Derived[int] | None = Field(None, description="Number of individuals matched to this polity. Counted over `Individual.polities`.")

    class PolityMatch(Model):
        polity: "Individual.Polity" = Field(..., description="The historical polity the individual is attached to, with its periods and modern countries.")
        origin: CliopatriaOrigin | None = Field(None, description="Which attribute placed the individual in the polity: their birthplace, their deathplace, or their country of citizenship.")
        matched: Wikidata.Entity | None = Field(None, description="The city or country that produced the match.")
        method: CliopatriaMethod | None = Field(None, description="How the match was made: the place fell inside the polity's polygon, or the two shared a Wikipedia URL.")
        floruit_year: int | None = Field(None, description="Floruit year used to test the overlap with the polity's periods.")
        floruit_period: "Individual.Span | None" = Field(None, description="Activity window used for the overlap test.")
        overlap_years: int | None = Field(None, description="Years of the activity window covered by this polity, summed over all of its periods. Use it to pick the dominant polity of a multi-polity individual.")

    class PolityMatchRoutes(Model):
        floruit_year: int | None = Field(None, description="Floruit year used when testing the candidate matches.")
        polygon_birthplace: bool | None = Field(None, description="True if the birth place falls inside some polity polygon.")
        polygon_deathplace: bool | None = Field(None, description="True if the death place falls inside some polity polygon.")
        polygon_country_of_citizenship: bool | None = Field(None, description="True if the country of citizenship falls inside some polity polygon.")
        url_birthplace: bool | None = Field(None, description="True if the birth place matched a polity by Wikipedia URL.")
        url_deathplace: bool | None = Field(None, description="True if the death place matched a polity by Wikipedia URL.")
        url_country_of_citizenship: bool | None = Field(None, description="True if the country of citizenship matched a polity by Wikipedia URL.")

    birth: Wikidata[Wikidata.HistoricalDate] | None = None
    death: Wikidata[Wikidata.HistoricalDate] | None = None
    floruit_declared: Wikidata[Wikidata.HistoricalDate] | None = None
    birthplace: Place | None = Field(None, description="City of birth, with its coordinates and modern country. Wikidata P19 'place of birth'.")
    deathplace: Place | None = Field(None, description="City of death, with its coordinates and modern country. Wikidata P20 'place of death'.")
    citizenships: tuple[Citizenship, ...] = Field((), description="Countries of citizenship, in Wikidata order, historical entities included. Wikidata P27 'country of citizenship'.")
    occupations: tuple[Occupation, ...] = Field((), description="Occupations, in Wikidata order. Wikidata P106 'occupation'.")
    writing_languages: tuple[WritingLanguage, ...] = Field((), description="Languages the individual wrote in. Wikidata P6886 'writing language'.")
    gender: Wikidata.Entity | None = Field(None, description="Gender item, e.g. Q6581097 for male. Free vocabulary: 48 distinct values in the data, a few of them unresolved. Wikidata P21 'sex or gender'.")
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


class Work(Wikidata.Entity):
    creator: Wikidata.Entity = Field(..., description="The individual credited for the work; joins `Individual` by qid.")
    role: Wikidata[Relationship] | None = None
    instance_of: tuple[Wikidata.Entity, ...] = Field((), description="Classes of the work, e.g. 'painting', 'film'. Wikidata P31 'instance of'.")
    inception: Wikidata[Wikidata.HistoricalDate] | None = None
    publication: Wikidata[Wikidata.HistoricalDate] | None = None

    @field_validator("role", mode="before")
    @classmethod
    def normalize_role(cls, value: object) -> object:
        return value | {"value": ROLE_FROM_PROPERTY.get(value["value"], value["value"])} if isinstance(value, dict) and isinstance(value.get("value"), str) else value


TABLES: dict[str, type[Model]] = {"individuals": Individual, "works": Work}
