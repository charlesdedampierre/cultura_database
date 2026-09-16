import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datamodels"))

import datamodel_raw as R
import sources as S


def sample_qids(size):
    return sorted(qid for qid, _ in itertools.islice(S.pairs(S.WORK), size))


def individuals(qids):
    label = S.subset(S.LABEL, qids)
    description = S.subset(S.DESCRIPTION, qids)
    date_of_birth = S.subset(S.DATE_OF_BIRTH, qids)
    date_of_birth_precision = S.subset(S.DATE_OF_BIRTH_PRECISION, qids)
    date_of_death = S.subset(S.DATE_OF_DEATH, qids)
    date_of_death_precision = S.subset(S.DATE_OF_DEATH_PRECISION, qids)
    floruit = S.subset(S.FLORUIT, qids)
    floruit_precision = S.subset(S.FLORUIT_PRECISION, qids)
    place_of_birth = S.subset(S.PLACE_OF_BIRTH, qids)
    place_of_death = S.subset(S.PLACE_OF_DEATH, qids)
    sex_or_gender = S.subset(S.SEX_OR_GENDER, qids, S.pairs_until_truncated)
    occupation = S.subset(S.OCCUPATION, qids)
    country_of_citizenship = S.subset(S.COUNTRY_OF_CITIZENSHIP, qids)
    writing_language = S.subset(S.WRITING_LANGUAGE, qids)
    external_id = S.subset(S.EXTERNAL_ID, qids)
    sitelink = S.subset(S.SITELINK, qids)
    work = S.subset(S.WORK, qids)

    return [
        R.IndividualWikidata(
            qid=qid,
            label=S.literal(label.get(qid)),
            description=S.literal(description.get(qid)),
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
            external_id={
                pid: tuple(value) if isinstance(value, list) else (value,)
                for pid, value in (external_id.get(qid) or {}).items()
            },
            sitelink=tuple(
                R.Sitelink(site=s.get("site"), title=s.get("title"), url=s.get("url"))
                for s in sitelink.get(qid) or ()
            ),
            work=tuple(
                R.WorkCredit(work=w.get("work"), property=w.get("prop"))
                for w in work.get(qid) or ()
            ),
        )
        for qid in qids
    ]


def places(qids):
    location = S.subset(S.PLACE_LOCATION, qids)
    instance_of = S.subset(S.PLACE_INSTANCE_OF, qids)
    inception = S.subset(S.PLACE_INCEPTION, qids)
    dissolution = S.subset(S.PLACE_DISSOLUTION, qids)

    return [
        R.PlaceWikidata(
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
        )
        for qid in qids
    ]


def countries(qids):
    location = S.subset(S.COUNTRY_LOCATION, qids)
    country_of = S.subset(S.COUNTRY_OF_PLACE, qids)
    modern = S.subset(S.COUNTRY_MODERN, qids)
    sitelink = S.subset(S.COUNTRY_SITELINK, qids)

    return [
        R.CountryWikidata(
            qid=qid,
            label=(country_of.get(qid) or modern.get(qid) or {}).get("name"),
            latitude=(location.get(qid) or {}).get("lat"),
            longitude=(location.get(qid) or {}).get("lon"),
            country=(country_of.get(qid) or {}).get("country_id"),
            continent=(modern.get(qid) or {}).get("continent"),
            iso_3166_1_alpha_3_code=(modern.get(qid) or {}).get("iso_a3_code"),
            sitelink=(
                (R.Sitelink(site="en.wikipedia.org", title=None, url=sitelink[qid]),)
                if sitelink.get(qid)
                else ()
            ),
        )
        for qid in qids
    ]


def occupations(qids):
    label = S.subset(S.OCCUPATION_LABEL, qids)
    return [R.OccupationWikidata(qid=qid, label=S.literal(label.get(qid))) for qid in qids]


def works(qids):
    label = S.subset(S.WORK_LABEL, qids)
    instance_of = S.subset(S.WORK_INSTANCE_OF, qids)
    inception = S.subset(S.WORK_INCEPTION, qids)
    publication_date = S.subset(S.WORK_PUBLICATION_DATE, qids)

    return [
        R.WorkWikidata(
            qid=qid,
            label=S.literal(label.get(qid)),
            instance_of=(instance_of[qid],) if instance_of.get(qid) else (),
            inception=(inception.get(qid) or {}).get("date"),
            inception_precision=(inception.get(qid) or {}).get("precision"),
            publication_date=(publication_date.get(qid) or {}).get("date"),
            publication_date_precision=(publication_date.get(qid) or {}).get("precision"),
        )
        for qid in qids
    ]


def external_id_properties(pids):
    wanted = set(pids)
    formatter = {
        p["property_id"]: p.get("formatter_url")
        for p in S.items(S.EXTERNAL_ID_PROPERTY, "properties.item")
        if p["property_id"] in wanted
    }
    metadata = {}
    document = S.whole(S.EXTERNAL_ID_PROPERTY_METADATA)
    names = document["columns"]
    for row in document["rows"]:
        record = dict(zip(names, row))
        if record["property_id"] in wanted:
            metadata[record["property_id"]] = record

    return [
        R.ExternalIdPropertyWikidata(
            pid=pid,
            label=(metadata.get(pid) or {}).get("name_en"),
            formatter_url=formatter.get(pid),
            subject_item_of_this_property=(metadata.get(pid) or {}).get("issuer_id"),
            country=(metadata.get(pid) or {}).get("country_id"),
            official_website=(metadata.get(pid) or {}).get("website"),
            number_of_records=(metadata.get(pid) or {}).get("database_records"),
            inception=(metadata.get(pid) or {}).get("inception"),
        )
        for pid in sorted(wanted)
    ]


def properties():
    return [
        R.Property(pid=pid, label=entry["name"], definition=entry.get("definition"))
        for pid, entry in S.pairs(S.PROPERTY)
    ]


def polities():
    return [
        R.PolityCliopatria(
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
        for feature in S.items(S.POLITY, "features.item")
    ]
