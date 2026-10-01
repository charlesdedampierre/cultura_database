import functools
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "1-datamodels"))

import datamodel_raw
import raw_file_readers


def sample_qids(size):
    return sorted(qid for qid, _ in itertools.islice(raw_file_readers.pairs(raw_file_readers.WORK), size))


def individuals(qids):
    label = raw_file_readers.subset(raw_file_readers.LABEL, qids)
    missing_label = raw_file_readers.subset(raw_file_readers.MISSING_LABEL, set(qids) - set(label))
    description = raw_file_readers.subset(raw_file_readers.DESCRIPTION, qids)
    date_of_birth = raw_file_readers.subset(raw_file_readers.DATE_OF_BIRTH, qids)
    date_of_birth_precision = raw_file_readers.subset(raw_file_readers.DATE_OF_BIRTH_PRECISION, qids)
    date_of_death = raw_file_readers.subset(raw_file_readers.DATE_OF_DEATH, qids)
    date_of_death_precision = raw_file_readers.subset(raw_file_readers.DATE_OF_DEATH_PRECISION, qids)
    floruit = raw_file_readers.subset(raw_file_readers.FLORUIT, qids)
    floruit_precision = raw_file_readers.subset(raw_file_readers.FLORUIT_PRECISION, qids)
    place_of_birth = raw_file_readers.subset(raw_file_readers.PLACE_OF_BIRTH, qids)
    place_of_death = raw_file_readers.subset(raw_file_readers.PLACE_OF_DEATH, qids)
    sex_or_gender = raw_file_readers.subset(raw_file_readers.SEX_OR_GENDER, qids, raw_file_readers.pairs_until_truncated)
    occupation = raw_file_readers.subset(raw_file_readers.OCCUPATION, qids)
    country_of_citizenship = raw_file_readers.subset(raw_file_readers.COUNTRY_OF_CITIZENSHIP, qids)
    writing_language = raw_file_readers.subset(raw_file_readers.WRITING_LANGUAGE, qids)
    external_id = raw_file_readers.subset(raw_file_readers.EXTERNAL_ID, qids)
    sitelink = raw_file_readers.subset(raw_file_readers.SITELINK, qids)
    work = raw_file_readers.subset(raw_file_readers.WORK, qids)

    return [
        datamodel_raw.IndividualWikidata(
            qid=qid,
            label=raw_file_readers.literal(label.get(qid)) or (missing_label.get(qid) or {}).get("label"),
            label_language="en" if label.get(qid) else (missing_label.get(qid) or {}).get("language"),
            description=raw_file_readers.literal(description.get(qid)),
            date_of_birth=date_of_birth.get(qid),
            date_of_birth_precision=date_of_birth_precision.get(qid),
            date_of_death=date_of_death.get(qid),
            date_of_death_precision=date_of_death_precision.get(qid),
            floruit=floruit.get(qid),
            floruit_precision=floruit_precision.get(qid),
            place_of_birth=(place_of_birth.get(qid) or {}).get("id"),
            place_of_death=(place_of_death.get(qid) or {}).get("id"),
            sex_or_gender=(sex_or_gender.get(qid) or {}).get("id"),
            occupation=tuple(occupation.get(qid) or ()),
            country_of_citizenship=tuple(c["id"] for c in country_of_citizenship.get(qid) or ()),
            writing_language=tuple(w["id"] for w in writing_language.get(qid) or ()),
            external_id={pid: tuple(value) if isinstance(value, list) else (value,) for pid, value in (external_id.get(qid) or {}).items()},
            sitelink=tuple(datamodel_raw.Sitelink(site=s.get("site"), title=s.get("title"), url=s.get("url")) for s in sitelink.get(qid) or ()),
            work=tuple(datamodel_raw.WorkCredit(work=w.get("work"), property=w.get("prop")) for w in work.get(qid) or ()),
        )
        for qid in qids
    ]


