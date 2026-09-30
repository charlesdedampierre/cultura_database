from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AIAnswer(BaseModel):
    model_name: str | None = Field(None, description="The exact model id that answered, 'claude-opus-4-20250514'. The version matters: the same prompt to a later model gives different answers, and a value without this cannot be reproduced.")
    prompt_id: str | None = Field(None, description="The prompt that was sent, by the name of its file in prompts/ — 'urban_settlement', 'wikipedia_dates'. The file is the prompt in full, so the question asked is on the record alongside the answer.")


class Provenance(BaseModel):
    raw: tuple[str, ...] = Field((), description="The fields of datamodel_raw.py this value was built from, as 'Model.field' — 'IndividualWikidata.date_of_birth', 'CrossVerifiedPerson.birth', 'PolityCliopatria.geometry'. Every source the project reads is in that file in full, so this is the link back to the data exactly as it arrived, and from there to a Wikidata property and its definition.")
    inputs: tuple[str, ...] = Field((), description="For a value computed from another computed one, the fields of this table it was built on — the floruit from its start and end. Values read from a source name those in `raw` instead.")
    rule: str | None = Field(None, description="For a computed value, what was done to those inputs, in one sentence. This is the whole method: there is no step recorded elsewhere.")
    ai_answer: AIAnswer | None = Field(None, description="Set when a language model produced the value rather than a rule — which model, and which prompt it was given. A value with this is a judgement, not a lookup, and is the one kind here that a rerun can change.")
    retrieved_on: date | None = Field(None, description="The day the source was read. Wikidata is edited continuously, so a value without this cannot be reproduced.")


class Date(BaseModel):
    iso: str | None = Field(None, description="The date as an ISO string, '1879-03-14'. Wikidata's own stamp, '1879-03-14T00:00:00Z', is removed: it is not a time of day. A leading minus is a date before the common era, '-0356-07-20'. Empty where the source gives a bare year and nothing to build a day out of — every source but a Wikidata date property does — and `year` carries the value instead.")
    year: int | None = Field(None, description="The year alone, read off `iso` where there is one and stated outright where there is not. Negative before the common era. It is what nearly every analysis uses, and reading it off the string each time is a needless step.")
    precision: Literal["day", "month", "year", "decade", "century", "millennium"] | None = Field(None, description="How precisely the source states the date, as a word rather than Wikidata's numeric code. A date known only to the century still reads as a full ISO string, so this is the only way to know it is not one. Always 'year' for a date that arrived as a bare year.")
    field_provenance: dict[str, Provenance] = Field({}, description="Where this one date came from, keyed by the field of this model it accounts for — the same entry on each, because a date, the year read off it and its precision are one fact from one reading. Every other field_provenance in this file explains a column of a row; this one explains a single value, and it is the only place a distinction survives that the row-level one cannot state: Wikidata's P569 is a date a source asserts with a precision, while the year a pattern-matcher pulled out of a one-line description, the year the cross-verified database publishes, the year read off a Wikipedia page and the year a life-expectancy model supplied are four other things entirely. A column-level entry can only say what the column means; this says what the value is. Read the rule before the year: an entry with no rule is a date a source states, an entry with one is a date this project worked out, and an entry with an ai_answer — none of the dates here has one yet — would be a judgement a language model made.")


class WikidataEntity(BaseModel):
    qid: str = Field(..., description="The item's Wikidata identifier, 'Q937'. Everything Wikidata knows hangs off it, and it is the join key between every table here.")
    label_en: str | None = Field(None, description="Its English label — 'Albert Einstein', 'Kingdom of Prussia', 'astronomer'. The raw files give it as the RDF literal '\"Ulm\"@en'; the quotes and the language tag are stripped.")
    label_non_en: str | None = Field(None, description="Its name in another language, for an item with no English or 'mul' label — 'Кузюлев Николай Николаевич'. Filled only where label_en is empty; the language is the alphabetically first code Wikidata has a label in, so reruns agree.")
    label_language: str | None = Field(None, description="The language of the label the item has: 'en' or 'mul' (the language-neutral label Wikidata uses in place of many English ones) for label_en, another code — 'ru', 'zh', 'ja' — for label_non_en. Empty only where the item has no label at all.")
    description: str | None = Field(None, description="Its English one-line description, 'city in Baden-Württemberg, Germany'. Wikidata writes one for most items, and it is often the shortest way to tell two items with the same label apart.")


