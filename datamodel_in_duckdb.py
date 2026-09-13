from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Origin(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was built from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.birth', 'PolityCliopatria.geometry'. Every source the project reads is in that file in full, so this is the link back to the data exactly as it arrived, and from there to a Wikidata property and its definition.")
    inputs: tuple[str, ...] = Field((), description="For a value computed from another computed one, the fields of this table it was built on — the floruit from its start and end. Values read from a source name those in `raw` instead.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    model: str | None = Field(None, description="For a value a language model produced, the exact model id. The prompt is in prompts/, named after the task.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class Date(BaseModel):
    iso: str | None = Field(None, description="The date as an ISO string, '1879-03-14'. Wikidata's own stamp, '1879-03-14T00:00:00Z', is removed: it is not a time of day. A leading minus is a date before the common era, '-0356-07-20'.")
    year: int | None = Field(None, description="The year alone, read off `iso`. Negative before the common era. It is what nearly every analysis uses, and reading it off the string each time is a needless step.")
    precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely the source states the date, as a word rather than Wikidata's numeric code. A date known only to the century still reads as a full ISO string, so this is the only way to know it is not one.")


class WikidataEntity(BaseModel):
    qid: str = Field(..., description="The item's Wikidata identifier, 'Q937'. Everything Wikidata knows hangs off it, and it is the join key between every table here.")
    label: str | None = Field(None, description="Its English label — 'Albert Einstein', 'Kingdom of Prussia', 'astronomer'. The raw files give it as the RDF literal '\"Ulm\"@en'; the quotes and the language tag are stripped.")
    description: str | None = Field(None, description="Its English one-line description, 'city in Baden-Württemberg, Germany'. Wikidata writes one for most items, and it is often the shortest way to tell two items with the same label apart.")


class WikidataProperty(BaseModel):
    pid: str = Field(..., description="The property's identifier, 'P569'. Non-property sources keep their RDF term, 'rdfs:label'. Every column of Individual is named after one of these, and Origin.raw reaches them.")
    label: str | None = Field(None, description="The property's English label, 'date of birth'. Lowercased with non-alphanumeric runs turned into underscores, it is the column name in Individual.")
    description: str | None = Field(None, description="What the property means, in Wikidata's own words — 'date on which the subject was born'. Stored once here rather than repeated on every value, which is why no column of this schema describes itself.")


class Coordinates(BaseModel):
    latitude: float | None = Field(None, description="Decimal degrees, the latitude half of P625. Negative south of the equator.")
    longitude: float | None = Field(None, description="Decimal degrees, the longitude half. Negative west of Greenwich.")


class ExistencePeriod(BaseModel):
    inception: Date | None = Field(None, description="When it came into being, P571. The precision is worth reading before the year: a city dated to the century is not a city dated to the day.")
    dissolution: Date | None = Field(None, description="When it ceased to exist, P576. Empty for something that still does.")


class PresentDayState(BaseModel):
    name: str | None = Field(None, description="The state's name in English, 'Russia'.")
    iso_3166_1_alpha_3_code: str | None = Field(None, description="Its ISO 3166-1 alpha-3 code, 'RUS'. Empty where the geocoder found none, which happens at sea and in Antarctica.")
    continent: str | None = Field(None, description="The continent it sits on, 'Europe'. It is the coarsest grouping in the schema and the one most analyses reach for first, so it is here rather than left to a lookup a reader has to supply.")


class Sitelink(BaseModel):
    url: str = Field(..., description="A Wikimedia edition, by its URL — 'https://fr.wikipedia.org'. This is the key: 612 of them carry the 15 551 839 pages, and an individual reaches at most 341. They are not all Wikipedia — 349 are, and the rest are Wikiquote (81), Wikisource (76), Wikibooks (43), Wikinews (30) and Wikivoyage (10). Counting a person's pages without filtering on the project counts their quotations and their transcribed works alongside the articles about them.")
    label: str | None = Field(None, description="The edition's name in English, 'French Wikipedia'.")
    language: str | None = Field(None, description="The language it is written in, as a qid — joining to the same items Individual.writing_language names.")
    is_western: bool | None = Field(None, description="Whether the edition counts as Western, from its language code. Drawing this line is a decision this project made, not a fact Wikidata states, which is why it is a column to be read and argued with rather than a rule buried in the code. 208 editions are Western, 204 are not, and 200 are on neither list — 9.4 per cent of all pages — so a split computed from this column leaves a residue.")
    number_of_articles: int | None = Field(None, description="How many of the individuals in Cultura this edition covers. A count of articles is a measure of the edition as much as of the people in it: a large edition makes everyone in it look better known.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class PeakProductivity(BaseModel):
    start_year: int | None = Field(None, description="First year of the range. By convention that is from age 30 to age 60, truncated by an early death — so it is a claim about a life stage, not a record of anything observed.")
    midpoint_year: int | None = Field(None, description="The single year that stands for the range, its middle. Empty on 12 934 755 of the 13 003 420 rows — it survives only where a source states a single year, so a distribution over time has to be built from start_year and end_year instead. It is the floruit as defined in the paper, and deliberately not called floruit — Wikidata has a property of that name, P1317, which is a date a source states rather than a range this project computes, and it is on Individual.floruit_date.")
    end_year: int | None = Field(None, description="Last year of the range.")
    is_estimated: bool | None = Field(None, description="True when the range rests on an estimated birth or death year rather than an attested one. The range is still usable; it is simply softer, and this says so rather than leaving it to be discovered.")
    assignation_method: str | None = Field(None, description="How the range was arrived at, as a token naming the dates used and where they came from — 'birth_death_property', 'birth_only_property', 'works_span', 'floruit_description', 'no_data'. Twenty-two of them across the thirteen million, and they are not interchangeable: a range from an attested birth and death is a different claim from one the life-expectancy model produced. Group by this before trusting any distribution over time.")


class Territory(BaseModel):
    start_year: int | None = Field(None, description="First year the polity held this ground. Negative before the common era.")
    end_year: int | None = Field(None, description="Last year it held it.")
    area: float | None = Field(None, description="Area of that ground in square kilometres. Read down the territories and you watch an empire move: the Greek City-States go 64 106, then 89 420, then 129 112 km².")
    geometry: str | None = Field(None, description="The ground itself, as GeoJSON — a Polygon for a territory in one piece, a MultiPolygon when it is not, and never a Point: a polity holds an area, the smallest in Cliopatria being 87 km². This is what decides whether a place falls inside the polity, and the heaviest column in the published set.")
    present_day_states: tuple[PresentDayState, ...] = Field((), description="The states holding this ground today — several, because a historical territory does not stop at present-day borders. The same model Place and CountryOfCitizenship carry, so a birthplace, a citizenship and a territory all land on comparable ground. Cliopatria resolves these per polity rather than per territory, so loading it as it stands repeats the same ones on every entry; only recomputing them from this polygon makes the breakdown real.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Polity(BaseModel):
    cliopatria_id: int | None = Field(None, description="Cliopatria's identifier for the polity — assigned by this project when the GeoJSON was loaded, since Cliopatria itself numbers nothing. One row per polity here — 1 633 of them — with the changes of borders nested in `territories` rather than spread over 13 755 rows that repeat the name.")
    name: str | None = Field(None, description="The polity's name as Cliopatria spells it — 'Ottoman Empire', 'Magadha - Shaishunaga dynasty'. Its own spelling, not Wikidata's.")
    type: Literal["POLITY", "RELATION"] | None = Field(None, description="'POLITY' for a polity in its own right, 'RELATION' for a dependency between two of them — 13 370 against 385. A relation is not somewhere a person can be born, so filter on it before counting.")
    existence: ExistencePeriod | None = Field(None, description="The years the polity existed, read off its territories — the earliest start and the latest end. Cliopatria states years and nothing finer, so the precision is always 'year' and the day in the ISO string carries no information.")
    entity: WikidataEntity | None = Field(None, description="The Wikidata item Cliopatria resolved for the polity, where it resolved one — the join out to Wikidata and to the other tables here. Empty for a polity it could not resolve, which is why cliopatria_id and not a qid is this table's key.")
    sitelink: Sitelink | None = Field(None, description="Its English Wikipedia article. Cliopatria publishes the title and this is the URL built from it; matching a place to a polity by URL is one of the two ways it is done, the other being a territory's polygon.")
    territories: tuple[Territory, ...] = Field((), description="The ground the polity held, one entry per change of borders, oldest first — each with its own years, area, polygon and the polities holding that ground today. A polity averages 8.4 of them and one reaches 212.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class WorksPeriod(BaseModel):
    first_year: int | None = Field(None, description="Year of the earliest dated work, by publication date where there is one and creation date otherwise.")
    last_year: int | None = Field(None, description="Year of the latest, on the same terms.")


class Notability(BaseModel):
    western_reach: int | None = Field(None, description="How far the individual reaches into Western-language coverage, as this project scores it. Deliberately not called a count of editions: it is not a partition of the individual's own sitelinks, and the two reaches sum to more pages than the individual has on 499 of 500 sampled rows, by 37.8 on average — Shakespeare has 332 pages, 228 Western and 348 non-Western. Do not derive it from individual_sitelink or check it against that table.")
    non_western_reach: int | None = Field(None, description="The same for non-Western coverage, on the same caution.")
    cross_cultural_score: float | None = Field(None, description="The geometric mean of the two reaches, 0 to about 282, and the project's headline ranking. A geometric mean is what makes it cross-cultural: 100 Western and 100 non-Western scores 100, while 200 Western and none scores 0 — so it measures reach across the divide, not reach in total.")


class PolityMatch(BaseModel):
    polity: Polity | None = Field(None, description="The polity, carrying its id and its name only — the ground it held is in its territories, in the Polity table, which a polygon repeated on thirteen million rows would otherwise dwarf.")
    years: int | None = Field(None, description="Years of the peak-productivity range spent inside it. A small number means the match is incidental — someone who died abroad.")
    assignation_method: Literal["polygon", "url"] | None = Field(None, description="Which of the two matches settled it — the location falling inside the ground the polity held, or the location and the polity sharing a Wikipedia article. The polygon does almost all of it: 7 745 076 matches against 85 265 by URL.")
    matched_on: Literal["birthplace", "deathplace", "country_of_citizenship"] | None = Field(None, description="Which of the individual's locations the match ran on. It matters as much as the method: a polity matched on a birthplace says where someone started, one matched on a country of citizenship says what state claimed them, and the two disagree for anyone who moved. The split is 2 873 217 birthplaces, 2 690 644 deathplaces and 2 266 480 citizenships.")


class Place(BaseModel):
    entity: WikidataEntity = Field(..., description="The place's Wikidata item, as Individual.place_of_birth and .place_of_death name it. Its description is often the only thing that tells a city from a hospital without reading the P31 classes.")
    coordinates: Coordinates | None = Field(None, description="Where the place is, P625. This is what every polygon test runs against, so a place without it can never be matched to a polity.")
    country: str | None = Field(None, description="P17, the country Wikidata declares the place to be in, as a qid. For a historical place this is often a state that no longer exists — Königsberg is declared in the Kingdom of Prussia. Join it to CountryOfCitizenship.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the place as qids — 'city', 'hospital', 'quarter'. P19 names all of these as places of birth.")
    existence: ExistencePeriod | None = Field(None, description="The years the place existed. A birthplace with an end has since been razed or absorbed.")
    present_day_state: PresentDayState | None = Field(None, description="The state holding this ground today, from a reverse geocoder on the coordinates — not what Wikidata declares. Königsberg is declared in Prussia and geocodes to Russia. Computed, unlike everything above it.")
    is_settlement: bool | None = Field(None, description="True when the place is a populated place rather than a hospital, a building or an administrative region. A language model read the P31 classes, not the places, so a place is a settlement when any of its classes is. Computed.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column. An entry with a rule was computed — the last three columns — and one without was read.")


class CountryOfCitizenship(BaseModel):
    entity: WikidataEntity = Field(..., description="The state's Wikidata item, as Individual.country_of_citizenship names it. Historical states are here as readily as present ones.")
    instance_of: tuple[str, ...] = Field((), description="P31, as qids — 'sovereign state', 'former country'. This is what tells a state that still exists from one that does not, without asking a geocoder.")
    coordinates: Coordinates | None = Field(None, description="Where the state is, P625 — a single point for a whole country, so it locates it rather than bounds it.")
    present_day_state: PresentDayState | None = Field(None, description="The state holding this ground today, reverse-geocoded from the coordinates — the Ottoman Empire gives Turkey, the Kingdom of Prussia gives Germany, and a state that still exists gives itself. Computed, unlike everything above it, and the reason no column here carries a historical state's own ISO code: it has none.")
    sitelink: Sitelink | None = Field(None, description="Its English Wikipedia article, which is how a state is matched to a Cliopatria polity when the polygons do not settle it.")
    existence: ExistencePeriod | None = Field(None, description="The years the state existed. An empty dissolution is the only thing that says it still does — present_day_state is filled either way.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Occupation(BaseModel):
    entity: WikidataEntity = Field(..., description="The occupation's Wikidata item, as Individual.occupation names it.")
    subclass_of: tuple[str, ...] = Field((), description="P279, as qids. This is the tree Individual.is_scientist and .is_artist walk, so it is here rather than left implicit in the flags.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Identifier(BaseModel):
    property: WikidataProperty = Field(..., description="The Wikidata property that carries the identifier, 'P214' for VIAF, its label being the database's name. This is what an external database is: Wikidata has 10 329 such properties and nothing else names them.")
    formatter_url: str | None = Field(None, description="P1630, the template that turns an identifier into a link — 'https://viaf.org/viaf/$1', with $1 standing for the value. It is why IndividualIdentifier need not store a URL per row.")
    issuer: str | None = Field(None, description="P1629, the qid of the organisation that issues the identifiers — a national library, a museum.")
    issuer_country: str | None = Field(None, description="P17 of that issuer, as a qid. Use it to weigh how national a database's coverage is: a French library indexes French lives more densely, and a count of identifiers is not a count of importance.")
    official_website: str | None = Field(None, description="P856 of the database.")
    number_of_records: int | None = Field(None, description="P4876, how many records it holds. Together with the count of individuals carrying one of its identifiers, this says what share of the database Cultura reaches.")
    inception: Date | None = Field(None, description="When the database was founded, P571.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class IndividualIdentifier(BaseModel):
    qid: str = Field(..., description="The individual, joining to Individual.qid.")
    pid: str = Field(..., description="Which database, joining to Identifier.pid. The pair is the key: an individual has at most one identifier per database.")
    value: str | None = Field(None, description="The identifier as that database issued it, '75121530'. A string, never a number: many carry leading zeros or letters.")
    url: str | None = Field(None, description="The record's URL where Wikidata gives one. It is otherwise Identifier.formatter_url with the value substituted, so this column is mostly empty by design.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class IndividualSitelink(BaseModel):
    qid: str = Field(..., description="The entity the page is about, joining to its own table — Individual.qid for the rows of individual_sitelink, and the state's or the polity's qid where one of those carries a page of its own.")
    url: str = Field(..., description="The page's URL, percent-encoded as Wikidata gives it. With the qid it is the key, and on its own it identifies the article across the whole set — an individual has at most one per edition.")
    site_url: str | None = Field(None, description="Which edition, joining to Sitelink.url. It is the host of `url` and could be cut from it, but a join that needs string surgery is a join most people get wrong, so it is a column.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped — 'هانز-ايكارت شايفر'.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Work(BaseModel):
    entity: WikidataEntity = Field(..., description="The work's Wikidata item, its title as the label — 'Mona Lisa'. A few keys in the source are lexeme URIs rather than qids.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the work as qids — 'painting', 'film', 'novel'.")
    inception: Date | None = Field(None, description="When the work was made, P571.")
    publication_date: Date | None = Field(None, description="When it was first published or released, P577. The year of a work is this where there is one and the inception otherwise, which is how Individual.works_period is built.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class IndividualWork(BaseModel):
    qid: str = Field(..., description="The individual credited, joining to Individual.qid.")
    work_qid: str = Field(..., description="The work, joining to Work.qid. The pair is the key: a work with several creators has one row per creator.")
    credit_property: WikidataProperty | None = Field(None, description="The property that credits them — 'P50' author, 'P170' creator, 'P175' performer. It is what stops an actor and a director counting as having written the same film.")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by column.")


class Individual(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual's Wikidata item, their name as the label. Raw: IndividualWikidata.qid, .label and .description.")
    birth_date: Date | None = Field(None, description="Date of birth as one value: the ISO string, the year read off it, and the precision. Built from IndividualWikidata.date_of_birth and .date_of_birth_precision, which arrive as two separate files and are one fact.")
    death_date: Date | None = Field(None, description="Date of death, on the same terms.")
    floruit_date: Date | None = Field(None, description="The P1317 date, on the same terms. Still a date Wikidata states, not IndividualEnriched.peak_productivity, which this project computes.")
    place_of_birth: Place | None = Field(None, description="P19, carrying the place's qid and its name only — the coordinates, the classes and the modern country are in the Place table, which is what keeps them from being repeated on thirteen million rows. Often a city, sometimes a country, sometimes a hospital: P19 makes no promise, and Place.instance_of is where that is settled. Raw: IndividualWikidata.place_of_birth.")
    place_of_death: Place | None = Field(None, description="P20, on the same terms. Raw: IndividualWikidata.place_of_death.")
    sex_or_gender: str | None = Field(None, description="P21, as a qid. A free vocabulary in practice: 48 distinct values in the data. Raw: IndividualWikidata.sex_or_gender.")
    occupation: tuple[Occupation, ...] = Field((), description="P106, in Wikidata's order, each carrying the occupation's qid and its name only — the subclass tree that IndividualEnriched.is_scientist and .is_artist walk is in the Occupation table. Raw: IndividualWikidata.occupation.")
    country_of_citizenship: tuple[CountryOfCitizenship, ...] = Field((), description="P27, in Wikidata's order, historical states included, each carrying the state's qid and its name only — its coordinates, its dates and its ISO code are in the CountryOfCitizenship table. This is the state a person held papers from, not the ground they lived on: IndividualEnriched.polity is that. Raw: IndividualWikidata.country_of_citizenship.")
    writing_language: tuple[str, ...] = Field((), description="P6886, qids. Raw: IndividualWikidata.writing_language.")
    external_id: tuple[IndividualIdentifier, ...] = Field((), description="Every external database that holds a record for the individual, each carrying the database's pid and the identifier it issued. Which database it is, is the pid and nothing else — Identifier is where that is named and given a formatter_url to build the link from. Raw: IndividualWikidata.external_id, a map of property to value.")
    sitelink: tuple[IndividualSitelink, ...] = Field((), description="Every Wikimedia page about the individual, one per edition, up to 341, each carrying the edition and the page's title and URL. Most are Wikipedia articles; the rest are Wikiquote, Wikisource, Wikibooks, Wikinews and Wikivoyage pages, told apart by the host in Sitelink.url. Raw: IndividualWikidata.sitelink.")
    work: tuple[IndividualWork, ...] = Field((), description="Every work credited to the individual, each carrying the work's qid and the property that credits them — which is what stops an actor and a director counting as having written the same film. The title and the dates are on the work's own row. Raw: IndividualWikidata.work.")
    works_period: WorksPeriod | None = Field(None, description="The years their dated works span, from the earliest to the latest. Unlike peak_productivity this is observed rather than inferred — but only from works that carry a date, so it is narrower than a working life and empty for the many individuals credited with none.")
    is_human: bool | None = Field(None, description="False for the rows that are not people — fictional characters, deities, legendary creatures. Wikidata classes them among humans, so filter on this before counting.")
    is_scientist: bool | None = Field(None, description="True when any occupation descends from 'scientist' (Q901) through Wikidata's subclass tree.")
    is_artist: bool | None = Field(None, description="True when any occupation descends from 'artist' (Q483501).")
    origins: dict[str, Origin] = Field({}, description="Where each value came from, keyed by field name. Every entry names a raw field and carries no rule: the values here are the raw ones unquoted and stripped of their stamps, nothing more. Any change of shape — a date joined to its precision, a qid resolved to a label — is on IndividualEnriched.")


class IndividualEnriched(BaseModel):
    qid: str = Field(..., description="The individual, joining to Individual.qid. This table holds only what the project computed; everything a source states is on that row.")

    peak_productivity: PeakProductivity | None = Field(None, description="The range of years this project takes the individual to have been at work, and the single year that stands for it. This is what to date an individual by in a distribution over time: birth and death are missing for most people before 1500, and a birth year dates someone decades before they did anything.")

    polity: PolityMatch | None = Field(None, description="The historical polity the individual most belonged to, and how long they were in it. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and the one with the longest overlap is published here. CVDB and Pantheon answer this question too, by other methods — theirs are in datamodel_raw.py.")
    polity_count: int | None = Field(None, description="How many polities the individual overlaps at all. More than one is normal for a long life in a contested region.")

    notability: Notability | None = Field(None, description="How widely the individual is written about, as the two counts the project publishes and the score built from them. Compare it with CVDB's visibility and Pantheon's hpi, which rank the same people differently — theirs are in datamodel_raw.py.")

    origins: dict[str, Origin] = Field({}, description="Where every value on this row came from, keyed by field name. Each one carries the rule that produced it and the raw fields it was built on, which is the whole method: nothing here is read from a source, so nothing here is beyond argument.")


TABLES = {"individual": Individual, "individual_enriched": IndividualEnriched, "polity": Polity, "place": Place, "country_of_citizenship": CountryOfCitizenship, "occupation": Occupation, "work": Work, "identifier": Identifier, "individual_identifier": IndividualIdentifier, "sitelink": Sitelink, "wikidata_property": WikidataProperty, "individual_sitelink": IndividualSitelink, "individual_work": IndividualWork}
