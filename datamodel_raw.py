"""The Cultura data as it arrives, before anything is resolved.

This is the layer `datamodel.py` is built from. Everything here is a value a
query returned, kept in the shape and the spelling it came back in: a date is
still '1937-04-11T00:00:00Z', a label is still the RDF literal '"Boston"@en'
with its quotes and its language tag, a multi-valued property is still the list
Wikidata sent. Nothing is parsed, nothing is joined, nothing is chosen between.

Two things follow from that.

Every value here comes from Wikidata, so `Value.source` is a Wikidata and not
the three-way union of the curated model: at this stage there is nothing
derived, nothing answered by a model and nothing taken from another dataset.

An individual is one row, not the eighteen tables the legacy database split
them over — the raw files are already keyed by qid, one file per property, so
one row per person is what they reassemble into.

Cliopatria is the exception: it arrives as its own GeoJSON, not through
Wikidata, so Polity and Territory carry plain values and reach Wikidata only
through the qid the dataset itself provides.
"""

from pydantic import BaseModel, Field

from datamodel import Wikidata


class Value(BaseModel):
    value: str | int | float | bool | None = Field(None, description="One value, spelled as the query returned it. A date keeps its Wikidata stamp, '1937-04-11T00:00:00Z'; a label keeps its RDF literal form, '\"Boston\"@en'; an item is its bare qid.")
    source: Wikidata = Field(..., description="Which property it was read from, and which item it points at when it points at one. Always a Wikidata source here: nothing at this stage is computed, answered or taken from elsewhere.")


class Values(BaseModel):
    values: tuple[str, ...] = Field((), description="Several values for one property, in the order Wikidata listed them. Kept as a list rather than pipe-joined, because that is how the extraction received them.")
    source: Wikidata = Field(..., description="The property they were all read from.")


class Sitelink(BaseModel):
    site: str | None = Field(None, description="The edition's host, e.g. 'ar.wikipedia.org'.")
    title: str | None = Field(None, description="The article's title in that edition, unescaped.")
    url: str | None = Field(None, description="The article's URL, percent-encoded as Wikidata gives it.")


class Credit(BaseModel):
    work: str | None = Field(None, description="The work's qid.")
    property: str | None = Field(None, description="The credit property that links the individual to it — 'P50' for author, 'P170' for creator. It is not resolved to a role name here.")


class Individual(BaseModel):
    qid: str = Field(..., description="The individual's Wikidata item. It is the key every raw file is indexed by, and the only field on this row that is not a Value.")
    name: Value | None = Field(None, description="rdfs:label, as the literal '\"Claus Hammel\"@en'.")
    description: Value | None = Field(None, description="schema:description, as a literal. Some carry mojibake from the extraction — '1937\\u00e2\\u0080\\u00932016' is an en dash read twice — which is the kind of thing this layer exists to keep visible.")
    birthdate: Value | None = Field(None, description="P569, as '1860-02-21T00:00:00Z'. The stamp is Wikidata's, not a real time of day.")
    birthdate_precision: Value | None = Field(None, description="P569's precision code: 11 for a day, 9 for a year. It arrives in its own file, so a date and its precision can be present without each other.")
    deathdate: Value | None = Field(None, description="P570, in the same form.")
    deathdate_precision: Value | None = Field(None, description="P570's precision code.")
    floruit_date: Value | None = Field(None, description="P1317, in the same form.")
    floruit_precision: Value | None = Field(None, description="P1317's precision code.")
    birthplace: Value | None = Field(None, description="P19, as the place's bare qid. Its label rides in the source, still as a literal.")
    deathplace: Value | None = Field(None, description="P20, in the same form.")
    gender: Value | None = Field(None, description="P21, as a qid.")
    occupations: Values | None = Field(None, description="P106, a list of qids. Unresolved: the labels are in their own file.")
    nationalities: Values | None = Field(None, description="P27, a list of qids, each with its label in the source.")
    writing_languages: Values | None = Field(None, description="P6886, a list of qids.")
    identifiers: tuple[Value, ...] = Field((), description="One entry per external database, the identifier as its value and the property that carries it in its source — P214 for VIAF, P227 for GND. The raw file is a map of property to identifier, so which database it is, is the property and nothing else.")
    sitelinks: tuple[Sitelink, ...] = Field((), description="Every Wikipedia article about the individual, one per language edition, as the sitelinks file gives them. Up to 228 per person.")
    works: tuple[Credit, ...] = Field((), description="Every work credited to the individual, as a pair of the work's qid and the property that credits them. Neither is resolved here.")


class Territory(BaseModel):
    from_year: int | None = Field(None, description="First year of the span, as Cliopatria names the column. Negative before the common era.")
    to_year: int | None = Field(None, description="Last year of the span.")
    area: float | None = Field(None, description="Area in square kilometres, as published — an unrounded float, 64105.809261435774.")
    geometry: str | None = Field(None, description="The GeoJSON geometry as a string, Polygon or MultiPolygon, not parsed. It is the heaviest thing in the whole pipeline.")


class Polity(BaseModel):
    id: int | None = Field(None, description="Cliopatria's own identifier. Not a qid: this dataset numbers its polities itself.")
    name: str | None = Field(None, description="Name as Cliopatria spells it, e.g. 'Magadha - Shaishunaga dynasty' — its own spelling, not Wikidata's.")
    type: str | None = Field(None, description="'POLITY' or 'RELATION', as published.")
    wikipedia_url: str | None = Field(None, description="English Wikipedia URL, which is how the dataset is matched to Wikidata items and to places.")
    wikidata_id: str | None = Field(None, description="The qid Cliopatria resolved for the polity, where it resolved one. This is the only place the raw Cliopatria layer touches Wikidata.")
    territories: tuple[Territory, ...] = Field((), description="One entry per change of borders, as the GeoJSON features come. A polity averages 16 and one reaches 212.")
