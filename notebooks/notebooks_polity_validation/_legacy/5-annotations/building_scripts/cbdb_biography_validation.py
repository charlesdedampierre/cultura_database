"""Fill a BiographyDatabaseValidation (datamodel_annotations.py) for a few CBDB individuals.

Picks --n individuals of cbdb_sample.json spread across centuries, among those whose Wikidata
statements are not sourced from CBDB (cbdb_wikidata_references.json) and whose CBDB record
(cbdb_persons.json) has a birth year, a death year and at least one dated activity. Dates are read
from the structured CBDB fields; each stage place is the address CBDB gives for it, located with the
coordinates of the CBDB address table (ADDR_CODES of the CBDB SQLite release) and matched to the
Cliopatria polities of the polity table.
Saved to scripts/5-annotations/cbdb_validation/cbdb_biography_validation.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/cbdb_biography_validation.py [--n 10]
"""

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import duckdb
import sqlite3
from shapely.geometry import Point, shape
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
from datamodel_annotations import AIAnswer, BiographyData, BiographyDatabase, BiographyDatabaseValidation, DateAnswer
from datamodel_in_duckdb import Polity, WikidataEntity

FOLDER = ROOT / "scripts" / "5-annotations" / "cbdb_validation"
SAMPLE = FOLDER / "cbdb_sample.json"
PERSONS = FOLDER / "cbdb_persons.json"
REFERENCES = ROOT / "scripts" / "5-annotations" / "data" / "cbdb_wikidata_references.json"
OUT = FOLDER / "cbdb_biography_validation.json"
DB = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
CBDB_PAGE = "https://cbdb.fas.harvard.edu/cbdbapi/person.php?id={}"
CBDB_SQLITE = ROOT / "data" / "similar_databases" / "cbdb" / "cbdb_20261024.sqlite3"
SEED = 42

CBDB = BiographyDatabase(
    name="cbdb",
    description="China Biographical Database: a relational database of about 650,000 individuals of Chinese history, mainly from the 7th to the 19th century.",
    url="https://projects.iq.harvard.edu/cbdb",
)
EARLY_ADDRESSES = {"出生地": "high", "戶籍地": "medium", "籍貫(基本地址)": "low", "本貫": "low", "祖籍": "low"}
ACTIVE_ADDRESSES = {"落籍(實際居住地)": "medium", "遷住地": "medium", "僑居": "medium", "籍貫(基本地址)": "low"}
LATE_ADDRESSES = {"死所": "high", "最後所知地": "medium", "葬地": "medium"}


def entries(record, section, key):
    value = record.get(section) or {}
    value = value.get(key, []) if isinstance(value, dict) else []
    return value if isinstance(value, list) else [value]


def year(text):
    text = str(text or "").strip()
    return int(text) if text.lstrip("-").isdigit() and int(text) != 0 else None


def activities(record, birth, death):
    found = []
    for entry in entries(record, "PersonEntryInfo", "Entry"):
        found.append((year(entry["RuShiYear"]), f"Entry: {entry['EntryType']} {entry['EntryCode']}, RuShiYear {entry['RuShiYear']}", None))
    for posting in entries(record, "PersonPostings", "Posting"):
        text = f"Posting: {posting['OfficeName']} at {posting['AddrName']}, FirstYear {posting['FirstYear']}, LastYear {posting['LastYear']}"
        found.append((year(posting["FirstYear"]), text, f"{posting['FirstYearNianhao']} {posting['FirstYearNiaohaoYear']}"))
        found.append((year(posting["LastYear"]), text, f"{posting['LastYearNianhao']} {posting['LastYearNianhaoYear']}"))
    for text in entries(record, "PersonTexts", "Text"):
        found.append((year(text["Year"]), f"Text: {text['TextName']} ({text['Role']}), Year {text['Year']}", None))
    return sorted((event for event in found if event[0] and birth <= event[0] <= death), key=lambda event: event[0])


def life_date(value, written, verbatim, reasoning, confidence, cbdb_id):
    return DateAnswer(
        answer=str(value), answer_as_written_in_text=written, answer_as_written_in_text_english=str(value),
        confidence=confidence, reasoning=reasoning, source=CBDB_PAGE.format(cbdb_id) + "&o=json",
        source_verbatim=(verbatim,), source_verbatim_english=(verbatim,),
        source_verbatim_not_invented=True, answer_supported_by_source_verbatim=True,
    )