class WikidataProperty(BaseModel):
    pid: str = Field(..., description="The property's identifier, 'P569'. Non-property sources keep their RDF term, 'rdfs:label'. Every column of Individual is named after one of these, and Provenance.raw reaches them.")
    label_en: str | None = Field(None, description="The property's English label, 'date of birth'. Lowercased with non-alphanumeric runs turned into underscores, it is the column name in Individual.")
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
    continent: str | None = Field(None, description="The continent it sits on, 'Europe'. It is the coarsest grouping in the schema and the one most analyses reach for first, so it is here rather than left to a lookup a reader has to supply. Wikidata's continent (P30) is kept except for two regroupings Claude, Anthropic's language model, drew up for this project: a list of states that read 'Latin America' (Wikidata puts Mexico in North America and Brazil in South America) and a list that read 'Middle East' (Wikidata puts Egypt in Africa and Turkey in Asia). The lists and the rule are in database_enrichment/06b_western_continents_and_worlds.py, which writes them, and the field_provenance of the row holding the state says so.")
    is_western: bool | None = Field(None, description="Whether the state counts as Western: True for a state on the list of Western countries Claude, Anthropic's language model, drew up for this project, False for any other named state, empty where there is no name. A decision to be read and argued with, not a fact a source states. The list carries a few historical states (Weimar Republic, German Reich, Kingdom of Italy) because Wikidata names them as countries of citizenship. Written by database_enrichment/06b_western_continents_and_worlds.py.")


