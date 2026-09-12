"""The Cultura data as it arrives, before anything is resolved.

This is the layer `datamodel.py` is built from. Every value is kept in the shape
and the spelling the query returned: a date is still '1937-04-11T00:00:00Z', a
label is still the RDF literal '"Boston"@en' with its quotes and its language
tag, a multi-valued property is still the list Wikidata sent. Nothing is parsed,
nothing is joined, nothing is chosen between.

Every field is named after the Wikidata property it holds, spelled as Wikidata
spells it: P569 is `date_of_birth`, P27 is `country_of_citizenship`, P21 is
`sex_or_gender`. Reading a field name tells you which property to look up, and
a field that does not correspond to a property says so in its description.

Because everything here comes from Wikidata, `Value.source` is a Wikidata and
not a union at all: nothing at this stage is derived, answered by a language
model, or taken from another dataset. It is declared here rather than imported
from the curated model, so this file stands on its own and can drift from it —
the two layers describe different stages and are not obliged to agree.

Two sets of raw files are deliberately not modelled here, because they are not
Wikidata and the guarantee above would stop being true: the reverse-geocoder
outputs — city_modern_countries, nationality_modern_countries, with their
geocoder_cc and geocoder_name columns — and Cliopatria, which arrives as its
own GeoJSON and gets the last two models in this file.
"""

from datetime import date

from pydantic import BaseModel, Field


class WikidataEntity(BaseModel):
    qid: str = Field(..., description="The Wikidata item, e.g. 'Q937'.")
    label_en: str | None = Field(None, description="English label of that item, as the literal '\"Boston\"@en' — quotes and language tag included, because that is how it arrived.")
    description_en: str | None = Field(None, description="English one-line description of that item, as a literal.")


class WikidataProperty(BaseModel):
    pid: str = Field(..., description="Wikidata property the value was read from, e.g. 'P569'. Non-property sources keep their RDF term, e.g. 'rdfs:label'.")
    label_en: str | None = Field(None, description="English label of that property, e.g. 'date of birth'. Every field in this file is named after it.")
    definition: str | None = Field(None, description="What that property means, e.g. 'date on which the subject was born'.")


class Wikidata(BaseModel):
    date_of_extraction: date = Field(..., description="Day the query was run. Mandatory: Wikidata is edited continuously, so an undated value cannot be reproduced.")
    entity: WikidataEntity | None = Field(None, description="The item the value is or points at.")
    property: WikidataProperty | None = Field(None, description="The property the value was read from.")


class Value(BaseModel):
    value: str | int | float | bool | None = Field(None, description="One value, spelled as the query returned it. A date keeps its Wikidata stamp, '1937-04-11T00:00:00Z'; a label keeps its RDF literal form, '\"Boston\"@en'; an item is its bare qid.")
    source: Wikidata = Field(..., description="Which property it was read from, and which item it points at when it points at one. Always a Wikidata source here.")


class Values(BaseModel):
    values: tuple[str, ...] = Field((), description="Several values for one property, in the order Wikidata listed them. Kept as a list rather than pipe-joined, because that is how the extraction received them.")
    source: Wikidata = Field(..., description="The property they were all read from.")


class Sitelink(BaseModel):
    site: str | None = Field(None, description="The edition's host, e.g. 'ar.wikipedia.org'.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped.")
    url: str | None = Field(None, description="The article's URL, percent-encoded as Wikidata gives it.")


class WorkCredit(BaseModel):
    work: str | None = Field(None, description="The work's qid.")
    property: str | None = Field(None, description="The credit property that links the individual to it — 'P50' for author, 'P170' for creator, 'P175' for performer. It is not resolved to a role name here.")


class IndividualWikidata(BaseModel):
    qid: str = Field(..., description="The individual's Wikidata item. It is the key every raw file is indexed by, and the only field on this row that is not a Value.")
    label: Value | None = Field(None, description="rdfs:label, as the literal '\"Claus Hammel\"@en'.")
    description: Value | None = Field(None, description="schema:description, as a literal. Some carry mojibake from the extraction — an en dash decoded twice — which is the kind of thing this layer exists to keep visible.")
    date_of_birth: Value | None = Field(None, description="P569, as '1860-02-21T00:00:00Z'. The stamp is Wikidata's, not a real time of day.")
    date_of_birth_precision: Value | None = Field(None, description="Precision of P569's time value: 11 for a day, 9 for a year, 7 for a century. Not a property of its own — it is part of the time value — and it arrives in its own file, so a date and its precision can be present without each other.")
    date_of_death: Value | None = Field(None, description="P570, in the same form.")
    date_of_death_precision: Value | None = Field(None, description="Precision of P570's time value.")
    floruit: Value | None = Field(None, description="P1317, in the same form.")
    floruit_precision: Value | None = Field(None, description="Precision of P1317's time value.")
    place_of_birth: Value | None = Field(None, description="P19, as the place's bare qid. Its label rides in the source, still as a literal. Resolve it against PlaceWikidata.")
    place_of_death: Value | None = Field(None, description="P20, in the same form.")
    sex_or_gender: Value | None = Field(None, description="P21, as a qid. Free vocabulary: 48 distinct values in the data.")
    occupation: Values | None = Field(None, description="P106, a list of qids. Unresolved: the labels are in OccupationWikidata.")
    country_of_citizenship: Values | None = Field(None, description="P27, a list of qids, each with its label in the source. Resolve them against CountryWikidata.")
    writing_language: Values | None = Field(None, description="P6886, a list of qids.")
    external_id: tuple[Value, ...] = Field((), description="One entry per external database, the identifier as its value and the property that carries it in its source — P214 for VIAF, P227 for GND. Wikidata has 10 329 external-id properties; which database this is, is the property and nothing else.")
    sitelink: tuple[Sitelink, ...] = Field((), description="schema:about — every Wikipedia article about the individual, one per language edition, up to 228 per person.")
    work: tuple[WorkCredit, ...] = Field((), description="Every work credited to the individual, as a pair of the work's qid and the property that credits them. Neither is resolved here; the labels are in WorkWikidata.")