def era(dynasty, era_name, era_year):
    parts = [part for part in (dynasty, era_name, era_year) if part and part != "未詳"]
    return " ".join(parts) or None


def dates(record, cbdb_id):
    basic = record["BasicInfo"]
    birth, death = year(basic["YearBirth"]), year(basic["YearDeath"])
    events = activities(record, birth, death)
    data = {
        "birth_date": life_date(birth, era(basic["DynastyBirth"], basic["EraBirth"], basic["EraYearBirth"]) or str(birth),
                                f"YearBirth: {basic['YearBirth']}", "Read from the YearBirth field of the CBDB record.", "high", cbdb_id),
        "death_date": life_date(death, era(basic["DynastyDeath"], basic["EraDeath"], basic["EraYearDeath"]) or str(death),
                                f"YearDeath: {basic['YearDeath']}", "Read from the YearDeath field of the CBDB record.", "high", cbdb_id),
    }
    if events:
        first, last = events[0], events[-1]
        data["start_of_active_life"] = life_date(first[0], first[2] or str(first[0]), first[1], "Earliest dated activity of the CBDB record (entry into office, posting, text).", "medium", cbdb_id)
        data["end_of_active_life"] = life_date(last[0], last[2] or str(last[0]), last[1], "Latest dated activity of the CBDB record (entry into office, posting, text).", "medium", cbdb_id)
    return data, birth, death, events


def address(record, types):
    for kind, confidence in types.items():
        for found in entries(record, "PersonAddresses", "Address"):
            if found["AddrType"] == kind and known(found):
                return found["AddrId"], found["AddrName"], f"Address: {kind} {found['AddrName']}", confidence
    return None


def known(found):
    return year(found["AddrId"]) is not None and "未詳" not in found["AddrName"]


def stage_places(record, events):
    early = address(record, EARLY_ADDRESSES)
    postings = [posting for posting in entries(record, "PersonPostings", "Posting") if known(posting)]
    if postings:
        addr_id, name = Counter((posting["AddrId"], posting["AddrName"]) for posting in postings).most_common(1)[0][0]
        count = sum(posting["AddrId"] == addr_id for posting in postings)
        active = (addr_id, name, f"Postings at {name}: {count} of {len(postings)}", "medium")
    else:
        active = address(record, ACTIVE_ADDRESSES)
    late = address(record, LATE_ADDRESSES)
    dated = [posting for posting in postings if year(posting["LastYear"]) or year(posting["FirstYear"])]
    if late is None and dated:
        last = max(dated, key=lambda posting: year(posting["LastYear"]) or year(posting["FirstYear"]))
        late = (last["AddrId"], last["AddrName"], f"Last dated posting: {last['OfficeName']} at {last['AddrName']}", "low")
    return early, active, late