def places(qids):
    location = raw_file_readers.subset(raw_file_readers.PLACE_LOCATION, qids)
    instance_of = raw_file_readers.subset(raw_file_readers.PLACE_INSTANCE_OF, qids)
    inception = raw_file_readers.subset(raw_file_readers.PLACE_INCEPTION, qids)
    dissolution = raw_file_readers.subset(raw_file_readers.PLACE_DISSOLUTION, qids)
    sitelink = raw_file_readers.subset(raw_file_readers.PLACE_SITELINK, qids)

    return [
        datamodel_raw.PlaceWikidata(
            qid=qid,
            label=(location.get(qid) or {}).get("name"),
            latitude=(location.get(qid) or {}).get("lat"),
            longitude=(location.get(qid) or {}).get("lon"),
            country=(location.get(qid) or {}).get("country_id"),
            instance_of=tuple(t["id"] for t in (instance_of.get(qid) or {}).get("types", ())),
            inception=(inception.get(qid) or {}).get("date"),
            inception_precision=(inception.get(qid) or {}).get("precision"),
            dissolved_abolished_or_demolished_date=(dissolution.get(qid) or {}).get("date"),
            dissolved_abolished_or_demolished_date_precision=(dissolution.get(qid) or {}).get("precision"),
            sitelink=((datamodel_raw.Sitelink(site="en.wikipedia.org", title=None, url=sitelink[qid]),) if sitelink.get(qid) else ()),
        )
        for qid in qids
    ]


def countries(qids):
    location = raw_file_readers.subset(raw_file_readers.COUNTRY_LOCATION, qids)
    country_of = raw_file_readers.subset(raw_file_readers.COUNTRY_OF_PLACE, qids)
    modern = raw_file_readers.subset(raw_file_readers.COUNTRY_MODERN, qids)
    sitelink = raw_file_readers.subset(raw_file_readers.COUNTRY_SITELINK, qids)

    place_location = raw_file_readers.subset(raw_file_readers.PLACE_LOCATION, qids)
    instance_of = raw_file_readers.subset(raw_file_readers.PLACE_INSTANCE_OF, qids)
    inception = raw_file_readers.subset(raw_file_readers.PLACE_INCEPTION, qids)
    dissolution = raw_file_readers.subset(raw_file_readers.PLACE_DISSOLUTION, qids)

    return [
        datamodel_raw.CountryWikidata(
            qid=qid,
            label=(country_of.get(qid) or modern.get(qid) or place_location.get(qid) or {}).get("name"),
            latitude=(location.get(qid) or place_location.get(qid) or {}).get("lat"),
            longitude=(location.get(qid) or place_location.get(qid) or {}).get("lon"),
            country=(country_of.get(qid) or place_location.get(qid) or {}).get("country_id"),
            continent=(modern.get(qid) or {}).get("continent"),
            iso_3166_1_alpha_3_code=(modern.get(qid) or {}).get("iso_a3_code"),
            sitelink=((datamodel_raw.Sitelink(site="en.wikipedia.org", title=None, url=sitelink[qid]),) if sitelink.get(qid) else ()),
            instance_of=tuple(t["id"] for t in (instance_of.get(qid) or {}).get("types", ())),
            inception=(inception.get(qid) or {}).get("date"),
            inception_precision=(inception.get(qid) or {}).get("precision"),
            dissolved_abolished_or_demolished_date=(dissolution.get(qid) or {}).get("date"),
            dissolved_abolished_or_demolished_date_precision=(dissolution.get(qid) or {}).get("precision"),
        )
        for qid in qids
    ]


def occupations(qids):
    label = raw_file_readers.subset(raw_file_readers.OCCUPATION_LABEL, qids)
    return [datamodel_raw.OccupationWikidata(qid=qid, label=raw_file_readers.literal(label.get(qid))) for qid in qids]


@functools.cache
def work_class_labels():
    return raw_file_readers.whole(raw_file_readers.WORK_INSTANCE_LABEL)


def works(qids):
    label = raw_file_readers.subset(raw_file_readers.WORK_LABEL, qids)
    instance_of = raw_file_readers.subset(raw_file_readers.WORK_INSTANCE_OF, qids)
    inception = raw_file_readers.subset(raw_file_readers.WORK_INCEPTION, qids)
    publication_date = raw_file_readers.subset(raw_file_readers.WORK_PUBLICATION_DATE, qids)
    class_label = work_class_labels()

    return [
        datamodel_raw.WorkWikidata(
            qid=qid,
            label=raw_file_readers.literal(label.get(qid)),
            instance_of=(instance_of[qid],) if instance_of.get(qid) else (),
            instance_of_label=(class_label.get(instance_of[qid]),) if instance_of.get(qid) else (),
            inception=(inception.get(qid) or {}).get("date"),
            inception_precision=(inception.get(qid) or {}).get("precision"),
            publication_date=(publication_date.get(qid) or {}).get("date"),
            publication_date_precision=(publication_date.get(qid) or {}).get("precision"),
        )
        for qid in qids
    ]


