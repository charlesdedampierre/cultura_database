import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datamodels"))

import datamodel_in_duckdb as D

PRECISION = {11: "day", 10: "month", 9: "year", 8: "decade", 7: "century", 6: "millennium"}
STAMP = re.compile(r"^-?\d{1,6}(-\d{2}(-\d{2})?)?$")


def iso(stamp):
    head = str(stamp or "").split("T")[0]
    return head if STAMP.match(head) else None


def year(stamp):
    head = iso(stamp)
    if head is None:
        return None
    sign, digits = ("-", head[1:]) if head.startswith("-") else ("", head)
    return int(sign + digits.split("-")[0])


def read_from(*raw_fields):
    return D.Provenance(raw=raw_fields)


def date(stamp, precision, *raw_fields):
    if iso(stamp) is None:
        return None
    return D.Date(
        iso=iso(stamp),
        year=year(stamp),
        precision=PRECISION.get(precision),
        field_provenance={field: read_from(*raw_fields) for field in ("iso", "year", "precision")},
    )


def dates(stamp, precision, *raw_fields):
    found = date(stamp, precision, *raw_fields)
    return (found,) if found else ()


def entity(qid, label=None, description=None):
    return D.WikidataEntity(qid=qid, label_en=label, description=description)


def individual(raw):
    return D.Individual(
        entity=entity(raw.qid, raw.label, raw.description),
        birth_date=dates(raw.date_of_birth, raw.date_of_birth_precision, "IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_birth_precision"),
        death_date=dates(raw.date_of_death, raw.date_of_death_precision, "IndividualWikidata.date_of_death", "IndividualWikidata.date_of_death_precision"),
        floruit_date=dates(raw.floruit, raw.floruit_precision, "IndividualWikidata.floruit", "IndividualWikidata.floruit_precision"),
        place_of_birth=D.Place(entity=entity(raw.place_of_birth)) if raw.place_of_birth else None,
        place_of_death=D.Place(entity=entity(raw.place_of_death)) if raw.place_of_death else None,
        sex_or_gender=raw.sex_or_gender,
        occupation=tuple(D.Occupation(entity=entity(qid)) for qid in raw.occupation),
        country_of_citizenship=tuple(D.Place(entity=entity(qid)) for qid in raw.country_of_citizenship),
        writing_language=raw.writing_language,
        external_id=tuple(
            individual_identifier(raw.qid, pid, value)
            for pid, values in sorted(raw.external_id.items())
            for value in values
        ),
        sitelink=tuple(individual_sitelink(raw.qid, link) for link in raw.sitelink),
        work=tuple(individual_work(raw.qid, credit) for credit in raw.work),
        field_provenance={
            "entity": read_from("IndividualWikidata.qid", "IndividualWikidata.label", "IndividualWikidata.description"),
            "birth_date": read_from("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_birth_precision"),
            "death_date": read_from("IndividualWikidata.date_of_death", "IndividualWikidata.date_of_death_precision"),
            "floruit_date": read_from("IndividualWikidata.floruit", "IndividualWikidata.floruit_precision"),
            "place_of_birth": read_from("IndividualWikidata.place_of_birth"),
            "place_of_death": read_from("IndividualWikidata.place_of_death"),
            "sex_or_gender": read_from("IndividualWikidata.sex_or_gender"),
            "occupation": read_from("IndividualWikidata.occupation"),
            "country_of_citizenship": read_from("IndividualWikidata.country_of_citizenship"),
            "writing_language": read_from("IndividualWikidata.writing_language"),
            "external_id": read_from("IndividualWikidata.external_id"),
            "sitelink": read_from("IndividualWikidata.sitelink"),
            "work": read_from("IndividualWikidata.work"),
        },
    )


def individual_identifier(qid, pid, value):
    return D.IndividualIdentifier(
        qid=qid,
        pid=pid,
        value=value,
        field_provenance={"value": read_from("IndividualWikidata.external_id")},
    )


