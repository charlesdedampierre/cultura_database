from pydantic import BaseModel, ConfigDict, Field


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
    label_language: str | None = Field(None, description="Language of `label`: 'en' from all_human_names.json, or the language missing_labels.json recovered it in.")
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
    sitelink: tuple[Sitelink, ...] = Field((), description="Its English Wikipedia article, from place_sitelinks.json.")


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
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    read_from_issuer: tuple[str, ...] = Field((), description="The fields above read from the issuer's item because the property states none.")


class PolityWikidata(BaseModel):
    qid: str = Field(..., description="The polity's Wikidata item, as Cliopatria resolved it.")
    inception: str | None = Field(None, description="P571, the most precise one where several are stated.")
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    dissolution: str | None = Field(None, description="P576, on the same terms.")
    dissolution_precision: int | None = Field(None, description="Precision of P576's time value.")


class WikimediaSiteWikidata(BaseModel):
    url: str = Field(..., description="The site's address, 'https://fr.wikipedia.org', as P856 of its item.")
    qid: str | None = Field(None, description="The site's own Wikidata item, 'Q8447' for the French Wikipedia.")
    label: str | None = Field(None, description="Its English label, 'French Wikipedia'.")
    language: str | None = Field(None, description="P407, the language it is written in, as a qid.")


class PolityModernCountry(BaseModel):
    polity_id: int | None = Field(None, description="The Cliopatria polity, by its integer id. Several rows share one: a historical polity's ground is in 1.4 modern countries on average.")
    country_qid: str | None = Field(None, description="A country holding that ground today, as a qid. Join it to CountryWikidata.")
    iso_a3_code: str | None = Field(None, description="ISO 3166-1 alpha-3 code of that country.")
    continent: str | None = Field(None, description="P30 of that country, by name.")
    sources: str | None = Field(None, description="The Wikidata property paths that produced the mapping, pipe-joined: 'P17', 'P36/P17', 'P1366/P17'. A path of P36/P17 means the polity was matched through its capital's country rather than directly, which is a weaker claim, and this column is the only place that shows it.")


class SeshatVariable(BaseModel):
    section: str = Field(..., description="'Section' as the Equinox file gives it, 'Warfare variables'. Only the variables Equinox codes are kept — 145 of the codebook's 1 555 — each under the section and subsection where most of its rows sit, so the clerical strays (a Copper row with no subsection) do not make variables of their own.")
    subsection: str | None = Field(None, description="'Subsection' as the Equinox file gives it, 'Military Technologies'. Empty for the variables Equinox files directly under a section, such as RA or Capital.")
    name: str = Field(..., description="'Variable' as the Equinox file gives it, 'Polity territory'. With section and subsection it is the key: RA recurs once per section, Duration once for the polity and once per ritual. It is also the comment on the matching seshat_information column, which is how a column finds its definition.")
    definition: str | None = Field(None, description="The text the Legacy Codebook (Equinox) gives after ♥ for this variable, in its own wording: the allowed codes ('absent/present/unknown'), the unit ('in squared kilometers'), or a definition. Matched on the name, under the codebook heading that bears the subsection or section. Empty where the codebook lists the variable without one.")
    notes: str | None = Field(None, description="The codebook lines that follow the definition up to the next variable or heading, such as the meaning of each code of 'Degree of centralization'. Taken as they fall in the file, so an introduction to the next group of variables can land here.")


class SeshatValue(BaseModel):
    value_from: str | int | None = Field(None, description="'Value.From', the coded value as published: a presence code ('present', 'inferred absent', 'suspected unknown' — the codebook's coding conventions define each), a number, or a name. Numbers arrive as integers, everything else as text. When value_note is 'range' it is the lower bound.")
    value_to: str | int | None = Field(None, description="'Value.To', the upper bound of a range — Polity Population 50000 to 60000. Filled only when value_note is 'range', on 1 126 of 47 477 rows.")
    date_from: str | None = Field(None, description="'Date.From', with the era glued to the year: '115BCE', '1300CE'. Empty on 46 031 rows, where the value holds for the polity's whole span. Filled without date_to, it dates the value to that single year — how a changing Polity territory is published.")
    date_to: str | None = Field(None, description="'Date.To', same format. The codebook puts uncertainty on values, never on dates, so a date here is always exact.")
    fact_type: str | None = Field(None, description="'Fact.Type', 'simple' or 'complex'. A complex row is always one of several the coder's single entry was split into — the items of a list, or a value that changed over dated periods. Simple rows can share a variable too: that is how an uncertain or disputed value is published.")
    value_note: str | None = Field(None, description="'Value.Note': 'simple'; 'list', one item of a list; 'range', see value_to; 'uncertain', the codebook's [a; b] — one row per extreme, the coder cannot tell which held; 'disputed', the codebook's {a; b} — one row per expert opinion. An uncertain or disputed variable has more than one value and none of them is the answer.")
    date_note: str | None = Field(None, description="'Date.Note': 'range' when date_to is filled, empty otherwise.")


