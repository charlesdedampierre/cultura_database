"""Extract where each employer and school is (P131, P159, P276, kept apart), then
the place metadata (label, coordinates, country, classes, inception, dissolution,
English Wikipedia article) of every work location, residence and institution
location, in the shape of PlaceWikidata. Reads the files of 26_extract_life_locations.py."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wikidata import clean_literal, extract_qid, time_value, values_rows

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "life_locations"
INSTITUTION_OUT = FOLDER / "institution_locations.json"
PLACE_OUT = FOLDER / "life_location_places.json"

LOCATION_PROPERTIES = ("P131", "P159", "P276")
PREFIXES_EXTRA = "PREFIX psv: <http://www.wikidata.org/prop/statement/value/>\n"

QUERIES = {
    "location": """SELECT ?t ?p ?place WHERE {{
  VALUES ?t {{ {values} }}
  VALUES ?p {{ wdt:P131 wdt:P159 wdt:P276 }}
  ?t ?p ?place .
}}""",
    "label": """SELECT ?t ?label ?coord ?country WHERE {{
  VALUES ?t {{ {values} }}
  OPTIONAL {{ ?t rdfs:label ?label FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?t wdt:P625 ?coord }}
  OPTIONAL {{ ?t wdt:P17 ?country }}
}}""",
    "instance_of": """SELECT ?t ?class WHERE {{
  VALUES ?t {{ {values} }}
  ?t wdt:P31 ?class .
}}""",
    "inception": PREFIXES_EXTRA + """SELECT ?t ?time ?precision WHERE {{
  VALUES ?t {{ {values} }}
  ?t p:P571 ?st . ?st psv:P571 ?v . ?v wikibase:timeValue ?time ; wikibase:timePrecision ?precision .
}}""",
    "dissolution": PREFIXES_EXTRA + """SELECT ?t ?time ?precision WHERE {{
  VALUES ?t {{ {values} }}
  ?t p:P576 ?st . ?st psv:P576 ?v . ?v wikibase:timeValue ?time ; wikibase:timePrecision ?precision .
}}""",
    "sitelink": """SELECT ?t ?article WHERE {{
  VALUES ?t {{ {values} }}
  ?article schema:about ?t ; schema:isPartOf <https://en.wikipedia.org/> .
}}""",
}


def run(name: str, qids: list[str]) -> list[list[str]]:
    rows, failed = values_rows(qids, QUERIES[name], size=500, threads=2, desc=name)
    if failed:
        raise SystemExit(f"{name}: {len(failed)} chunks failed twice")
    return rows


def statement_targets(name: str) -> set[str]:
    data = json.loads((FOLDER / f"{name}_statements.json").read_text())
    return {statement["target"] for statements in data.values() for statement in statements}


def parse_point(token: str) -> tuple[float, float] | None:
    text = time_value(token)
    if not text.upper().startswith("POINT("):
        return None
    longitude, latitude = text[6:-1].split()[:2]
    return float(latitude), float(longitude)


def institution_locations(institutions: list[str]) -> dict:
    found = {qid: {pid: [] for pid in LOCATION_PROPERTIES} for qid in institutions}
    for target, prop, place in run("location", institutions):
        values = found[extract_qid(target)][extract_qid(prop)]
        if extract_qid(place).startswith("Q") and extract_qid(place) not in values:
            values.append(extract_qid(place))
    return {qid: locations for qid, locations in found.items() if any(locations.values())}


def most_precise(rows: list[list[str]]) -> dict:
    best = {}
    for target, stamp, precision in rows:
        qid, precision = extract_qid(target), int(float(time_value(precision)))
        if qid not in best or precision > best[qid][1]:
            best[qid] = (time_value(stamp), precision)
    return best


def place_metadata(places: list[str]) -> dict:
    found = {qid: {"qid": qid, "label": None, "latitude": None, "longitude": None, "country": None, "instance_of": [],
                   "inception": None, "inception_precision": None,
                   "dissolved_abolished_or_demolished_date": None, "dissolved_abolished_or_demolished_date_precision": None,
                   "sitelink": []} for qid in places}
    for row in run("label", places):
        target, label, coord, country = row + [""] * (4 - len(row))
        record = found[extract_qid(target)]
        record["label"] = record["label"] or (clean_literal(label) or None)
        point = parse_point(coord) if coord else None
        if point and record["latitude"] is None:
            record["latitude"], record["longitude"] = point
        record["country"] = record["country"] or (extract_qid(country) if country else None)
    for target, cls in run("instance_of", places):
        if extract_qid(cls) not in found[extract_qid(target)]["instance_of"]:
            found[extract_qid(target)]["instance_of"].append(extract_qid(cls))
    for qid, (stamp, precision) in most_precise(run("inception", places)).items():
        found[qid]["inception"], found[qid]["inception_precision"] = stamp, precision
    for qid, (stamp, precision) in most_precise(run("dissolution", places)).items():
        found[qid]["dissolved_abolished_or_demolished_date"], found[qid]["dissolved_abolished_or_demolished_date_precision"] = stamp, precision
    for target, article in run("sitelink", places):
        found[extract_qid(target)]["sitelink"] = [{"site": "en.wikipedia.org", "title": None, "url": article.strip("<>")}]
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true", help="first 2,000 institutions and places only, writes *.test.json")
    args = parser.parse_args()
    limit = 2_000 if args.test else None

    institutions = sorted(statement_targets("employer_P108") | statement_targets("educated_at_P69"))[:limit]
    print(f"{len(institutions):,} employers and schools")
    locations = institution_locations(institutions)
    institution_out = INSTITUTION_OUT.with_suffix(".test.json") if args.test else INSTITUTION_OUT
    institution_out.write_text(json.dumps(locations, ensure_ascii=False))
    print(f"{len(locations):,} have a location; saved {institution_out}")

    places = statement_targets("work_location_P937") | statement_targets("residence_P551")
    places |= {place for found in locations.values() for values in found.values() for place in values}
    places = sorted(places)[:limit]
    print(f"{len(places):,} places")
    metadata = place_metadata(places)
    place_out = PLACE_OUT.with_suffix(".test.json") if args.test else PLACE_OUT
    place_out.write_text(json.dumps(metadata, ensure_ascii=False))
    print(f"{sum(r['latitude'] is not None for r in metadata.values()):,} of {len(metadata):,} places have coordinates; saved {place_out}")


if __name__ == "__main__":
    main()
