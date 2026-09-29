from pydantic import BaseModel, Field


class Property(BaseModel):
    pid: str = Field(..., description="The property's identifier, e.g. 'P569'. Non-property sources keep their RDF term instead, e.g. 'rdfs:label' or 'schema:about'.")
    label: str = Field(..., description="The property's English label, e.g. 'date of birth'. Every field in this file is named after it — lowercased, with runs of non-alphanumeric characters turned into single underscores — so this column joins a field back to its property.")
    definition: str | None = Field(None, description="What the property means, e.g. 'date on which the subject was born'. Wikidata's own wording, not this project's.")


class Sitelink(BaseModel):
    site: str | None = Field(None, description="The edition's host, e.g. 'ar.wikipedia.org'.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped.")
    url: str | None = Field(None, description="The article's URL, percent-encoded as Wikidata gives it.")


class WorkCredit(BaseModel):
    work: str | None = Field(None, description="The work's qid.")
    property: str | None = Field(None, description="The credit property that links the individual to it — 'P50' for author, 'P170' for creator, 'P175' for performer. It is not resolved to a role name here.")


class IndividualWikidata(BaseModel):
    qid: str = Field(..., description="The individual's Wikidata item. It is the key every raw file is indexed by.")
    label: str | None = None
    description: str | None = None
    date_of_birth: str | None = None
    date_of_birth_precision: int | None = Field(None, description="Precision of P569's time value: 11 for a day, 9 for a year, 7 for a century. Not a property of its own — it is part of the time value — and it arrives in its own file, so a date and its precision can be present without each other.")
    date_of_death: str | None = None
    date_of_death_precision: int | None = Field(None, description="Precision of P570's time value.")
    floruit: str | None = None
    floruit_precision: int | None = Field(None, description="Precision of P1317's time value.")
    place_of_birth: str | None = None
    place_of_death: str | None = None
    sex_or_gender: str | None = None
    occupation: tuple[str, ...] = ()
    country_of_citizenship: tuple[str, ...] = ()
    writing_language: tuple[str, ...] = ()
    external_id: dict[str, tuple[str, ...]] = Field({}, description="A map of property to the identifiers it carries, exactly as the raw file gives them: {'P214': ('7007870',)}. The values are a list because Wikidata lets one property carry several — a person indexed twice in the same database, under two records that were never merged. It is not rare: 28 of 500 sampled individuals have at least one such property, 23 distinct properties do it, and reading only the first value would have dropped 132 identifiers from that sample alone. Which database it is, is the property and nothing else — Wikidata has 10 329 external-id properties, and Property holds what each one is.")
    sitelink: tuple[Sitelink, ...] = ()
    work: tuple[WorkCredit, ...] = Field((), description="Every work credited to the individual, as a pair of the work's qid and the property that credits them. Neither is resolved here; the labels are in WorkWikidata.")


