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