class PlaceWikidata(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, as P19 and P20 name it.")
    label: Value | None = Field(None, description="rdfs:label. Unlike the individual files, place_locations gives it already unquoted.")
    latitude: Value | None = Field(None, description="The latitude half of P625 'coordinate location'. The property has two components and the extraction splits them, which is why this field cannot carry the property's own name.")
    longitude: Value | None = Field(None, description="The longitude half of P625.")
    country: Value | None = Field(None, description="P17, as a qid, with its label in the source. This is what Wikidata declares — for a historical place, often a historical country.")
    instance_of: Values | None = Field(None, description="P31, the classes of the place — 'seaside resort', 'quarter', 'hospital'. This is what a language model later reads to decide whether the place is a settlement at all.")


class CountryWikidata(BaseModel):
    qid: str = Field(..., description="The country's Wikidata item, as P27 names it.")
    label: Value | None = Field(None, description="rdfs:label.")
    latitude: Value | None = Field(None, description="The latitude half of P625.")
    longitude: Value | None = Field(None, description="The longitude half of P625.")
    country: Value | None = Field(None, description="P17, for an entity that is inside another country rather than one itself.")
    continent: Value | None = Field(None, description="P30, as a qid with its label in the source.")
    iso_3166_1_alpha_3_code: Value | None = Field(None, description="P298. Only a country that exists today has one, which is how a historical entity is told apart from a modern one without asking a geocoder.")
    sitelink: tuple[Sitelink, ...] = Field((), description="schema:about. The English one is what matches a country to a Cliopatria polity.")


class OccupationWikidata(BaseModel):
    qid: str = Field(..., description="The occupation's Wikidata item, as P106 names it.")
    label: Value | None = Field(None, description="rdfs:label, as the literal '\"insurance expert\"@en'.")
    subclass_of: Values | None = Field(None, description="P279. The closure over this is what decides whether an occupation is reachable from Q901 'scientist' or Q483501 'artist'.")


class WorkWikidata(BaseModel):
    qid: str = Field(..., description="The work's Wikidata item, as the credit properties name it. A few keys in the raw file are lexeme URIs rather than qids.")
    label: Value | None = Field(None, description="rdfs:label. The work labels file gives it already unquoted, unlike the individual labels.")
    instance_of: Values | None = Field(None, description="P31, the classes of the work — 'painting', 'film', 'novel'.")
    inception: Value | None = Field(None, description="P571, as a Wikidata time stamp.")
    inception_precision: Value | None = Field(None, description="Precision of P571's time value.")
    publication_date: Value | None = Field(None, description="P577, as a Wikidata time stamp.")
    publication_date_precision: Value | None = Field(None, description="Precision of P577's time value.")


class Territory(BaseModel):
    from_year: int | None = Field(None, description="First year of the span, as Cliopatria names the column. Negative before the common era.")
    to_year: int | None = Field(None, description="Last year of the span.")
    area: float | None = Field(None, description="Area in square kilometres, as published — an unrounded float, 64105.809261435774.")
    geometry: str | None = Field(None, description="The GeoJSON geometry as a string, Polygon or MultiPolygon, not parsed. It is the heaviest thing in the whole pipeline.")


class PolityCliopatria(BaseModel):
    id: int | None = Field(None, description="Cliopatria's own identifier. Not a qid: this dataset numbers its polities itself.")
    name: str | None = Field(None, description="Name as Cliopatria spells it, e.g. 'Magadha - Shaishunaga dynasty' — its own spelling, not Wikidata's.")
    type: str | None = Field(None, description="'POLITY' or 'RELATION', as published.")
    wikipedia_url: str | None = Field(None, description="English Wikipedia URL, which is how the dataset is matched to Wikidata items and to places.")
    wikidata_id: str | None = Field(None, description="The qid Cliopatria resolved for the polity, where it resolved one. This is the only place this dataset touches Wikidata.")
    territories: tuple[Territory, ...] = Field((), description="One entry per change of borders, as the GeoJSON features come. A polity averages 16 and one reaches 212.")