class SeshatPolity(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    polity_long_name: str | None = Field(None, description="'polity_long_name', 'Abbasid Caliphate I'.")
    id: int | None = Field(None, description="'id', the polity's number on seshat-db.com — the n of seshat-db.com/core/polity/n. 864 polities, the whole of Seshat's list on 2026-09-29, not only the 373 Equinox codes.")
    url: str | None = Field(None, description="'url', the polity's page on seshat-db.com. The page is where the new and old ids stand side by side, 'af_durrani_emp / AfDurrn'; the API returns only the new one.")
    macro_region: str | None = Field(None, description="'macro_region', 'Southwest Asia'.")
    home_seshat_region: str | None = Field(None, description="'home_seshat_region', a region inside the macro region, 'Mesopotamia'.")
    polity_new_id: str | None = Field(None, description="'polity_new_ID', the id Seshat uses today, 'af_durrani_emp'. It is the form Cliopatria's SeshatID takes, so it is the join to PolityCliopatria.seshat_id: 540 of Cliopatria's 546 distinct ids are here. Cliopatria sometimes packs two in one field, 'de_empire_2;it_sicily_k_2', which must be split first.")
    polity_old_id: str | None = Field(None, description="'polity_old_ID', the id Equinox uses, 'AfDurrn', which SeshatInformation.seshat_polity carries. On 313 polities it simply repeats the new id — mostly those added after Equinox, which never had an old one, but also 36 tagged Equinox 2020.")
    start_year: int | None = Field(None, description="'start_year', negative before the common era.")
    end_year: int | None = Field(None, description="'end_year'.")
    home_nga: str | None = Field(None, description="'home_nga', the Natural Geographic Area the polity was sampled from. Filled on 376 of 864: only the polities of the NGA sample have one.")
    g: bool | None = Field(None, alias="g (General Variables)", description="'G', whether the polity has General Variables coded. This and the seven flags below are the section badges of Seshat's polity list; their meanings come from the tooltips there. Each flag is stored under its code and meaning, 'g (General Variables)', so a record reads without this model.")
    sc: bool | None = Field(None, alias="sc (Social Complexity Variables)", description="'SC', Social Complexity Variables.")
    wf: bool | None = Field(None, alias="wf (Warfare Variables)", description="'WF', Warfare Variables (MilTech).")
    rt: bool | None = Field(None, alias="rt (Religion Variables)", description="'RT', Religion Variables.")
    hs: bool | None = Field(None, alias="hs (Human Sacrifice)", description="'HS', Human Sacrifice. The site's tooltips do not name it; the meaning is inferred from the data: the 323 polities flagged are exactly those in Seshat's rt/human-sacrifices API.")
    cc: bool | None = Field(None, alias="cc (Crisis Consequences)", description="'CC', Crisis Consequences.")
    pt: bool | None = Field(None, alias="pt (Power Transition)", description="'PT', Power Transition.")
    in_: bool | None = Field(None, alias="in (Instability Events)", description="'IN', Instability Events. The field is in_ in Python because 'in' is a keyword; the stored key is the alias.")
    polity_tag: str | None = Field(None, description="'polity_tag', the batch the polity was added in: 'Equinox 2020 Polities' on 564, 'Other Polities' on 200, and 'NEW ... Polities' for regional additions.")
    shapefile_name: str | None = Field(None, description="'shapefile_name', the name of the polity's shape in Seshat's own maps, 'Aghlabid Dynasty'. Filled on 81.")


class SeshatInformation(BaseModel):
    seshat_polity: SeshatPolity = Field(..., description="The polity, as its entry in Seshat's polity list: the Equinox 'Polity' id is its polity_old_id, the Equinox 'NGA' its home_nga. It is the key: 373 polities, 46 to 167 coded rows each, and polity_new_id is the id Cliopatria's SeshatID uses. GbEmpr2, InGurjr and InKanau are missing from the list, so their entry holds only polity_old_id and home_nga, both taken from Equinox. Equinox's NGA is the one the polity was sampled in, which is not always its home: for IrSeleu it is Susiana, for JpNara* Kansai, and those two are lost. The raw file is long, one row per coded value; every field below gathers the rows of one 'Variable', and the file's 'Section' and 'Subsection' are dropped because the variable implies them. What each variable means is in SeshatVariable. The few rows filed elsewhere are clerical: 115 Warfare rows with no subsection, 14 ideology rows under a misspelled or wrong subsection.")
    ra: dict[str, tuple[str, ...]] = Field({}, description="'RA', the research assistants who coded the polity, keyed by the section they coded: {'Warfare variables': ('Enrico Cioni',)}. The file repeats RA once per section, so it is a map rather than a list.")
    ritual_duration: dict[str, tuple[SeshatValue, ...]] = Field({}, description="'Duration' as published under the ritual subsections — 'Most euphoric collective ritual of the official cult' — and filed under Warfare variables. It is the duration of the ritual in hours, not of the polity, so it cannot share the duration field. Six rows in the whole file.")
    original_name: tuple[SeshatValue, ...] = ()
    alternative_names: tuple[SeshatValue, ...] = ()
    peak_date: tuple[SeshatValue, ...] = ()
    duration: tuple[SeshatValue, ...] = ()
    degree_of_centralization: tuple[SeshatValue, ...] = ()
    supra_polity_relations: tuple[SeshatValue, ...] = ()
    preceding_quasi_polity: tuple[SeshatValue, ...] = ()
    relationship_to_preceding_quasi_polity: tuple[SeshatValue, ...] = ()
    succeeding_quasi_polity: tuple[SeshatValue, ...] = ()
    capital: tuple[SeshatValue, ...] = ()
    language: tuple[SeshatValue, ...] = ()
    supracultural_entity: tuple[SeshatValue, ...] = ()
    scale_of_supra_cultural_interaction: tuple[SeshatValue, ...] = ()
    polity_territory: tuple[SeshatValue, ...] = ()
    polity_population: tuple[SeshatValue, ...] = ()
    population_of_the_largest_settlement: tuple[SeshatValue, ...] = ()
    settlement_hierarchy: tuple[SeshatValue, ...] = ()
    administrative_levels: tuple[SeshatValue, ...] = ()
    religious_levels: tuple[SeshatValue, ...] = ()
    military_levels: tuple[SeshatValue, ...] = ()
    professional_military_officers: tuple[SeshatValue, ...] = ()
    professional_soldiers: tuple[SeshatValue, ...] = ()
    professional_priesthood: tuple[SeshatValue, ...] = ()
    full_time_bureaucrats: tuple[SeshatValue, ...] = ()
    examination_system: tuple[SeshatValue, ...] = ()
    merit_promotion: tuple[SeshatValue, ...] = ()
    specialized_government_buildings: tuple[SeshatValue, ...] = ()
    formal_legal_code: tuple[SeshatValue, ...] = ()
    judges: tuple[SeshatValue, ...] = ()
    courts: tuple[SeshatValue, ...] = ()
    professional_lawyers: tuple[SeshatValue, ...] = ()
    irrigation_systems: tuple[SeshatValue, ...] = ()
    drinking_water_supply_systems: tuple[SeshatValue, ...] = ()
    markets: tuple[SeshatValue, ...] = ()
    food_storage_sites: tuple[SeshatValue, ...] = ()
    roads: tuple[SeshatValue, ...] = ()
    bridges: tuple[SeshatValue, ...] = ()
    canals: tuple[SeshatValue, ...] = ()
    ports: tuple[SeshatValue, ...] = ()
    mines_or_quarries: tuple[SeshatValue, ...] = ()
    nonwritten_records: tuple[SeshatValue, ...] = ()
    written_records: tuple[SeshatValue, ...] = ()
    script: tuple[SeshatValue, ...] = ()
    non_phonetic_writing: tuple[SeshatValue, ...] = ()
    phonetic_alphabetic_writing: tuple[SeshatValue, ...] = ()
    lists_tables_and_classifications: tuple[SeshatValue, ...] = ()
    calendar: tuple[SeshatValue, ...] = ()
    sacred_texts: tuple[SeshatValue, ...] = ()
    religious_literature: tuple[SeshatValue, ...] = ()
    practical_literature: tuple[SeshatValue, ...] = ()
    history: tuple[SeshatValue, ...] = ()
    philosophy: tuple[SeshatValue, ...] = ()
    fiction: tuple[SeshatValue, ...] = ()
    articles: tuple[SeshatValue, ...] = ()
    tokens: tuple[SeshatValue, ...] = ()
    foreign_coins: tuple[SeshatValue, ...] = ()
    indigenous_coins: tuple[SeshatValue, ...] = ()
    paper_currency: tuple[SeshatValue, ...] = ()
    couriers: tuple[SeshatValue, ...] = ()
    postal_stations: tuple[SeshatValue, ...] = ()
    general_postal_service: tuple[SeshatValue, ...] = ()
    scientific_literature: tuple[SeshatValue, ...] = ()
    precious_metals: tuple[SeshatValue, ...] = ()
    mnemonic_devices: tuple[SeshatValue, ...] = ()
    copper: tuple[SeshatValue, ...] = ()
    bronze: tuple[SeshatValue, ...] = ()
    iron: tuple[SeshatValue, ...] = ()
    steel: tuple[SeshatValue, ...] = ()
    javelins: tuple[SeshatValue, ...] = ()
    atlatl: tuple[SeshatValue, ...] = ()
    slings: tuple[SeshatValue, ...] = ()
    self_bow: tuple[SeshatValue, ...] = ()
    composite_bow: tuple[SeshatValue, ...] = ()
    crossbow: tuple[SeshatValue, ...] = ()
    tension_siege_engines: tuple[SeshatValue, ...] = ()
    sling_siege_engines: tuple[SeshatValue, ...] = ()
    gunpowder_siege_artillery: tuple[SeshatValue, ...] = ()
    handheld_firearms: tuple[SeshatValue, ...] = ()
    war_clubs: tuple[SeshatValue, ...] = ()
    battle_axes: tuple[SeshatValue, ...] = ()
    daggers: tuple[SeshatValue, ...] = ()
    swords: tuple[SeshatValue, ...] = ()
    spears: tuple[SeshatValue, ...] = ()
    polearms: tuple[SeshatValue, ...] = ()
    dogs: tuple[SeshatValue, ...] = ()
    donkeys: tuple[SeshatValue, ...] = ()
    horses: tuple[SeshatValue, ...] = ()
    camels: tuple[SeshatValue, ...] = ()
    wood_bark_etc: tuple[SeshatValue, ...] = ()
    leather_cloth: tuple[SeshatValue, ...] = ()
    shields: tuple[SeshatValue, ...] = ()
    helmets: tuple[SeshatValue, ...] = ()
    breastplates: tuple[SeshatValue, ...] = ()
    limb_protection: tuple[SeshatValue, ...] = ()
    scaled_armor: tuple[SeshatValue, ...] = ()
    laminar_armor: tuple[SeshatValue, ...] = ()
    plate_armor: tuple[SeshatValue, ...] = ()
    small_vessels_canoes_etc: tuple[SeshatValue, ...] = ()
    merchant_ships_pressed_into_service: tuple[SeshatValue, ...] = ()
    specialized_military_vessels: tuple[SeshatValue, ...] = ()
    settlements_in_a_defensive_position: tuple[SeshatValue, ...] = ()
    wooden_palisades: tuple[SeshatValue, ...] = ()
    earth_ramparts: tuple[SeshatValue, ...] = ()
    ditch: tuple[SeshatValue, ...] = ()
    moat: tuple[SeshatValue, ...] = ()
    stone_walls_non_mortared: tuple[SeshatValue, ...] = ()
    stone_walls_mortared: tuple[SeshatValue, ...] = ()
    fortified_camps: tuple[SeshatValue, ...] = ()
    complex_fortifications: tuple[SeshatValue, ...] = ()
    long_walls: tuple[SeshatValue, ...] = ()
    modern_fortifications: tuple[SeshatValue, ...] = ()
    elephants: tuple[SeshatValue, ...] = ()
    chainmail: tuple[SeshatValue, ...] = ()
    elite_status_is_hereditary: tuple[SeshatValue, ...] = ()
    rulers_are_legitimated_by_gods: tuple[SeshatValue, ...] = ()
    rulers_are_gods: tuple[SeshatValue, ...] = ()
    ideological_reinforcement_of_equality: tuple[SeshatValue, ...] = ()
    ideological_thought_equates_rulers_and_commoners: tuple[SeshatValue, ...] = ()
    ideological_thought_equates_elites_and_commoners: tuple[SeshatValue, ...] = ()
    ideology_reinforces_prosociality: tuple[SeshatValue, ...] = ()
    production_of_public_goods: tuple[SeshatValue, ...] = ()
    moral_concern_is_primary: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_is_certain: tuple[SeshatValue, ...] = ()
    moralizing_norms_are_broad: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_is_targeted: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_of_rulers: tuple[SeshatValue, ...] = ()
    moralizing_religion_adopted_by_elites: tuple[SeshatValue, ...] = ()
    moralizing_religion_adopted_by_commoners: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_in_afterlife: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_in_this_life: tuple[SeshatValue, ...] = ()
    moralizing_enforcement_is_agentic: tuple[SeshatValue, ...] = ()
    constraint_on_executive_by_government: tuple[SeshatValue, ...] = ()
    constraint_on_executive_by_non_government: tuple[SeshatValue, ...] = ()
    impeachment: tuple[SeshatValue, ...] = ()