def individual_sitelink(qid, link):
    return D.IndividualSitelink(
        qid=qid,
        url=link.url,
        site_url=f"https://{link.site}" if link.site else None,
        title=link.title,
        field_provenance={
            field: read_from("IndividualWikidata.sitelink") for field in ("url", "site_url", "title")
        },
    )


def individual_work(qid, credit):
    return D.IndividualWork(
        qid=qid,
        work_qid=credit.work,
        credit_property=D.WikidataProperty(pid=credit.property) if credit.property else None,
        field_provenance={"credit_property": read_from("IndividualWikidata.work")},
    )


def sitelink(site):
    return D.Sitelink(url=f"https://{site}", field_provenance={"url": read_from("IndividualWikidata.sitelink")})


def place(raw):
    return D.Place(
        entity=entity(raw.qid, raw.label),
        coordinates=D.Coordinates(latitude=raw.latitude, longitude=raw.longitude) if raw.latitude is not None else None,
        country=entity(raw.country) if raw.country else None,
        instance_of=tuple(entity(qid) for qid in raw.instance_of),
        existence=D.ExistencePeriod(
            inception=date(raw.inception, raw.inception_precision, "PlaceWikidata.inception", "PlaceWikidata.inception_precision"),
            dissolution=date(raw.dissolved_abolished_or_demolished_date, raw.dissolved_abolished_or_demolished_date_precision, "PlaceWikidata.dissolved_abolished_or_demolished_date", "PlaceWikidata.dissolved_abolished_or_demolished_date_precision"),
        ),
        field_provenance={
            "entity": read_from("PlaceWikidata.qid", "PlaceWikidata.label"),
            "coordinates": read_from("PlaceWikidata.latitude", "PlaceWikidata.longitude"),
            "country": read_from("PlaceWikidata.country"),
            "instance_of": read_from("PlaceWikidata.instance_of"),
            "existence": read_from("PlaceWikidata.inception", "PlaceWikidata.dissolved_abolished_or_demolished_date"),
        },
    )


def country(raw):
    return D.Place(
        entity=entity(raw.qid, raw.label, raw.description),
        coordinates=D.Coordinates(latitude=raw.latitude, longitude=raw.longitude) if raw.latitude is not None else None,
        country=entity(raw.country) if raw.country else None,
        instance_of=tuple(entity(qid) for qid in raw.instance_of),
        existence=D.ExistencePeriod(
            inception=date(raw.inception, raw.inception_precision, "CountryWikidata.inception", "CountryWikidata.inception_precision"),
            dissolution=date(raw.dissolved_abolished_or_demolished_date, raw.dissolved_abolished_or_demolished_date_precision, "CountryWikidata.dissolved_abolished_or_demolished_date", "CountryWikidata.dissolved_abolished_or_demolished_date_precision"),
        ),
        present_day_state=D.PresentDayState(
            name=raw.label,
            iso_3166_1_alpha_3_code=raw.iso_3166_1_alpha_3_code,
            continent=raw.continent,
        ) if raw.iso_3166_1_alpha_3_code else None,
        sitelink=D.Sitelink(url=raw.sitelink[0].url) if raw.sitelink else None,
        field_provenance={
            "entity": read_from("CountryWikidata.qid", "CountryWikidata.label", "CountryWikidata.description"),
            "coordinates": read_from("CountryWikidata.latitude", "CountryWikidata.longitude"),
            "country": read_from("CountryWikidata.country"),
            "instance_of": read_from("CountryWikidata.instance_of"),
            "existence": read_from("CountryWikidata.inception", "CountryWikidata.dissolved_abolished_or_demolished_date"),
            "present_day_state": read_from("CountryWikidata.iso_3166_1_alpha_3_code", "CountryWikidata.continent"),
            "sitelink": read_from("CountryWikidata.sitelink"),
        },
    )