def addresses(connection, ids):
    rows = connection.execute(f"SELECT c_addr_id, c_name, c_firstyear, c_lastyear, x_coord, y_coord FROM ADDR_CODES WHERE c_addr_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {str(row[0]): row[1:] for row in rows}


def polities_at(point, start, end, polities):
    years = {}
    for polity in polities:
        for territory in polity["territories"]:
            low, high = max(start, territory["start_year"]), min(end, territory["end_year"])
            if low <= high and shape(json.loads(territory["geometry"])).covers(point):
                years.setdefault(polity["cliopatria_id"], set()).update(range(low, high + 1))
    ranked = sorted(years, key=lambda cliopatria_id: -len(years[cliopatria_id]))
    by_id = {polity["cliopatria_id"]: polity for polity in polities}
    return tuple(Polity(cliopatria_id=i, name=by_id[i]["name"], meta_polities=by_id[i]["meta_polities"] or (), world=by_id[i]["world"] or ()) for i in ranked)


def stage(found, start, end, polities, places, cbdb_id):
    if found is None:
        return AIAnswer(), ()
    addr_id, name, verbatim, confidence = found
    reasoning = f"Address CBDB gives for the stage ({start}-{end})."
    english, point = None, None
    if str(int(addr_id)) in places:
        english, first, last, x, y = places[str(int(addr_id))]
        if x and y:
            point = Point(x, y)
            reasoning += f" CBDB address {int(addr_id)} ({english}, {first}-{last}) at {y:.4f}, {x:.4f}."
    answer = AIAnswer(
        answer=english or name, answer_as_written_in_text=name, answer_as_written_in_text_english=english,
        confidence=confidence, reasoning=reasoning, source=CBDB_PAGE.format(cbdb_id) + "&o=json",
        source_verbatim=(verbatim,), source_verbatim_english=(verbatim,),
        source_verbatim_not_invented=True, answer_supported_by_source_verbatim=True,
    )
    return answer, polities_at(point, start, end, polities) if point else ()


def candidates(sample, persons, cbdb_sourced):
    found = {}
    for row in sample:
        record = persons.get(row["qid"])
        if record is None or row["qid"] in cbdb_sourced:
            continue
        birth, death = year(record["BasicInfo"]["YearBirth"]), year(record["BasicInfo"]["YearDeath"])
        if birth and death and birth < death and activities(record, birth, death):
            found.setdefault(row["century"], []).append(row)
    return found


def pick(by_century, n):
    rng = random.Random(SEED)
    centuries = sorted(by_century)
    chosen = [centuries[round(i * (len(centuries) - 1) / max(n - 1, 1))] for i in range(min(n, len(centuries)))]
    return [rng.choice(by_century[century]) for century in chosen]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=10)
    args = parser.parse_args()

    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    persons = json.loads(PERSONS.read_text(encoding="utf-8"))
    cbdb_sourced = {statement["qid"] for statement in json.loads(REFERENCES.read_text(encoding="utf-8")) if statement["status"] == "cbdb"}
    by_century = candidates(sample, persons, cbdb_sourced)
    print(f"{sum(map(len, by_century.values()))} usable individuals over centuries {sorted(by_century)}")
    chosen = pick(by_century, args.n)

    connection = duckdb.connect(str(DB), read_only=True)
    qids = [row["qid"] for row in chosen]
    entities = {entity["qid"]: entity for (entity,) in connection.execute("SELECT entity FROM individual WHERE entity.qid IN (SELECT unnest(?))", [qids]).fetchall()}
    polities = [dict(zip(("cliopatria_id", "name", "meta_polities", "world", "territories"), row)) for row in connection.execute("SELECT cliopatria_id, name, meta_polities, world, territories FROM polity").fetchall()]

    cbdb_addresses = sqlite3.connect(f"file:{CBDB_SQLITE}?mode=ro", uri=True)
    validations = []
    for row in tqdm(chosen, desc="CBDB individuals"):
        record = persons[row["qid"]]
        cbdb_id = record["BasicInfo"]["PersonId"]
        data, birth, death, events = dates(record, cbdb_id)
        start = events[0][0] if events else birth
        end = events[-1][0] if events else death
        early, active, late = stage_places(record, events)
        places = addresses(cbdb_addresses, [str(int(found[0])) for found in (early, active, late) if found])
        data["early_stage_place"], data["early_stage_polity"] = stage(early, birth, start, polities, places, cbdb_id)
        data["active_stage_place"], data["active_stage_polity"] = stage(active, start, end, polities, places, cbdb_id)
        data["late_stage_place"], data["late_stage_polity"] = stage(late, end, death, polities, places, cbdb_id)
        validations.append(BiographyDatabaseValidation(
            wikidata_entity=WikidataEntity(**entities[row["qid"]]),
            biography_database=CBDB,
            biography_database_id=cbdb_id,
            biography_database_url=CBDB_PAGE.format(cbdb_id),
            biography_database_text_path=str(PERSONS.relative_to(ROOT)),
            biography_database_structured_data=BiographyData(**data),
        ))

    OUT.write_text(json.dumps([v.model_dump(mode="json") for v in validations], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(validations)} validations saved to {OUT.relative_to(ROOT)}")
    for v in validations:
        d = v.biography_database_structured_data
        print(f"  {v.wikidata_entity.qid:11} {v.wikidata_entity.label_en or '':24} {d.birth_date.answer}-{d.death_date.answer} active {d.start_of_active_life.answer}-{d.end_of_active_life.answer} | "
              f"{d.early_stage_place.answer} / {d.active_stage_place.answer} / {d.late_stage_place.answer} | {[p.name for p in d.active_stage_polity]}")


if __name__ == "__main__":
    main()