class PlaceWikidata(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, as P19 and P20 name it.")
    label: str | None = None
    latitude: float | None = Field(None, description="The latitude half of P625 'coordinate location'. The property has two components and the extraction splits them, which is why this field cannot carry the property's own name.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = None
    instance_of: tuple[str, ...] = ()
    inception: str | None = None
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    dissolved_abolished_or_demolished_date: str | None = None
    dissolved_abolished_or_demolished_date_precision: int | None = Field(None, description="Precision of P576's time value. A place with one no longer exists, which is how a birthplace since razed or absorbed shows itself.")


class CountryWikidata(BaseModel):
    qid: str = Field(..., description="The country's Wikidata item, as P27 names it.")
    label: str | None = None
    description: str | None = None
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the entity, as qids — 'sovereign state', 'former country'. This is what tells a state that still exists from one that does not, without asking a geocoder.")
    latitude: float | None = Field(None, description="The latitude half of P625.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = None
    continent: str | None = None
    iso_3166_1_alpha_3_code: str | None = None
    sitelink: tuple[Sitelink, ...] = ()
    inception: str | None = None
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    dissolved_abolished_or_demolished_date: str | None = None
    dissolved_abolished_or_demolished_date_precision: int | None = Field(None, description="Precision of P576's time value. A state with one no longer exists.")


class OccupationWikidata(BaseModel):
    qid: str = Field(..., description="The occupation's Wikidata item, as P106 names it.")
    label: str | None = None
    subclass_of: tuple[str, ...] = ()
    description: str | None = None


class WorkWikidata(BaseModel):
    qid: str = Field(..., description="The work's Wikidata item, as the credit properties name it. A few keys in the raw file are lexeme URIs rather than qids.")
    label: str | None = None
    instance_of: tuple[str, ...] = ()
    inception: str | None = None
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    publication_date: str | None = None
    publication_date_precision: int | None = Field(None, description="Precision of P577's time value.")


class PolityCliopatria(BaseModel):
    name: str = Field(..., description="'Name' in the GeoJSON. There is no identifier in the source: a polity is its name, and the 13 755 features carry 1 633 distinct ones — 8.4 spans each on average. The integer id the legacy database uses was assigned by this project, not by Cliopatria.")
    from_year: int | None = Field(None, description="'FromYear'. Negative before the common era. One feature is one polity over one span, so a row is a polity as it stood between these two years, not the polity.")
    to_year: int | None = Field(None, description="'ToYear'.")
    area: float | None = Field(None, description="'Area', in square kilometres, unrounded as published: 22012.292763497044.")
    type: str | None = Field(None, description="'Type': 'POLITY' for a polity in its own right, 13 370 of them, and 'RELATION' for a dependency between two, 385. A relation is not somewhere a person can be born.")
    wikipedia: str | None = Field(None, description="'Wikipedia' — the English article's title, 'History of Sumer', not a URL. The URL in the legacy database was built from it. Filled on 13 750 of 13 755 features.")
    wikidata: str | None = Field(None, description="'Wikidata' — the qid Cliopatria resolved itself, 1 416 distinct ones. This is the only place the dataset touches Wikidata.")
    seshat_id: str | None = Field(None, description="'SeshatID' — the polity's identifier in the Seshat databank, 'eg_dynasty_1'. Filled on 8 328 of 13 755 features.")
    components: str | None = Field(None, description="'Components' — the polities this one is made of, semicolon-joined names: 'Elam;Babylonia'. Filled on 1 722 features.")
    member_of: str | None = Field(None, description="'MemberOf' — the polity this one belongs to, in parentheses as published: '(Phoenician Empire)'. Filled on 2 658 features.")
    geometry: str | None = Field(None, description="The feature's GeoJSON geometry as a string: Polygon on 6 522 features, MultiPolygon on 7 233, never a Point. It is the heaviest thing in the pipeline.")


class CrossVerifiedColumn(BaseModel):
    column: str = Field(..., description="The column's name in the CSV. Every field of CrossVerifiedPerson is named after it, so this column is the whole join.")
    description: str | None = Field(None, description="What the column holds, in the dataset's own wording, taken from the columns_dictionary.csv it ships with.")


class CrossVerifiedPerson(BaseModel):
    wikidata_code: str = Field(..., description="The qid, and the key this dataset is joined to Cultura on. The only field here that is not explained by CrossVerifiedColumn.")
    birth: int | None = None
    death: int | None = None
    updated_death_date: int | None = None
    approx_birth: str | None = None
    approx_death: str | None = None
    birth_min: int | None = None
    birth_max: int | None = None
    death_min: int | None = None
    death_max: int | None = None
    gender: str | None = None
    level1_main_occ: str | None = None
    name: str | None = None
    un_subregion: str | None = None
    birth_estimation: float | None = None
    death_estimation: float | None = None
    bigperiod_birth_graph_b: str | None = None
    bigperiod_death_graph_b: str | None = None
    curid: int | None = None
    level2_main_occ: str | None = None
    freq_main_occ: float | None = None
    freq_second_occ: float | None = None
    level2_second_occ: str | None = None
    level3_main_occ: str | None = None
    bigperiod_birth: str | None = None
    bigperiod_death: str | None = None
    wiki_readers_2015_2018: float | None = None
    non_missing_score: float | None = None
    total_count_words_b: float | None = None
    number_wiki_editions: int | None = None
    total_noccur_links_b: float | None = None
    sum_visib_ln_5criteria: float | None = None
    ranking_visib_5criteria: int | None = None
    all_geography_groups: str | None = None
    string_citizenship_raw_d: str | None = None
    citizenship_1_b: str | None = None
    citizenship_2_b: str | None = None
    list_areas_of_rattach: str | None = None
    area1_of_rattachment: str | None = None
    area2_of_rattachment: str | None = None
    list_wikipedia_editions: str | None = None
    un_region: str | None = None
    group_wikipedia_editions: str | None = None
    bplo1: float | None = None
    dplo1: float | None = None
    bpla1: float | None = None
    dpla1: float | None = None
    pantheon_1: int | None = None
    level3_all_occ: str | None = None


class PantheonPerson(BaseModel):
    id: int | None = Field(None, description="Pantheon's own row identifier. Not a qid: this dataset numbers its people itself.")
    wd_id: str | None = Field(None, description="The qid, and the key this dataset is joined to Cultura on. Unlike CVDB, Pantheon ships no column dictionary, so the fields below are described here.")
    wp_id: int | None = Field(None, description="English Wikipedia page id.")
    slug: str | None = Field(None, description="The name as a URL slug.")
    name: str | None = None
    occupation: str | None = Field(None, description="Pantheon's own occupation label, uppercased — 'RELIGIOUS FIGURE'. Its own vocabulary, neither Wikidata's nor CVDB's.")
    prob_ratio: float | None = Field(None, description="As published.")
    gender: str | None = Field(None, description="'M' or 'F'.")
    twitter: str | None = None
    alive: bool | None = None
    l: int | None = Field(None, description="Number of Wikipedia language editions carrying an article. Pantheon's coverage count, the equivalent of CVDB's number_wiki_editions.")
    l_: float | None = Field(None, description="An effective number of editions, always smaller than `l` and never a whole number — 223 editions give 26.6. It discounts editions that carry little, which is what keeps a stub in 200 languages from outranking a real article in 30.")
    hpi_raw: float | None = Field(None, description="Historical Popularity Index before adjustment.")
    hpi: float | None = Field(None, description="Historical Popularity Index, Pantheon's ranking metric — its answer to the same question Cultura's notability score asks, computed differently.")
    non_en_page_views: float | None = Field(None, description="Page views outside the English edition, which is how the index avoids ranking on English alone.")
    coefficient_of_variation: float | None = Field(None, description="As published.")
    age: float | None = None
    is_group: bool | None = Field(None, description="True when the row is not one person. Filter these out, as non_human does in the curated model.")
    birthdate: str | None = Field(None, description="As published, '0632-06-08' — zero-padded, no time stamp, unlike Wikidata's.")
    birthyear: int | None = Field(None, description="Negative before the common era.")
    deathdate: str | None = None
    deathyear: int | None = None
    bplace_name: str | None = Field(None, description="Birthplace as Pantheon names it, not a qid.")
    bplace_lat: float | None = None
    bplace_lon: float | None = None
    bplace_geonameid: int | None = Field(None, description="The birthplace's GeoNames identifier. Pantheon resolves places against GeoNames, where Cultura resolves them against Wikidata.")
    bplace_country: str | None = Field(None, description="Modern country of the birthplace, by name.")
    bplace_geacron_name: str | None = Field(None, description="The historical polity holding the birthplace, from GeaCron — Pantheon's equivalent of Cultura's Cliopatria match.")
    dplace_name: str | None = None
    dplace_lat: float | None = None
    dplace_lon: float | None = None
    dplace_geonameid: int | None = None
    dplace_country: str | None = None
    dplace_geacron_name: str | None = None


class PlaceModernCountry(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, the key this file is indexed by. Join it to PlaceWikidata.")
    country_name: str | None = Field(None, description="The country holding that ground today. Not read from Wikidata — a reverse geocoder was run on the place's coordinates, so this answers a different question from PlaceWikidata.country, which is what Wikidata declares and is often a state that no longer exists.")
    iso_a3_code: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country. Empty when the geocoder found no country, which happens for places at sea and in Antarctica.")


class EntityTypeClassification(BaseModel):
    qid: str = Field(..., description="A Wikidata class, not a place — 'Q1021711' is the class 'seaside resort'. The classification was run over the classes, of which there are a few thousand, rather than over the millions of places that instantiate them. A place is urban when any of its PlaceWikidata.instance_of classes is.")
    label: str | None = Field(None, description="The class's English label, as given to the model.")
    urban_settlement: bool | None = Field(None, description="Whether the class denotes a populated place — a town, a village, a quarter — rather than an administrative region, a building or a natural feature. Answered by a language model; the model id and the prompt are in the enrichment that used it.")
    reason: str | None = Field(None, description="The short phrase the model gave for its answer, kept so a wrong call can be seen rather than guessed at.")


class WritingLanguageWikidata(BaseModel):
    qid: str = Field(..., description="The language's Wikidata item, as P6886 names it. Nothing else resolved these: an individual's writing_language is a list of qids and this is what turns them into languages.")
    label: str | None = None


class ExternalIdPropertyWikidata(BaseModel):
    pid: str = Field(..., description="A Wikidata property of type external identifier, 'P214' for VIAF. There are 10 329 of them, and every key of IndividualWikidata.external_id is one.")
    label: str | None = Field(None, description="The property's English label — 'ISBN-13', 'VIAF ID'. This is the name of the database an identifier belongs to.")
    formatter_url: str | None = Field(None, description="P1630, the template that turns an identifier into a link: 'https://viaf.org/viaf/$1', with $1 standing for the value. It is how an external_id becomes a URL without storing one per individual.")
    subject_item_of_this_property: str | None = Field(None, description="P1629, the qid of the organisation that issues the identifiers — a national library, a museum. Join it to CountryWikidata to weigh how national a database's coverage is.")
    country: str | None = Field(None, description="P17 of that issuer, as a qid.")
    official_website: str | None = Field(None, description="P856 of the database.")
    number_of_records: str | None = Field(None, description="P4876, how many records the database holds, as published.")
    inception: str | None = Field(None, description="P571, when the database was founded.")


class PolityModernCountry(BaseModel):
    polity_id: int | None = Field(None, description="The Cliopatria polity, by its integer id. Several rows share one: a historical polity's ground is in 1.4 modern countries on average.")
    country_qid: str | None = Field(None, description="A country holding that ground today, as a qid. Join it to CountryWikidata.")
    iso_a3_code: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country.")
    continent: str | None = Field(None, description="P30 of that country, by name.")
    sources: str | None = Field(None, description="The Wikidata property paths that produced the mapping, pipe-joined: 'P17', 'P36/P17', 'P1366/P17'. A path of P36/P17 means the polity was matched through its capital's country rather than directly, which is a weaker claim, and this column is the only place that shows it.")


class SeshatValue(BaseModel):
    value_from: str | int | None = Field(None, description="'Value.From', the coded value as published: a presence code ('present', 'inferred absent', 'suspected unknown' — the codebook's coding conventions define each), a number, or a name. Numbers arrive as integers, everything else as text. When value_note is 'range' it is the lower bound.")
    value_to: str | int | None = Field(None, description="'Value.To', the upper bound of a range — Polity Population 50000 to 60000. Filled only when value_note is 'range', on 1 126 of 47 477 rows.")
    date_from: str | None = Field(None, description="'Date.From', with the era glued to the year: '115BCE', '1300CE'. Empty on 46 031 rows, where the value holds for the polity's whole span. Filled without date_to, it dates the value to that single year — how a changing Polity territory is published.")
    date_to: str | None = Field(None, description="'Date.To', same format. The codebook puts uncertainty on values, never on dates, so a date here is always exact.")
    fact_type: str | None = Field(None, description="'Fact.Type', 'simple' or 'complex'. A complex row is always one of several the coder's single entry was split into — the items of a list, or a value that changed over dated periods. Simple rows can share a variable too: that is how an uncertain or disputed value is published.")
    value_note: str | None = Field(None, description="'Value.Note': 'simple'; 'list', one item of a list; 'range', see value_to; 'uncertain', the codebook's [a; b] — one row per extreme, the coder cannot tell which held; 'disputed', the codebook's {a; b} — one row per expert opinion. An uncertain or disputed variable has more than one value and none of them is the answer.")
    date_note: str | None = Field(None, description="'Date.Note': 'range' when date_to is filled, empty otherwise.")


class SeshatPolity(BaseModel):
    polity: str = Field(..., description="'Polity', Seshat's seven-character polity id, 'AfDurrn' for the Durrani Empire. It is the key: 373 polities, 46 to 167 coded rows each. Not the same form as PolityCliopatria.seshat_id, 'eg_dynasty_1', so joining the two needs a crosswalk. The raw file is long, one row per coded value; every field below gathers the rows of one 'Variable', and the file's 'Section' and 'Subsection' are dropped because the variable implies them — the few rows filed elsewhere are clerical: 115 Warfare rows with no subsection, 14 ideology rows under a misspelled or wrong subsection.")
    nga: str | None = Field(None, description="'NGA', the Natural Geographic Area the polity was sampled from — a region of roughly 100 by 100 km, 'Kachi Plain'. 35 of them. The codebook uses it purely as a sampling scheme: codes describe the polity, not the NGA. Each polity sits in exactly one.")
    ra: dict[str, tuple[str, ...]] = Field({}, description="'RA', the research assistants who coded the polity, keyed by the section they coded: {'Warfare variables': ('Enrico Cioni',)}. The file repeats RA once per section, so it is a map rather than a list.")
    ritual_duration: dict[str, tuple[SeshatValue, ...]] = Field({}, description="'Duration' as published under the ritual subsections — 'Most euphoric collective ritual of the official cult' — and filed under Warfare variables. It is the duration of the ritual in hours, not of the polity, so it cannot share the duration field. Six rows in the whole file.")
    original_name: tuple[SeshatValue, ...] = Field((), description="'Original name', General variables. Generally same as the name of this page")
    alternative_names: tuple[SeshatValue, ...] = Field((), description="'Alternative names', General variables. Used in the historical literature; also supply the most common name used by the natives")
    peak_date: tuple[SeshatValue, ...] = Field((), description="'Peak Date', General variables. The period when the polity was at its peak, whether militarily, in terms of the size of territory controlled, or the degree of cultural development. This variable has a subjective element, but typically historians agree when the peak was.")
    duration: tuple[SeshatValue, ...] = Field((), description="'Duration', General variables. The starting and ending dates covered by this coding sheet. Briefly explain the significance of each date. For example, the starting date could be the establishment of a long-ruling dynasty, while the ending date may be the year when the polity was conquered by an aggressive neighbor. In cases when starting and/or ending dates are fuzzy, as explained above, use the earliest possible starting date and the latest possible ending date. This approach will result in a temporal overlap, so that some NGAs for some periods will be coded as belonging to two polities simultaneously (e.g., to a disintegrating overarching polity and to the rising regional subpolity). Such overlap is acceptable, and will be dealt with at the analysis stage.")
    degree_of_centralization: tuple[SeshatValue, ...] = Field((), description="'Degree of centralization', General variables. unknown/ quasi-polity/ nominal/ loose/ confederated state /unitary state")
    supra_polity_relations: tuple[SeshatValue, ...] = Field((), description="'Supra-polity relations', General variables. unknown/ none/ alliance/ nominal allegiance/ personal union/ vassalage/")
    preceding_quasi_polity: tuple[SeshatValue, ...] = Field((), description="'preceding (quasi)polity', General variables. Name. This code is based on the core region of the current polity (not the NGA region). E.g. Achaemenid Empire's core region was Persia, where they were preceded by the Median Empire.")
    relationship_to_preceding_quasi_polity: tuple[SeshatValue, ...] = Field((), description="'relationship to preceding (quasi)polity', General variables. Possible codes: continuity (gradual change), cultural assimilation (by another quasi-polity in the absence of substantial population replacement), elite migration (the preceding elites replaced by new elites coming from elsewhere), population migration (evidence for substantial population replacement), secession (from another polity). In the narrative paragraph explain the evidential basis for the code: what are the proxies for change? Examples include DNA data, isotope data, material (other than subsistence) culture, subsistence mode, symbolic culture (incl. burial practices), settlement patterns.")
    succeeding_quasi_polity: tuple[SeshatValue, ...] = Field((), description="'succeeding (quasi)polity', General variables. Name. Only name it here and don't code the nature of change (it's coded on the page of the succeeding quasi-polity). This code is based on the core region of the current polity (not the NGA region). E.g. Achaemenid Empire's core region was Persia, where they were succeeded by the Macedonian Empire.")
    capital: tuple[SeshatValue, ...] = Field((), description="'Capital', General variables. The city where the ruler spends most of its time. If there were more than one capital supply all names and enclose in curly braces. For example, {Susa; Pasargadae; Persepolis; Ecbatana; Babylon}. Note that the capital may be different from the largest city (see below).")
    language: tuple[SeshatValue, ...] = Field((), description="'Language', General variables. The codebook lists it without a definition.")
    supracultural_entity: tuple[SeshatValue, ...] = Field((), description="'Supracultural entity', General variables. Name it. Our quasi-polity are often embedded within larger-scale cultural groupings of polities or quasi-polities. These are sometimes referred to as \"civilizations\". For example, medieval European kingdoms were part of Latin Christendom. During the periods of disunity in China, warring states there, nevertheless, belonged to the same Chinese cultural sphere. Archaeologists often use \"archaeological traditions\" to denote such large-scale cultural entities (for example, Peregrine's Atlas of Cultural Evolution). Note, 'supracultural entity' refers to cultural interdependence, and is distinct from a political confederation or alliance, which should be coded under 'supra-polity relations.'")
    scale_of_supra_cultural_interaction: tuple[SeshatValue, ...] = Field((), description="'scale of supra-cultural interaction', General variables. km squared. An estimate of the area encompassed by the supracultural entity")
    polity_territory: tuple[SeshatValue, ...] = Field((), description="'Polity territory', Social Complexity variables › Social Scale. in squared kilometers")
    polity_population: tuple[SeshatValue, ...] = Field((), description="'Polity Population', Social Complexity variables › Social Scale. Estimated population of the polity; can change as a result of both adding/losing new territories or by population growth/decline within a region")
    population_of_the_largest_settlement: tuple[SeshatValue, ...] = Field((), description="'Population of the largest settlement', Social Complexity variables › Social Scale. Note that this could be different from the capital (coded under General). If possible, indicate the dynamics (that is, how population changed during the temporal period of the polity). Note that we are also building a city database - you should consult it as it may already have the needed data.")
    settlement_hierarchy: tuple[SeshatValue, ...] = Field((), description="'Settlement hierarchy', Social Complexity variables › Hierarchical Complexity. levels. This variable records the hierarchy of not just settlement sizes, but also their complexity as reflected in different roles they play within the (quasi)polity. As settlements become more populous they acquire more complex functions: transportational (e.g. port); economic (e.g. market); administrative (e.g. storehouse, local government building); cultural (e.g. theatre); religious (e.g. temple), utilitarian (e.g. hospital), monumental (e.g. statues, plazas).")
    administrative_levels: tuple[SeshatValue, ...] = Field((), description="'Administrative levels', Social Complexity variables › Hierarchical Complexity. levels. An example of hierarchy for a state society could be (1) the overall ruler, (2) provincial/regional governors, (3) district heads, (4) town mayors, (5) village heads. Note that unlike in settlement hierarchy, here you code people hierarchy. Do not simply copy settlement hierarchy data here. For archaeological polities, you will usually code as 'unknown', unless experts identified ranks of chiefs or officials independently of the settlement hierarchy.")
    religious_levels: tuple[SeshatValue, ...] = Field((), description="'Religious levels', Social Complexity variables › Hierarchical Complexity. levels. Same principle as with the previous variable. Start with the head of the official cult (if present) = level 1 and work down to the local priest.")
    military_levels: tuple[SeshatValue, ...] = Field((), description="'Military levels', Social Complexity variables › Hierarchical Complexity. levels. Again, start with the commander-in-chief = level 1 and work down to the private.")
    professional_military_officers: tuple[SeshatValue, ...] = Field((), description="'Professional military officers', Social Complexity variables › Professions. Full-time specialists absent/present/inferred present/inferred absent/uncoded/unknown")
    professional_soldiers: tuple[SeshatValue, ...] = Field((), description="'Professional soldiers', Social Complexity variables › Professions. Full-time specialists absent/present/inferred present/inferred absent/uncoded/unknown")
    professional_priesthood: tuple[SeshatValue, ...] = Field((), description="'Professional priesthood', Social Complexity variables › Professions. Full-time specialists absent/present/inferred present/inferred absent/uncoded/unknown")
    full_time_bureaucrats: tuple[SeshatValue, ...] = Field((), description="'Full-time bureaucrats', Social Complexity variables › Bureaucracy characteristics. Full-time administrative specialists absent/present/inferred present/inferred absent/uncoded/unknown. Code this absent if administrative duties are performed by generalists such as chiefs and subchiefs. Also code it absent if state officials perform multiple functions, e.g. combining administrative tasks with military duties. Note that this variable shouldn't be coded \"present\" only on the basis of the presence of specialized government buildings -- there must be some additional evidence of functional specialization in government.")
    examination_system: tuple[SeshatValue, ...] = Field((), description="'Examination system', Social Complexity variables › Bureaucracy characteristics. absent/present/inferred present/inferred absent/uncoded/unknown. The paradigmatic example is the Chinese imperial system.")
    merit_promotion: tuple[SeshatValue, ...] = Field((), description="'Merit promotion', Social Complexity variables › Bureaucracy characteristics. absent/present/inferred present/inferred absent/uncoded/unknown Code present if there are regular, institutionalized procedures for promotion based on performance. When exceptional individuals are promoted to the top ranks, in the absence of institutionalized procedures, we code it under institution and equity variables")
    specialized_government_buildings: tuple[SeshatValue, ...] = Field((), description="'Specialized government buildings', Social Complexity variables › Bureaucracy characteristics. absent/present/inferred present/inferred absent/uncoded/unknown. These buildings are where administrative officials are located, and must be distinct from the ruler's palace. They may be used for document storage, registration offices, minting money, etc. Defense structures also are not coded here (see Military). State-owned/operated workshop should also not be coded here.")
    formal_legal_code: tuple[SeshatValue, ...] = Field((), description="'Formal legal code', Social Complexity variables › Law. absent/present/inferred present/inferred absent/uncoded/unknown. Usually, but not always written down. If not written down, code it 'present' when a uniform legal system is established by oral transmission (e.g., officials are taught the rules, or the laws are announced in a public space). Provide a short description")
    judges: tuple[SeshatValue, ...] = Field((), description="'Judges', Social Complexity variables › Law. absent/present/inferred present/inferred absent/uncoded/unknown. This refers only to full-time professional judges")
    courts: tuple[SeshatValue, ...] = Field((), description="'Courts', Social Complexity variables › Law. absent/present/inferred present/inferred absent/uncoded/unknown. Buildings specialized for legal proceedings only.")
    professional_lawyers: tuple[SeshatValue, ...] = Field((), description="'Professional Lawyers', Social Complexity variables › Law. absent/present/inferred present/inferred absent/uncoded/unknown.")
    irrigation_systems: tuple[SeshatValue, ...] = Field((), description="'irrigation systems', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    drinking_water_supply_systems: tuple[SeshatValue, ...] = Field((), description="'drinking water supply systems', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    markets: tuple[SeshatValue, ...] = Field((), description="'markets', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    food_storage_sites: tuple[SeshatValue, ...] = Field((), description="'food storage sites', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    roads: tuple[SeshatValue, ...] = Field((), description="'Roads', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown. This variable refers to deliberately constructed roads that connect settlements or other sites. It excludes streets/accessways within settlements and paths between settlements that develop through repeated use.")
    bridges: tuple[SeshatValue, ...] = Field((), description="'Bridges', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    canals: tuple[SeshatValue, ...] = Field((), description="'Canals', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    ports: tuple[SeshatValue, ...] = Field((), description="'Ports', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown These include river ports. Direct historical or archaeological evidence of Ports is absent when no port has been excavated or all evidence of such has been obliterated. Indirect historical or archaeological data is absent when there is no evidence that suggests that the polity engaged in maritime or riverine trade, conflict, or transportation, such as evidence of merchant shipping, administrative records of customs duties, or evidence that at the same period of time a trading relation in the region had a port (for example, due to natural processes, there is little evidence of ancient ports in delta Egypt at a time we know there was a timber trade with the Levant). When evidence for the variable itself is available the code is 'present.' When other forms of evidence suggests the existence of the variable (or not) the code may be 'inferred present' (or 'inferred absent'). When indirect evidence is not available the code will be either absent, temporal uncertainty, suspected unknown, or unknown.")
    mines_or_quarries: tuple[SeshatValue, ...] = Field((), description="'Mines or quarries', Social Complexity variables › Specialized Buildings: polity owned. absent/present/inferred present/inferred absent/uncoded/unknown")
    nonwritten_records: tuple[SeshatValue, ...] = Field((), description="'Nonwritten records', Social Complexity variables › Information. Physical records that are more extensive than mnemonics, but don't utilize script. Example: quipu; seals and stamps")
    written_records: tuple[SeshatValue, ...] = Field((), description="'Written records', Social Complexity variables › Information. These are more than short and fragmentary inscriptions, such as found on tombs or runic stones. There must be several sentences strung together, at the very minimum. For example, royal proclamations from Mesopotamia and Egypt qualify as written records")
    script: tuple[SeshatValue, ...] = Field((), description="'Script', Social Complexity variables › Information. As indicated at least by fragmentary inscriptions (note that if written records are present, then so is script)")
    non_phonetic_writing: tuple[SeshatValue, ...] = Field((), description="'Non-phonetic writing', Social Complexity variables › Information. this refers to the kind of script")
    phonetic_alphabetic_writing: tuple[SeshatValue, ...] = Field((), description="'Phonetic alphabetic writing', Social Complexity variables › Information. this refers to the kind of script")
    lists_tables_and_classifications: tuple[SeshatValue, ...] = Field((), description="'Lists tables and classifications', Social Complexity variables › Information. The codebook lists it without a definition.")
    calendar: tuple[SeshatValue, ...] = Field((), description="'Calendar', Social Complexity variables › Information. The codebook lists it without a definition.")
    sacred_texts: tuple[SeshatValue, ...] = Field((), description="'Sacred Texts', Social Complexity variables › Information. Sacred Texts originate from supernatural agents (deities), or are directly inspired by them.")
    religious_literature: tuple[SeshatValue, ...] = Field((), description="'Religious literature', Social Complexity variables › Information. Religious literature differs from the sacred texts. For example, it may provide commentary on the sacred texts, or advice on how to live a virtuous life.")
    practical_literature: tuple[SeshatValue, ...] = Field((), description="'Practical literature', Social Complexity variables › Information. Texts written with the aim of providing guidance on a certain topic, for example manuals on agriculture, warfare, or cooking. Letters do not count as practical literature.")
    history: tuple[SeshatValue, ...] = Field((), description="'History', Social Complexity variables › Information. The codebook lists it without a definition.")
    philosophy: tuple[SeshatValue, ...] = Field((), description="'Philosophy', Social Complexity variables › Information. The codebook lists it without a definition.")
    fiction: tuple[SeshatValue, ...] = Field((), description="'Fiction', Social Complexity variables › Information. Include poetry here")
    articles: tuple[SeshatValue, ...] = Field((), description="'Articles', Social Complexity variables › Information. items that have both a regular use and are used as money (example: axes, cattle, measures of grain, ingots of non-precious metals)")
    tokens: tuple[SeshatValue, ...] = Field((), description="'Tokens', Social Complexity variables › Information. unlike articles, used only for exchange. unlike coins are not manufactured (example: cowries)")
    foreign_coins: tuple[SeshatValue, ...] = Field((), description="'Foreign coins', Social Complexity variables › Information. The codebook lists it without a definition.")
    indigenous_coins: tuple[SeshatValue, ...] = Field((), description="'Indigenous coins', Social Complexity variables › Information. The codebook lists it without a definition.")
    paper_currency: tuple[SeshatValue, ...] = Field((), description="'Paper currency', Social Complexity variables › Information. Or another kind of fiat money. Note that this only refers to indigenously produced paper currency. Code absent if colonial money is used.")
    couriers: tuple[SeshatValue, ...] = Field((), description="'Couriers', Social Complexity variables › Information. Full-time professional couriers.")
    postal_stations: tuple[SeshatValue, ...] = Field((), description="'Postal stations', Social Complexity variables › Information. Specialized buildings exclusively devoted to the postal service. If there is a special building that has other functions than a postal station, we still code postal station as present. The intent is to capture additional infrastructure beyond having a corps of messengers.")
    general_postal_service: tuple[SeshatValue, ...] = Field((), description="'General postal service', Social Complexity variables › Information. This refers to a postal service that not only serves the ruler's needs, but carries mail for private citizens.")
    scientific_literature: tuple[SeshatValue, ...] = Field((), description="'Scientific literature', Social Complexity variables › Information. Mathematics, natural sciences, social sciences")
    precious_metals: tuple[SeshatValue, ...] = Field((), description="'Precious metals', Social Complexity variables › Information. non-coined silver, gold, platinum")
    mnemonic_devices: tuple[SeshatValue, ...] = Field((), description="'Mnemonic devices', Social Complexity variables › Information. For example, tallies")
    copper: tuple[SeshatValue, ...] = Field((), description="'Copper', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    bronze: tuple[SeshatValue, ...] = Field((), description="'Bronze', Warfare variables › Military Technologies. Bronze is an alloy that includes copper, so a polity that uses bronze in warfare is familiar with copper technology and probably uses it to at least a limited extent. Consequently, if a culture uses bronze in warfare and there is no mention of using copper then 'inferred present' is probably best.")
    iron: tuple[SeshatValue, ...] = Field((), description="'Iron', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    steel: tuple[SeshatValue, ...] = Field((), description="'Steel', Warfare variables › Military Technologies. Steel is an alloy that includes iron, so a polity that uses bronze in warfare is familiar with copper technology and probably uses it to at least a limited extent. Consequently, if a culture uses steel in warfare and there is no mention of using iron then 'inferred present' is probably best.")
    javelins: tuple[SeshatValue, ...] = Field((), description="'Javelins', Warfare variables › Military Technologies. Includes thrown spears")
    atlatl: tuple[SeshatValue, ...] = Field((), description="'Atlatl', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    slings: tuple[SeshatValue, ...] = Field((), description="'Slings', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    self_bow: tuple[SeshatValue, ...] = Field((), description="'Self bow', Warfare variables › Military Technologies. This is a bow made from a single piece of wood (example: the English/Welsh longbow)")
    composite_bow: tuple[SeshatValue, ...] = Field((), description="'Composite bow', Warfare variables › Military Technologies. This is a bow made from several different materials, usually wood, horn, and sinew. Also known as laminated bow. Recurved bows should be coded here as well, because usually they are composite bows. When there is evidence for bows (or arrows) and no specific comment about how sophisticated the bows are then 'inferred present' for self bows and 'inferred absent' for composite bows is generally best (along with brief notes indicating that it is best to assume the less sophisticated rather than the more sophisticated technology is present).")
    crossbow: tuple[SeshatValue, ...] = Field((), description="'Crossbow', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    tension_siege_engines: tuple[SeshatValue, ...] = Field((), description="'Tension siege engines', Warfare variables › Military Technologies. For example, catapult, onager")
    sling_siege_engines: tuple[SeshatValue, ...] = Field((), description="'Sling siege engines', Warfare variables › Military Technologies. E.g., trebuchet, innclude mangonels here")
    gunpowder_siege_artillery: tuple[SeshatValue, ...] = Field((), description="'Gunpowder siege artillery', Warfare variables › Military Technologies. For example, cannon, mortars.")
    handheld_firearms: tuple[SeshatValue, ...] = Field((), description="'Handheld firearms', Warfare variables › Military Technologies. E.g., muskets, pistols, and rifles")
    war_clubs: tuple[SeshatValue, ...] = Field((), description="'War clubs', Warfare variables › Military Technologies. Includes maces")
    battle_axes: tuple[SeshatValue, ...] = Field((), description="'Battle axes', Warfare variables › Military Technologies. Axes designed for military use.")
    daggers: tuple[SeshatValue, ...] = Field((), description="'Daggers', Warfare variables › Military Technologies. Bladed weapons shorter than 50 cm. Includes knives. Material is not important (coded elsewhere), thus flint daggers should be coded as present.")
    swords: tuple[SeshatValue, ...] = Field((), description="'Swords', Warfare variables › Military Technologies. Bladed weapons longer than 50 cm. A machete is a sword (assuming the blade is probably longer than 50 cm). Material is not important (coded elsewhere), thus swords made from hard wood, or those edged with stones or bone should be coded as present.")
    spears: tuple[SeshatValue, ...] = Field((), description="'Spears', Warfare variables › Military Technologies. Includes lances and pikes. A trident is a spear.")
    polearms: tuple[SeshatValue, ...] = Field((), description="'Polearms', Warfare variables › Military Technologies. This category includes halberds, naginatas, and morning stars")
    dogs: tuple[SeshatValue, ...] = Field((), description="'Dogs', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    donkeys: tuple[SeshatValue, ...] = Field((), description="'Donkeys', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    horses: tuple[SeshatValue, ...] = Field((), description="'Horses', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    camels: tuple[SeshatValue, ...] = Field((), description="'Camels', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    wood_bark_etc: tuple[SeshatValue, ...] = Field((), description="'Wood bark etc', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    leather_cloth: tuple[SeshatValue, ...] = Field((), description="'Leather cloth', Warfare variables › Military Technologies. For example, leather cuirass, quilted cotton armor")
    shields: tuple[SeshatValue, ...] = Field((), description="'Shields', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    helmets: tuple[SeshatValue, ...] = Field((), description="'Helmets', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    breastplates: tuple[SeshatValue, ...] = Field((), description="'Breastplates', Warfare variables › Military Technologies. Armor made from wood, horn, or bone can be very important (as in the spread of the Asian War Complex into North America). Leather and cotton (in the Americas) armor was also effective against arrows and war clubs. Breastplate refers to any form of torso protection (in fact, we might rename this variable 'torso protection' at a later date). In the vast majority of cases you will probably find that if a culture has wooden armor, leather armor, chainmail armor, or scaled armor that breastplate should be coded as present because this is the most common location for armor. However, in theory, it is possible to have armor that doesn't protect the torso (for example, a culture might use armor that protects the limbs only).")
    limb_protection: tuple[SeshatValue, ...] = Field((), description="'Limb protection', Warfare variables › Military Technologies. E.g., greaves. Covering arms, or legs, or both.")
    scaled_armor: tuple[SeshatValue, ...] = Field((), description="'Scaled armor', Warfare variables › Military Technologies. Armor consisting of many individual small armor scales (plates) attached to a backing of cloth or leather. The scales don't need to be metal (i.e. they could be particularly rigid bits of leather, horn, bone, etc).")
    laminar_armor: tuple[SeshatValue, ...] = Field((), description="'Laminar armor', Warfare variables › Military Technologies. (also known as banded mail, example: lorica segmentata). Armor that is made from horizontal overlapping rows or bands of sold armor plates.")
    plate_armor: tuple[SeshatValue, ...] = Field((), description="'Plate armor', Warfare variables › Military Technologies. Armor made of iron or steel plates.")
    small_vessels_canoes_etc: tuple[SeshatValue, ...] = Field((), description="'Small vessels (canoes etc)', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    merchant_ships_pressed_into_service: tuple[SeshatValue, ...] = Field((), description="'Merchant ships pressed into service', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    specialized_military_vessels: tuple[SeshatValue, ...] = Field((), description="'Specialized military vessels', Warfare variables › Military Technologies. (such as galleys and sailing ships)")
    settlements_in_a_defensive_position: tuple[SeshatValue, ...] = Field((), description="'Settlements in a defensive position', Warfare variables › Military Technologies. Settlements in a location that was clearly chosen for defensive reasons. E.g. on a hill top, peninsula.")
    wooden_palisades: tuple[SeshatValue, ...] = Field((), description="'Wooden palisades', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    earth_ramparts: tuple[SeshatValue, ...] = Field((), description="'Earth ramparts', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    ditch: tuple[SeshatValue, ...] = Field((), description="'Ditch', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    moat: tuple[SeshatValue, ...] = Field((), description="'Moat', Warfare variables › Military Technologies. Differs from a ditch in that it has water")
    stone_walls_non_mortared: tuple[SeshatValue, ...] = Field((), description="'Stone walls (non-mortared)', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    stone_walls_mortared: tuple[SeshatValue, ...] = Field((), description="'Stone walls (mortared)', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    fortified_camps: tuple[SeshatValue, ...] = Field((), description="'Fortified camps', Warfare variables › Military Technologies. Camps made by armies on the move (e.g. on a campaign) that which could be constructed on a hill top or in the middle of a plain or desert, usually out of local materials.")
    complex_fortifications: tuple[SeshatValue, ...] = Field((), description="'Complex fortifications', Warfare variables › Military Technologies. When there are two or more concentric walls. So simply a wall and a donjon, for example, is not enough.")
    long_walls: tuple[SeshatValue, ...] = Field((), description="'Long walls', Warfare variables › Military Technologies. km. These are fortifications that were used not to protect a specific city or town, but a large territory. Examples include the Great Wall of China. Provide an estimate in km of the extent of the longest of such fortification systems. If not present, enter '0'. Very large circular walls protecting a settlement are not long walls - long walls are fairly linear and protect whole areas from incursions. If a polity inherits a stone wall from a previous one and continues to use and repair it, then we should probably code it as present.")
    modern_fortifications: tuple[SeshatValue, ...] = Field((), description="'Modern fortifications', Warfare variables › Military Technologies. used after the introduction of gunpowder, e.g., trace italienne/starfort.")
    elephants: tuple[SeshatValue, ...] = Field((), description="'Elephants', Warfare variables › Military Technologies. The codebook lists it without a definition.")
    chainmail: tuple[SeshatValue, ...] = Field((), description="'Chainmail', Warfare variables › Military Technologies. We’re using a broad definition of chainmail. Habergeon was the word used to describe the Chinese version and that would qualify as chainmail. Armor that is made of small metal rings linked together in a pattern to form a mesh.")
    elite_status_is_hereditary: tuple[SeshatValue, ...] = Field((), description="'elite status is hereditary', Social Mobility › Status. absent/present/unknown. Members of the ‘elite’ inherit their status and positions. If the ruler position is inherited most of the time, then these are sufficient grounds to code this variable as present")
    rulers_are_legitimated_by_gods: tuple[SeshatValue, ...] = Field((), description="'Rulers are legitimated by gods', Religion and Normative Ideology › Deification of Rulers. absent/present/unknown. For example, rulers are blessed by gods; the institution of kingship is ordained by heaven")
    rulers_are_gods: tuple[SeshatValue, ...] = Field((), description="'Rulers are gods', Religion and Normative Ideology › Deification of Rulers. absent/present/unknown.")
    ideological_reinforcement_of_equality: tuple[SeshatValue, ...] = Field((), description="'Ideological reinforcement of equality', Religion and Normative Ideology › Normative Ideological Aspects of Equity and Prosociality. absent/present/unknown. Religious doctrine, philosophical statements, or practice makes claims about equality. For instance, explicit statements by religious groups or influential philosophers that all humans are equal")
    ideological_thought_equates_rulers_and_commoners: tuple[SeshatValue, ...] = Field((), description="'Ideological thought equates rulers and commoners', Religion and Normative Ideology › Normative Ideological Aspects of Equity and Prosociality. absent/present/unknown")
    ideological_thought_equates_elites_and_commoners: tuple[SeshatValue, ...] = Field((), description="'Ideological thought equates elites and commoners', Religion and Normative Ideology › Normative Ideological Aspects of Equity and Prosociality. absent/present/unknown")
    ideology_reinforces_prosociality: tuple[SeshatValue, ...] = Field((), description="'Ideology reinforces prosociality', Religion and Normative Ideology › Normative Ideological Aspects of Equity and Prosociality. absent/present/unknown. Religious doctrine, philosophical statements, or practice makes claims about engaging in activity for the benefit of a wider community, for instance Christian traditions of alms-giving or Islamic sadaqah")
    production_of_public_goods: tuple[SeshatValue, ...] = Field((), description="'production of public goods', Religion and Normative Ideology › Normative Ideological Aspects of Equity and Prosociality. absent/present/unknown. Public Goods refer to anything that incurs cost to an individual or group of individuals, but that can be used or enjoyed by others who did not incur any of the cost, namely the public at large. They are non-excludable and non-rivalrous goods. Examples are roads, public drinking fountains, public parks or theatres, temples open to the public, etc.")
    moral_concern_is_primary: tuple[SeshatValue, ...] = Field((), description="'Moral concern is primary', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. Moralizing religion is described as ‘primary’ when the principal moral concerns of supernatural agents or forces pertain to cooperation in human affairs. It is coded as absent when the primary concern is the behavior of humans towards the supernatural realm, e.g. by discharging ritual obligations such as performing sacrifices, laying out offerings, etc.")
    moralizing_enforcement_is_certain: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement is certain', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This variable reflects the predictability of supernatural punishment for transgression or reward for ethical behavior. A code of absence here could result from a variety of characteristics of supernatural agents: if they are fickle or capricious, if they can be bought off or tricked, or, alternatively, if they are not independently concerned about human morality and need to be persuaded or induced to punish transgressions.")
    moralizing_norms_are_broad: tuple[SeshatValue, ...] = Field((), description="'Moralizing norms are broad', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This reflects how many aspects of morality deities care about and enforce. It is coded as absent when moralizing supernatural punishment/reward pertains to only very narrowly circumscribed domains, for example, kin-based moral precepts punishing incest or rewarding hospitality rather than enforcing moral norms across a broad range of social situations.")
    moralizing_enforcement_is_targeted: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement is targeted', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This reflects whether punishment and rewards are targeted specifically at culpable individuals. It is coded as absent when the whole group is punished rather than just the individual transgressor. This reflects whether punishment and rewards are targeted specifically at culpable individuals. It is coded as absent when the whole group is punished rather than just the individual transgressor.")
    moralizing_enforcement_of_rulers: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement of rulers', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This reflects whether supernatural forces or agents punish/reward rulers for their antisocial/prosocial behavior. It can be absent where such punishment is present generally, but rulers remain exempt.")
    moralizing_religion_adopted_by_elites: tuple[SeshatValue, ...] = Field((), description="'Moralizing religion adopted by elites', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This reflects whether elites of the polity subscribe to a religion with moralizing elements. In some cases, only a vocal segment of the elites advocated a particular moralizing religion (for example, early Buddhists, some Christians, Confucians) but not entire elite populations.")
    moralizing_religion_adopted_by_commoners: tuple[SeshatValue, ...] = Field((), description="'Moralizing religion adopted by commoners', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. This reflects the extent to which beliefs in a moralizing religion are adopted by the masses. A typical situation in which this variable is coded absent is when the state religion professed by rulers and elites, and endorsing beliefs in supernatural punishments and rewards, is different from the popular religion which lacks or professes only much weaker beliefs in supernatural enforcement. On the other hand, this variable might be coded as present, even while the Elites variable is coded absent, for example when popular religion emphasizes supernatural enforcement, but the religion of rulers and elites does not.")
    moralizing_enforcement_in_afterlife: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement in afterlife', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. Reflects whether punishment is delayed until after the death of the transgressor")
    moralizing_enforcement_in_this_life: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement in this life', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. Reflects whether punishment occurs during transgressor's lifetime")
    moralizing_enforcement_is_agentic: tuple[SeshatValue, ...] = Field((), description="'Moralizing enforcement is agentic', Religion and Normative Ideology › Moralizing Supernatural Powers. absent/present/unknown. Reflects whether punishment/reward is administered by a supernatural agent, such as a deity or spirit (as opposed to being administered by an impersonal supernatural force, such as karma).")
    constraint_on_executive_by_government: tuple[SeshatValue, ...] = Field((), description="'Constraint on executive by government', Institutional Variables › Limits on Power of the Chief Executive. absent/present/unknown. Governmental officials (i.e. judiciary/legislature) can veto or overturn executive decision (including removing a political appointment), or withhold cooperation (e.g., refuse to provide funds or allow raising troops), regardless of whether or not these limits were actually practiced. Explain in paragraph")
    constraint_on_executive_by_non_government: tuple[SeshatValue, ...] = Field((), description="'Constraint on executive by non-government', Institutional Variables › Limits on Power of the Chief Executive. absent/present/unknown. Non-governmental organization (elite, social group, community organization, economic group, etc.) can veto or overturn executive decision (including removing a political appointment), or withhold cooperation (e.g., refuse to provide funds or allow raising troops), regardless of whether or not these limits were actually practiced. Explain in paragraph. Note: this does not include religious groups (Church leaders, Buddhist monks, etc.), since that is coded elsewhere)")
    impeachment: tuple[SeshatValue, ...] = Field((), description="'Impeachment', Institutional Variables › Limits on Power of the Chief Executive. absent/present/unknown. There is a legal mechanism for removing and replacing the head of state")