class Sitelink(BaseModel):
    url: str = Field(..., description="A Wikimedia edition, by its URL — 'https://fr.wikipedia.org'. This is the key: 612 of them carry the 15 551 839 pages, and an individual reaches at most 341. They are not all Wikipedia — 349 are, and the rest are Wikiquote (81), Wikisource (76), Wikibooks (43), Wikinews (30) and Wikivoyage (10). Counting a person's pages without filtering on the project counts their quotations and their transcribed works alongside the articles about them.")
    label_en: str | None = Field(None, description="The edition's name in English, 'French Wikipedia'.")
    language: str | None = Field(None, description="The language it is written in, as a qid — joining to the same items Individual.writing_language names.")
    is_western: bool | None = Field(None, description="Whether a Wikipedia edition counts as Western, from its language code. Drawing this line is a decision this project made, not a fact Wikidata states, which is why it is a column to be read and argued with rather than a rule buried in the code. 75 editions are Western and 98 are not; the other Wikipedias are on neither list, and every non-Wikipedia site (Commons, Wikiquote...) is left empty. The two lists of language codes were drawn up by Claude, Anthropic's language model, for this project; database_enrichment/06b_western_continents_and_worlds.py holds them and writes this column.")
    number_of_articles: int | None = Field(None, description="How many of the individuals in Cultura this edition covers. A count of articles is a measure of the edition as much as of the people in it: a large edition makes everyone in it look better known.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class PeakProductivity(BaseModel):
    start_year: int | None = Field(None, description="First year of the range. Where it is inferred from a birth year it is that year plus the low end of the productive-age window — the first quartile of age at floruit, measured over the 16 106 individuals whose birth year and P1317 floruit are both stated to the year, and kept in data/productive_age_window.csv rather than written into the code. Globally that is 29 and the high end is 53, and the window differs by occupation: 30 to 61 in Culture, 32 to 60 in Discovery and Science, 21 to 35 in Sports and Games. The per-occupation windows are not applied, their category coming from the cross-verified database, which this schema does not carry. An early death truncates the range.")
    end_year: int | None = Field(None, description="Last year of the range. A window is always a range and never a single year: where a source states one year — a floruit, or the only dated work — that year is where the range is anchored, not what it collapses to, and assignation_method says which.")
    assignation_method: str | None = Field(None, description="How the range was arrived at, as a token naming the dates used and where they came from — 'birth_death_property', 'birth_only_property', 'works_span', 'floruit_description', 'no_data'. Twenty-two of them across the thirteen million, and they are not interchangeable: a range from an attested birth and death is a different claim from one the life-expectancy model produced. Group by this before trusting any distribution over time.")


class Territory(BaseModel):
    start_year: int | None = Field(None, description="First year the polity held this ground. Negative before the common era.")
    end_year: int | None = Field(None, description="Last year it held it.")
    area: float | None = Field(None, description="Area of that ground in square kilometres. Read down the territories and you watch an empire move: the Greek City-States go 64 106, then 89 420, then 129 112 km².")
    geometry: str | None = Field(None, description='The ground itself, as a GeoJSON geometry object serialised to a string: {"type": …, "coordinates": …} and those two keys only — no Feature wrapper, no properties, no crs member. The type is Polygon on 6 522 territories and MultiPolygon on 7 233, never a Point: a polity holds an area, the smallest in Cliopatria being 87 km². Coordinates are longitude then latitude in decimal degrees on WGS 84, as RFC 7946 requires, with rings closed and the outer ring first. Parse it with any GeoJSON reader, or in DuckDB with ST_GeomFromGeoJSON after installing spatial. It is by far the heaviest column here — 149 613 205 bytes over the 13 755 territories, a Polygon averaging 2.7 KB and a MultiPolygon 18 KB, one reaching 279 KB — which is why the polities are a table of their own and not embedded in each individual.')
    present_day_states: tuple[PresentDayState, ...] = Field((), description="The states holding this ground today — several, because a historical territory does not stop at present-day borders. The same model Place and CountryOfCitizenship carry, so a birthplace, a citizenship and a territory all land on comparable ground. Cliopatria resolves these per polity rather than per territory, so loading it as it stands repeats the same ones on every entry; only recomputing them from this polygon makes the breakdown real.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class Polity(BaseModel):
    cliopatria_id: int | None = Field(None, description="Cliopatria's identifier for the polity — assigned by this project when the GeoJSON was loaded, since Cliopatria itself numbers nothing. One row per polity here — 1 633 of them — with the changes of borders nested in `territories` rather than spread over 13 755 rows that repeat the name.")
    name: str | None = Field(None, description="The polity's name as Cliopatria spells it — 'Ottoman Empire', 'Magadha - Shaishunaga dynasty'. Its own spelling, not Wikidata's.")
    type: Literal["POLITY", "RELATION"] | None = Field(None, description="'POLITY' for a polity in its own right, 'RELATION' for a dependency between two of them — 13 370 against 385. A relation is not somewhere a person can be born, so filter on it before counting.")
    existence_wikidata: ExistencePeriod | None = Field(None, description="When the polity began and ended according to Wikidata — P571 inception and P576 dissolution of its item, at the precision Wikidata states them. Empty where Cliopatria resolved no item or Wikidata states neither. The years Cliopatria itself gives are on the territories, and the two need not agree: Wikidata dates the polity, Cliopatria the ground it held.")
    entity: WikidataEntity | None = Field(None, description="The Wikidata item Cliopatria resolved for the polity, where it resolved one — the join out to Wikidata and to the other tables here. Empty for a polity it could not resolve, which is why cliopatria_id and not a qid is this table's key.")
    sitelink: Sitelink | None = Field(None, description="Its English Wikipedia article. Cliopatria publishes the title and this is the URL built from it; matching a place to a polity by URL is one of the two ways it is done, the other being a territory's polygon.")
    territories: tuple[Territory, ...] = Field((), description="The ground the polity held, one entry per change of borders, oldest first — each with its own years, area, polygon and the polities holding that ground today. A polity averages 8.4 of them and one reaches 212.")
    world: tuple[str, ...] = Field((), description="The cultural world the polity belongs to — 'Chinese world', 'Greek world', 'Muslim world', 'Japan', 'Korea', 'India' — from a grouping of polity names Claude, Anthropic's language model, drew up for this project. Most polities belong to none and carry an empty tuple. It is a tuple because a polity can sit in two: the Mughal Empire is in both the Muslim world and India. Written by database_enrichment/06b_western_continents_and_worlds.py, and copied onto the polities nested in IndividualEnriched.polity by 08_polity_assignment.py.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class WorksPeriod(BaseModel):
    first_year: int | None = Field(None, description="Year of the earliest dated work, by publication date where there is one and creation date otherwise.")
    last_year: int | None = Field(None, description="Year of the latest, on the same terms.")


class Notability(BaseModel):
    number_of_western_editions: int | None = Field(None, description="How many Western Wikipedia editions have a page on the individual, each edition counted once, from individual_sitelink and Sitelink.is_western.")
    number_of_non_western_editions: int | None = Field(None, description="How many non-Western Wikipedia editions, on the same terms. Editions on neither list count in neither.")
    cross_cultural_score: float | None = Field(None, description="The geometric mean of the two counts, 0 to about 282, and the project's headline ranking. A geometric mean is what makes it cross-cultural: 100 Western and 100 non-Western scores 100, while 200 Western and none scores 0 — so it measures reach across the divide, not reach in total.")


class PolityMatch(BaseModel):
    polity: Polity | None = Field(None, description="The polity, carrying its id and its name only — the ground it held is in its territories, in the Polity table, which a polygon repeated on thirteen million rows would otherwise dwarf.")
    years_spent_in_polity: int | None = Field(None, description="How many years of the peak-productivity range fall inside this polity. A small number means the match is incidental — someone who died abroad. A number larger than a lifetime means the range itself is wrong, which happens: 53 of 500 sampled rows exceed 120 years, inherited from a peak-productivity range built on a mis-dated work.")
    assignation_method: Literal["polygon_of_birthplace", "polygon_of_deathplace", "polygon_of_country_of_citizenship", "url_of_birthplace", "url_of_deathplace", "url_of_country_of_citizenship"] | None = Field(None, description="How the match was made: which test settled it, and which of the individual's locations it ran on. Both halves matter — a polity matched on a birthplace says where someone started, one matched on a country of citizenship says what state claimed them, and the two disagree for anyone who moved. The polygon does almost all of the work and the birthplace is the commonest location: 2 864 131 by polygon of birthplace, 2 688 418 of deathplace, 2 192 527 of citizenship, then 73 953 by URL of citizenship, 9 086 of birthplace and 2 226 of deathplace.")


class Place(BaseModel):
    entity: WikidataEntity = Field(..., description="The place's Wikidata item, as Individual.place_of_birth, .place_of_death and .country_of_citizenship all name it. One table holds them because P19 makes no distinction: a birthplace is as often a state or a hospital as a city, and splitting states off into a table of their own only moved the problem. Its description is often the only thing that tells a city from a hospital without reading the P31 classes.")
    coordinates: Coordinates | None = Field(None, description="Where the place is, P625 — a single point, so for a state it locates rather than bounds it. This is what every polygon test runs against, so a place without it can never be matched to a polity.")
    country: WikidataEntity | None = Field(None, description="P17, the country Wikidata declares the place to be in, joining back to this same table by its qid. For a historical place this is often a state that no longer exists — Königsberg is declared in the Kingdom of Prussia. Empty on a row that is itself a state.")
    instance_of: tuple[WikidataEntity, ...] = Field((), description="P31, the classes of the place — 'city', 'hospital', 'quarter', 'sovereign state', 'former country'. This is what tells a city from a building and a state that still exists from one that does not, without asking a geocoder, and it carries the labels so that reading it needs no second table.")
    existence: ExistencePeriod | None = Field(None, description="The years the place existed. A birthplace with an end has since been razed or absorbed, and a state with one has fallen; an empty end is the only thing that says either still stands.")
    present_day_state: PresentDayState | None = Field(None, description="The state holding this ground today, from a reverse geocoder on the coordinates — not what Wikidata declares. Königsberg is declared in Prussia and geocodes to Russia, the Ottoman Empire gives Turkey, and a state that still exists gives itself. Computed, unlike everything above it, and the reason no column here carries a historical state's own ISO code: it has none.")
    sitelink: Sitelink | None = Field(None, description="Its English Wikipedia article, which is how a state is matched to a Cliopatria polity when the polygons do not settle it.")
    is_settlement: bool | None = Field(None, description="True when the place is a populated place rather than a hospital, a building, an administrative region or a state. A language model read the P31 classes, not the places, so a place is a settlement when any of its classes is. Computed.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class Occupation(BaseModel):
    entity: WikidataEntity = Field(..., description="The occupation's Wikidata item, as Individual.occupation names it.")
    subclass_of: tuple[WikidataEntity, ...] = Field((), description="P279, the occupations this one is a kind of. This is the tree Individual.is_scientist and .is_artist walk, so it is here rather than left implicit in the flags.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class Identifier(BaseModel):
    property: WikidataProperty = Field(..., description="The Wikidata property that carries the identifier, 'P214' for VIAF, its label being the database's name. This is what an external database is: Wikidata has 10 329 such properties and nothing else names them.")
    formatter_url: str | None = Field(None, description="P1630, the template that turns an identifier into a link — 'https://viaf.org/viaf/$1', with $1 standing for the value. It is why IndividualIdentifier need not store a URL per row.")
    issuer: WikidataEntity | None = Field(None, description="P1629, the organisation that issues the identifiers — a national library, a museum.")
    issuer_country: PresentDayState | None = Field(None, description="P17 of that issuer, as a present-day state — every database here exists now, so there is no historical case. Use it to weigh how national a database's coverage is: a French library indexes French lives more densely, and a count of identifiers is not a count of importance. Its continent makes that weighing coarse but immediate.")
    official_website: str | None = Field(None, description="P856 of the property, or of its issuer (P1629) where the property has none — field_provenance says which.")
    number_of_records: int | None = Field(None, description="P4876, how many records the database holds, read from the property or else from its issuer; the largest where several are stated. Together with the count of individuals carrying one of its identifiers, this says what share of the database Cultura covers.")
    inception: Date | None = Field(None, description="When the database was founded, P571 of the property or else of its issuer.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class IndividualIdentifier(BaseModel):
    qid: str = Field(..., description="The individual, joining to Individual.qid.")
    pid: str = Field(..., description="Which database, joining to Identifier.pid. The qid and the pid do not make a key: Wikidata lets one property carry several identifiers for one person — two library records never merged into one — so the same pair recurs with a different `value` on 9 per cent of the individuals sampled. Counting rows here counts records held, not databases reached; count distinct pids for that.")
    value: str | None = Field(None, description="The identifier as that database issued it, '75121530'. A string, never a number: many carry leading zeros or letters.")
    url: str | None = Field(None, description="The record's URL: Identifier.formatter_url with $1 replaced by the value. Empty where the property has no formatter URL.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class IndividualSitelink(BaseModel):
    qid: str = Field(..., description="The entity the page is about, joining to its own table — Individual.qid for the rows of individual_sitelink, and the state's or the polity's qid where one of those carries a page of its own.")
    url: str = Field(..., description="The page's URL, percent-encoded as Wikidata gives it. With the qid it is the key, and on its own it identifies the article across the whole set — an individual has at most one per edition.")
    site_url: str | None = Field(None, description="Which edition, joining to Sitelink.url. It is the host of `url` and could be cut from it, but a join that needs string surgery is a join most people get wrong, so it is a column.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped — 'هانز-ايكارت شايفر'.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class Work(BaseModel):
    entity: WikidataEntity = Field(..., description="The work's Wikidata item, its title as the label — 'Mona Lisa'. A few keys in the source are lexeme URIs rather than qids.")
    instance_of: tuple[WikidataEntity, ...] = Field((), description="P31, the classes of the work — 'painting', 'film', 'novel', 'version, edition or translation'. The last of these is worth filtering: a translation is a row of its own, so counting works without it counts the same book many times.")
    inception: Date | None = Field(None, description="When the work was made, P571.")
    publication_date: Date | None = Field(None, description="When it was first published or released, P577. The year of a work is this where there is one and the inception otherwise, which is how Individual.works_period is built.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class IndividualWork(BaseModel):
    qid: str = Field(..., description="The individual credited, joining to Individual.qid.")
    work_qid: str = Field(..., description="The work, joining to Work.qid. The pair is the key: a work with several creators has one row per creator.")
    credit_property: WikidataProperty | None = Field(None, description="The property that credits them — 'P50' author, 'P170' creator, 'P175' performer. It is what stops an actor and a director counting as having written the same film.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each value on this row came to be, keyed by column — the raw field it was read from, or the rule that produced it.")


class Individual(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual's Wikidata item, their name as the label. Raw: IndividualWikidata.qid, .label and .description.")
    birth_date: tuple[Date, ...] = Field((), description="Every date of birth the sources give, one entry per source, each carrying in its own field_provenance where it came from. There is more than one because the sources are not one source and this project does not silently pick between them: P569 states a date on 7 511 504 individuals, a pattern-matcher reads a year out of the Wikidata one-line description on 2 056 031, the cross-verified database publishes a year on 2 088 035, a Wikipedia page yields one on 2 242, and a life-expectancy model supplies one on 287 942. Entries disagree — a year apart is common, a decade happens — and the disagreement is the information: two sources landing on 1879 is a firmer date than one source stating it, and no analysis can weigh that if only one entry survives. The order is fixed and is the answer for a reader who wants a single date: the Wikidata property first, then the description, then the cross-verified database, then Wikipedia, then the estimate — a claim someone made before a year a rule worked out, and an inference last. Take the first entry for a date; take it only if its provenance carries no rule for a date anyone asserted. Empty for an individual no source dates at all.")
    death_date: tuple[Date, ...] = Field((), description="Every date of death, on the same terms and in the same order: P570 on 3 573 591 individuals, the description on 1 496 332, the cross-verified database on 1 044 831, Wikipedia on 999, and the life-expectancy model on 1 047 565 — the model carries far more deaths than births because a birth year with no death is the commoner gap.")
    floruit_date: tuple[Date, ...] = Field((), description="Every date a source gives for when the individual was at work, on the same terms. Still dates sources state, not IndividualEnriched.peak_productivity, which this project computes from them. The property is the rarest thing in this schema — P1317 on 68 694 individuals of thirteen million — while the description yields a floruit year on 1 391 030 and Wikipedia on 8 009, so for this field the description entry is usually the only entry and a reader who filters on the property alone keeps roughly one floruit in twenty.")
    place_of_birth: Place | None = Field(None, description="P19, carrying the place's qid and its name only — the coordinates, the classes and the modern country are in the Place table, which is what keeps them from being repeated on thirteen million rows. Often a city, sometimes a country, sometimes a hospital: P19 makes no promise, and Place.instance_of is where that is settled. Raw: IndividualWikidata.place_of_birth.")
    place_of_death: Place | None = Field(None, description="P20, on the same terms. Raw: IndividualWikidata.place_of_death.")
    sex_or_gender: str | None = Field(None, description="P21, as a qid. A free vocabulary in practice: 48 distinct values in the data. Raw: IndividualWikidata.sex_or_gender.")
    occupation: tuple[Occupation, ...] = Field((), description="P106, in Wikidata's order, each carrying the occupation's qid and its name only — the subclass tree that IndividualEnriched.is_scientist and .is_artist walk is in the Occupation table. Raw: IndividualWikidata.occupation.")
    country_of_citizenship: tuple[Place, ...] = Field((), description="P27, in Wikidata's order, historical states included, each carrying the state's qid and its name only — the rest of it is on its row in the place table, where a state sits alongside the cities. This is the state a person held papers from, not the ground they lived on: IndividualEnriched.polity is that. Raw: IndividualWikidata.country_of_citizenship.")
    writing_language: tuple[str, ...] = Field((), description="P6886, qids. Raw: IndividualWikidata.writing_language.")
    external_id: tuple[IndividualIdentifier, ...] = Field((), description="Every external database that holds a record for the individual, each carrying the database's pid and the identifier it issued. Which database it is, is the pid and nothing else — Identifier is where that is named and given a formatter_url to build the link from. Raw: IndividualWikidata.external_id, a map of property to value.")
    sitelink: tuple[IndividualSitelink, ...] = Field((), description="Every Wikimedia page about the individual, one per edition, up to 341, each carrying the edition and the page's title and URL. Most are Wikipedia articles; the rest are Wikiquote, Wikisource, Wikibooks, Wikinews and Wikivoyage pages, told apart by the host in Sitelink.url. Raw: IndividualWikidata.sitelink.")
    work: tuple[IndividualWork, ...] = Field((), description="Every work credited to the individual, each carrying the work's qid and the property that credits them — which is what stops an actor and a director counting as having written the same film. The title and the dates are on the work's own row. Raw: IndividualWikidata.work.")
    works_period: WorksPeriod | None = Field(None, description="The years their dated works span, from the earliest to the latest. Unlike peak_productivity this is observed rather than inferred — but only from works that carry a date, so it is narrower than a working life and empty for the many individuals credited with none.")
    is_human: bool | None = Field(None, description="False for the rows that are not people — fictional characters, deities, legendary creatures, which Wikidata classes among humans, so filter on this before counting. Read what it actually tests before trusting it: not the person but the places, False meaning some place the individual is tied to is itself fictional, by the labels of that place's Wikidata classes. Someone born in a fictional city is taken to be a fictional character. It is one-sided evidence — a False is a fictional place found, a True only none found — and it fires rarely: 872 rows of the thirteen million.")
    is_scientist: bool | None = Field(None, description="True when any occupation descends from 'scientist' (Q901) through Wikidata's subclass tree.")
    is_artist: bool | None = Field(None, description="True when any occupation descends from 'artist' (Q483501).")
    field_provenance: dict[str, Provenance] = Field({}, description="Where each value came from, keyed by field name. Every entry names the raw fields behind the column, and for all but the three date columns it carries no rule: the values here are the raw ones unquoted and stripped of their stamps, nothing more, and any change of shape — a qid resolved to a label — is on IndividualEnriched. The entries for birth_date, death_date and floruit_date are the exception, and they are here only to say that the column is a list of one date per source; which source any one of those dates came from is on that date's own field_provenance and nowhere else, because a column-level entry repeated on every row cannot tell a P569 date from a year read out of a description.")


class IndividualEnriched(BaseModel):
    entity: WikidataEntity = Field(..., description="The individual, joining to Individual.entity.qid. This table holds only what the project computed; everything a source states is on that row.")

    peak_productivity: PeakProductivity | None = Field(None, description="The range of years this project takes the individual to have been at work: a start_year, an end_year, and an assignation_method naming the rule and the date source that produced them. Always a range, never a point. This is what to date an individual by in a distribution over time: birth and death are missing for most people before 1500, and a birth year dates someone a generation before they did anything. Read assignation_method first — a window from works_span is the years of their dated works and is observed, while one from birth_death or birth_only is a life stage inferred from the productive-age window and nothing the individual did. Empty where no rule applied at all.")

    polity: tuple[PolityMatch, ...] = Field((), description="Every historical polity the individual is matched to, longest overlap first. A place is matched to a polity when it falls inside the ground that polity held while the individual was active, and an individual is tied to three places — a birthplace, a deathplace and a citizenship — which need not sit in the same polity and, over a long life in a contested region, need not sit in one polity for the whole of it. So a person is normally in several: 1 669 435 of the 5 161 090 matched individuals carry more than one, 32 per cent of them, and one carries 43. Earlier versions of this table published the first entry alone and dropped the rest; the overlap in years on each entry is what tells a polity someone spent a working life in from one they died passing through. CVDB and Pantheon answer this question too, by other methods — theirs are in datamodel_raw.py.")
    polity_count: int | None = Field(None, description="How many polities the individual overlaps at all — the length of `polity`, kept as a column because counting is the commonest thing asked of it and len() over a list of structs is not what most people reach for. It cannot disagree with the list: `polity_count = len(polity)` holds on every row, zero included, because it is computed from the list and never alongside it.")

    notability: Notability | None = Field(None, description="How widely the individual is written about, as the two counts the project publishes and the score built from them. Compare it with CVDB's visibility and Pantheon's hpi, which rank the same people differently — theirs are in datamodel_raw.py.")

    field_provenance: dict[str, Provenance] = Field({}, description="Where every value on this row came from, keyed by field name. Each one carries the rule that produced it and the raw fields it was built on, which is the whole method: nothing here is read from a source, so nothing here is beyond argument.")


class AgeRange(BaseModel):
    low: float | None = Field(None, description="The first quartile, in years of age. A quartile and not the minimum, because the minimum of thousands of lives is a data error or an infant death and says nothing about the group — the same choice data/productive_age_window.csv makes for its low_age.")
    median: float | None = Field(None, description="The median, in years of age.")
    high: float | None = Field(None, description="The third quartile, in years of age.")


class DateRange(BaseModel):
    start_year: int = Field(..., description="First birth year of the cohort, 1650. Negative before the common era.")
    end_year: int = Field(..., description="Last birth year of the cohort, start_year + 49.")


class OccupationStats(BaseModel):
    cv_occupation: Literal["Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other", "Missing", "All"] = Field(..., description="The occupation category, as the cross-verified database's level1_main_occ gives it — CrossVerifiedPerson.level1_main_occ. Cultura's own occupations are 18 227 Wikidata items; these six are the grouping the paper's figures use, and an individual has one only where the cross-verified database holds them. 'All' is every individual with a Wikidata birth year, in the cross-verified database or not, measured at once.")
    date_range: DateRange = Field(..., description="The fifty-year birth cohort. The key is the occupation and this: every occupation has a row for every cohort from 3500 BCE to 1949, so the table is a complete lookup and never returns nothing. Cohorts born from 1950 on are left out: most of those people are still alive, so a death date would only be the ones who died young. Cohorts are by birth year for both measures, so a life expectancy and a productivity window on the same row are about the same people.")
    life_expectancy_from_wikidata_birth_death: AgeRange | None = Field(None, description="Age at death, in fractional years, of the individuals whose Wikidata P569 birth and P570 death are both stated to the year or finer — no year read off a description, the cross-verified database or Wikipedia — kept between 0 and 110. The last cohort, 1900–1949, still runs a little low: someone born in 1945 has a death date only if they died before 81.")
    productivity_window_from_wikidata_floruit: AgeRange | None = Field(None, description="Age at floruit — floruit year minus birth year — of the individuals whose Wikidata P569 birth and P1317 floruit are both stated to the year or finer, kept between 10 and 100. The quartiles are the window, as in data/productive_age_window.csv, which is this measure over all periods at once.")
    birth_n: int | None = Field(None, description="How many individuals of this occupation — or of any, for 'All' — carry a Wikidata birth year in the cohort — the pool both measures draw from. Counted on the cohort itself, however wide the pool a measure had to borrow.")
    death_n: int | None = Field(None, description="How many lives the life expectancy on this row was measured on — the cohort's own where it was measured on the cohort, the wider pool's where it was not.")
    floruit_n: int | None = Field(None, description="How many individuals the productivity window was measured on, on the same terms. Small everywhere: about 3 900 individuals carry both a cross-verified occupation and a usable floruit, so most cohorts before 1700 borrow the occupation over all periods.")
    field_provenance: dict[str, Provenance] = Field({}, description="How each measure on this row came to be, keyed by column. A cohort rarely holds enough lives to be measured on its own, so the rule names the pool the value was measured on, the first of these to reach 10 lives for life expectancy or 5 for the productivity window: the cohort alone; the cohort with the one on each side; with three on each side; the occupation over all cohorts; every individual over all cohorts. Filter on a rule naming the cohort alone for a figure about this cohort and nothing else.")


TABLES = {"individual": Individual, "individual_enriched": IndividualEnriched, "polity": Polity, "place": Place, "occupation": Occupation, "work": Work, "identifier": Identifier, "individual_identifier": IndividualIdentifier, "sitelink": Sitelink, "wikidata_property": WikidataProperty, "individual_sitelink": IndividualSitelink, "individual_work": IndividualWork, "occupation_stats": OccupationStats}