def occupation(raw):
    return D.Occupation(
        entity=entity(raw.qid, raw.label, raw.description),
        subclass_of=tuple(entity(qid) for qid in raw.subclass_of),
        field_provenance={
            "entity": read_from("OccupationWikidata.qid", "OccupationWikidata.label"),
            "subclass_of": read_from("OccupationWikidata.subclass_of"),
        },
    )


def work(raw):
    return D.Work(
        entity=entity(raw.qid, raw.label),
        instance_of=tuple(entity(qid) for qid in raw.instance_of),
        inception=date(raw.inception, raw.inception_precision, "WorkWikidata.inception", "WorkWikidata.inception_precision"),
        publication_date=date(raw.publication_date, raw.publication_date_precision, "WorkWikidata.publication_date", "WorkWikidata.publication_date_precision"),
        field_provenance={
            "entity": read_from("WorkWikidata.qid", "WorkWikidata.label"),
            "instance_of": read_from("WorkWikidata.instance_of"),
            "inception": read_from("WorkWikidata.inception", "WorkWikidata.inception_precision"),
            "publication_date": read_from("WorkWikidata.publication_date", "WorkWikidata.publication_date_precision"),
        },
    )


def identifier(raw):
    return D.Identifier(
        property=D.WikidataProperty(pid=raw.pid, label_en=raw.label),
        formatter_url=raw.formatter_url,
        issuer=entity(raw.subject_item_of_this_property) if raw.subject_item_of_this_property else None,
        issuer_country=D.PresentDayState(name=raw.country) if raw.country else None,
        official_website=raw.official_website,
        number_of_records=int(raw.number_of_records) if (raw.number_of_records or "").isdigit() else None,
        inception=date(raw.inception, None, "ExternalIdPropertyWikidata.inception"),
        field_provenance={
            "property": read_from("ExternalIdPropertyWikidata.pid", "ExternalIdPropertyWikidata.label"),
            "formatter_url": read_from("ExternalIdPropertyWikidata.formatter_url"),
            "issuer": read_from("ExternalIdPropertyWikidata.subject_item_of_this_property"),
            "issuer_country": read_from("ExternalIdPropertyWikidata.country"),
            "official_website": read_from("ExternalIdPropertyWikidata.official_website"),
            "number_of_records": read_from("ExternalIdPropertyWikidata.number_of_records"),
            "inception": read_from("ExternalIdPropertyWikidata.inception"),
        },
    )


def wikidata_property(raw):
    return D.WikidataProperty(pid=raw.pid, label_en=raw.label, description=raw.definition)


def territory(raw):
    return D.Territory(
        start_year=raw.from_year,
        end_year=raw.to_year,
        area=raw.area,
        geometry=raw.geometry,
        field_provenance={
            "start_year": read_from("PolityCliopatria.from_year"),
            "end_year": read_from("PolityCliopatria.to_year"),
            "area": read_from("PolityCliopatria.area"),
            "geometry": read_from("PolityCliopatria.geometry"),
        },
    )


def polity(cliopatria_id, spans):
    first = spans[0]
    return D.Polity(
        cliopatria_id=cliopatria_id,
        name=first.name,
        type=first.type,
        entity=entity(first.wikidata) if first.wikidata else None,
        sitelink=D.Sitelink(url="https://en.wikipedia.org/wiki/" + first.wikipedia.replace(" ", "_")) if first.wikipedia else None,
        territories=tuple(territory(span) for span in spans),
        field_provenance={
            "name": read_from("PolityCliopatria.name"),
            "type": read_from("PolityCliopatria.type"),
            "entity": read_from("PolityCliopatria.wikidata"),
            "sitelink": read_from("PolityCliopatria.wikipedia"),
            "territories": read_from("PolityCliopatria.from_year", "PolityCliopatria.to_year", "PolityCliopatria.area", "PolityCliopatria.geometry"),
        },
    )
