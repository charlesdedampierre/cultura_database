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

A field that joins to a property carries no description: the property says what
it means. What the property cannot say is how this project received it, and
these are the seven places where the two differ.

    date_of_birth, date_of_death, floruit
        arrive as '1860-02-21T00:00:00Z'. The stamp is Wikidata's, not a time
        of day, and the precision that qualifies it comes in its own file, so a
        date and its precision can be present without each other.
    label, description
        arrive as RDF literals, '"Claus Hammel"@en', quotes and language tag
        included — but only on the individual files. place_locations and
        work_labels give them already unquoted.
    description
        some carry mojibake: an en dash decoded twice.
    sex_or_gender
        a free vocabulary in practice, 48 distinct values in the data, a few of
        them unresolved.
    occupation, country_of_citizenship, writing_language, instance_of
        arrive as lists, in the order Wikidata listed them, and kept as lists.
    sitelink
        up to 228 per individual.
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
    external_id: dict[str, str] = Field({}, description="A map of property to identifier, exactly as the raw file gives it: {'P214': '7007870'}. Which database it is, is the property and nothing else — Wikidata has 10 329 external-id properties, and Property holds what each one is.")
    sitelink: tuple[Sitelink, ...] = ()
    work: tuple[WorkCredit, ...] = Field((), description="Every work credited to the individual, as a pair of the work's qid and the property that credits them. Neither is resolved here; the labels are in WorkWikidata.")


class PlaceWikidata(BaseModel):
    qid: str = Field(..., description="The place's Wikidata item, as P19 and P20 name it.")
    label: str | None = None
    latitude: float | None = Field(None, description="The latitude half of P625 'coordinate location'. The property has two components and the extraction splits them, which is why this field cannot carry the property's own name.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = None
    instance_of: tuple[str, ...] = ()


class CountryWikidata(BaseModel):
    qid: str = Field(..., description="The country's Wikidata item, as P27 names it.")
    label: str | None = None
    latitude: float | None = Field(None, description="The latitude half of P625.")
    longitude: float | None = Field(None, description="The longitude half of P625.")
    country: str | None = None
    continent: str | None = None
    iso_3166_1_alpha_3_code: str | None = None
    sitelink: tuple[Sitelink, ...] = ()


class OccupationWikidata(BaseModel):
    qid: str = Field(..., description="The occupation's Wikidata item, as P106 names it.")
    label: str | None = None
    subclass_of: tuple[str, ...] = ()


class WorkWikidata(BaseModel):
    qid: str = Field(..., description="The work's Wikidata item, as the credit properties name it. A few keys in the raw file are lexeme URIs rather than qids.")
    label: str | None = None
    instance_of: tuple[str, ...] = ()
    inception: str | None = None
    inception_precision: int | None = Field(None, description="Precision of P571's time value.")
    publication_date: str | None = None
    publication_date_precision: int | None = Field(None, description="Precision of P577's time value.")