def formatter_urls():
    return {p["property_id"]: p.get("formatter_url") for p in raw_file_readers.items(raw_file_readers.EXTERNAL_ID_PROPERTY, "properties.item") if p.get("formatter_url")}


def external_id_properties(pids):
    wanted = set(pids)
    formatter = {p["property_id"]: p.get("formatter_url") for p in raw_file_readers.items(raw_file_readers.EXTERNAL_ID_PROPERTY, "properties.item") if p["property_id"] in wanted}
    metadata = {}
    document = raw_file_readers.whole(raw_file_readers.EXTERNAL_ID_PROPERTY_METADATA)
    names = document["columns"]
    for row in document["rows"]:
        record = dict(zip(names, row))
        if record["property_id"] in wanted:
            metadata[record["property_id"]] = record
    details = raw_file_readers.whole(raw_file_readers.EXTERNAL_ID_PROPERTY_DETAILS)

    return [
        datamodel_raw.ExternalIdPropertyWikidata(
            pid=pid,
            label=(metadata.get(pid) or {}).get("name_en"),
            formatter_url=formatter.get(pid),
            subject_item_of_this_property=(details.get(pid) or {}).get("issuer") or (metadata.get(pid) or {}).get("issuer_id"),
            country=(details.get(pid) or {}).get("country") or (metadata.get(pid) or {}).get("country_id"),
            official_website=(details.get(pid) or {}).get("website") or (metadata.get(pid) or {}).get("website"),
            number_of_records=str((details.get(pid) or {}).get("number_of_records") or (metadata.get(pid) or {}).get("database_records") or "") or None,
            inception=((details.get(pid) or {}).get("inception") or {}).get("date"),
            inception_precision=((details.get(pid) or {}).get("inception") or {}).get("precision"),
            read_from_issuer=tuple((details.get(pid) or {}).get("read_from_issuer", ())),
        )
        for pid in sorted(wanted)
    ]


def properties():
    return [datamodel_raw.Property(pid=pid, label=entry["name"], definition=entry.get("definition")) for pid, entry in raw_file_readers.pairs(raw_file_readers.PROPERTY)]


def polities():
    return [
        datamodel_raw.PolityCliopatria(
            name=feature["properties"]["Name"],
            from_year=feature["properties"].get("FromYear"),
            to_year=feature["properties"].get("ToYear"),
            area=feature["properties"].get("Area"),
            type=feature["properties"].get("Type"),
            wikipedia=feature["properties"].get("Wikipedia") or None,
            wikidata=feature["properties"].get("Wikidata") or None,
            seshat_id=feature["properties"].get("SeshatID") or None,
            components=feature["properties"].get("Components") or None,
            member_of=feature["properties"].get("MemberOf") or None,
            geometry=json.dumps(feature["geometry"], default=float),
        )
        for feature in raw_file_readers.items(raw_file_readers.POLITY, "features.item")
    ]


def polity_existence(qids):
    found = raw_file_readers.subset(raw_file_readers.POLITY_EXISTENCE, qids)
    return {
        qid: datamodel_raw.PolityWikidata(
            qid=qid,
            inception=(entry.get("inception") or {}).get("date"),
            inception_precision=(entry.get("inception") or {}).get("precision"),
            dissolution=(entry.get("dissolution") or {}).get("date"),
            dissolution_precision=(entry.get("dissolution") or {}).get("precision"),
        )
        for qid, entry in found.items()
    }


def wikimedia_sites():
    return {
        url: datamodel_raw.WikimediaSiteWikidata(url=url, qid=entry.get("qid"), label=entry.get("label_en"), language=entry.get("language"))
        for url, entry in raw_file_readers.pairs(raw_file_readers.WIKIMEDIA_SITE)
    }
