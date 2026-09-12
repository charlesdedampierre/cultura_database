"""The Cultura data as Wikidata returns it, before anything is resolved.

This is the layer `datamodel.py` is built from. Every value is kept in the shape
and the spelling the query returned: a date is still '1937-04-11T00:00:00Z', a
label is still the RDF literal '"Boston"@en' with its quotes and its language
tag, a multi-valued property is still the list Wikidata sent. Nothing is parsed,
nothing is joined, nothing is chosen between.

No value carries its provenance here, because at this stage every value has the
same one: it was read from Wikidata, from the property the field is named after.
`date_of_birth` is P569 and nothing else. What each property means is in
`Property`, one row per property, loaded from properties.json — so a field name
is the whole join, and P569's definition is stored once rather than on every
one of thirteen million rows.

The join is the property's label, lowercased, with every run of non-alphanumeric
characters turned into a single underscore: 'date of birth' gives date_of_birth,
'ISO 3166-1 alpha-3 code' gives iso_3166_1_alpha_3_code. A field that has no
property behind it says so in its own description — the qid is a key, a
precision is part of a time value, and external_id and work are maps keyed by
property rather than values of one.

The extraction date is not on these rows either. A raw file is one query run, so
the date belongs to the run: sources.json records it, and the curated model puts
it back on each value once several sources start disagreeing.
"""

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
    label: str | None = Field(None, description="rdfs:label, as the literal '\"Claus Hammel\"@en'.")
    description: str | None = Field(None, description="schema:description, as a literal. Some carry mojibake from the extraction — an en dash decoded twice — which is the kind of thing this layer exists to keep visible.")
    date_of_birth: str | None = Field(None, description="P569, as '1860-02-21T00:00:00Z'. The stamp is Wikidata's, not a real time of day.")
    date_of_birth_precision: int | None = Field(None, description="Precision of P569's time value: 11 for a day, 9 for a year, 7 for a century. Not a property of its own — it is part of the time value — and it arrives in its own file, so a date and its precision can be present without each other.")
    date_of_death: str | None = Field(None, description="P570, in the same form.")
    date_of_death_precision: int | None = Field(None, description="Precision of P570's time value.")
    floruit: str | None = Field(None, description="P1317, in the same form.")
    floruit_precision: int | None = Field(None, description="Precision of P1317's time value.")
    place_of_birth: str | None = Field(None, description="P19, as the place's bare qid. Resolve it against PlaceWikidata.")
    place_of_death: str | None = Field(None, description="P20, in the same form.")
    sex_or_gender: str | None = Field(None, description="P21, as a qid. Free vocabulary: 48 distinct values in the data.")
    occupation: tuple[str, ...] = Field((), description="P106, a list of qids in the order Wikidata listed them. Resolve them against OccupationWikidata.")
    country_of_citizenship: tuple[str, ...] = Field((), description="P27, a list of qids. Resolve them against CountryWikidata.")
    writing_language: tuple[str, ...] = Field((), description="P6886, a list of qids.")
    external_id: dict[str, str] = Field({}, description="A map of property to identifier, exactly as the raw file gives it: {'P214': '7007870'}. Which database it is, is the property and nothing else — Wikidata has 10 329 external-id properties, and Property holds what each one is.")
    sitelink: tuple[Sitelink, ...] = Field((), description="schema:about — every Wikipedia article about the individual, one per language edition, up to 228 per person.")
    work: tuple[WorkCredit, ...] = Field((), description="Every work credited to the individual, as a pair of the work's qid and the property that credits them. Neither is resolved here; the labels are in WorkWikidata.")


class PlaceWikidata(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, as P19 and P20 name it.")
    label: str | None = Field(None, description="rdfs:label. Unlike the individual files, place_locations gives it already unquoted.")
    latitude: float | None = Field(None, description="The latitude half of P625 'coordinate location'. The property has two components and the extraction splits them, which is why this field cannot carry the property's own name.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = Field(None, description="P17, as a qid. This is what Wikidata declares — for a historical place, often a historical country.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the place, as qids — 'seaside resort', 'quarter', 'hospital'. This is what a language model later reads to decide whether the place is a settlement at all.")


class CountryWikidata(BaseModel):
    qid: str = Field(..., description="The country's Wikidata item, as P27 names it.")
    label: str | None = Field(None, description="rdfs:label.")
    latitude: float | None = Field(None, description="The latitude half of P625.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = Field(None, description="P17, for an entity that is inside another country rather than one itself.")
    continent: str | None = Field(None, description="P30, as a qid.")
    iso_3166_1_alpha_3_code: str | None = Field(None, description="P298. Only a country that exists today has one, which is how a historical entity is told apart from a modern one without asking a geocoder.")
    sitelink: tuple[Sitelink, ...] = Field((), description="schema:about. The English one is what matches a country to a historical polity.")


class OccupationWikidata(BaseModel):
    qid: str = Field(..., description="The occupation's Wikidata item, as P106 names it.")
    label: str | None = Field(None, description="rdfs:label, as the literal '\"insurance expert\"@en'.")
    subclass_of: tuple[str, ...] = Field((), description="P279, as qids. The closure over this is what decides whether an occupation is reachable from Q901 'scientist' or Q483501 'artist'.")


class WorkWikidata(BaseModel):
    qid: str = Field(..., description="The work's Wikidata item, as the credit properties name it. A few keys in the raw file are lexeme URIs rather than qids.")
    label: str | None = Field(None, description="rdfs:label. The work labels file gives it already unquoted, unlike the individual labels.")
    instance_of: tuple[str, ...] = Field((), description="P31, the classes of the work, as qids — 'painting', 'film', 'novel'.")
    inception: str | None = Field(None, description="P571, as a Wikidata time stamp.")
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    publication_date: str | None = Field(None, description="P577, as a Wikidata time stamp.")
    publication_date_precision: int | None = Field(None, description="Precision of P577's time value.")
