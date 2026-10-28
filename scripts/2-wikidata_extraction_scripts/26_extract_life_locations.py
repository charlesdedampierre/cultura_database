"""Extract the life-location statements of every Q5 human (work location P937,
residence P551, employer P108, educated at P69, position held P39) with their
start / end / point-in-time qualifiers and precisions, then the coordinates of
every target (directly, via its location, or via the jurisdiction of a position)."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from tqdm import tqdm

from wikidata import PREFIXES, clean_literal, extract_qid, qlever_stream, time_value

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "life_locations"
PROGRESS = ROOT / "task.log"

PROPERTIES = {"P937": "work_location", "P551": "residence", "P108": "employer", "P69": "educated_at", "P39": "position_held"}
QUALIFIERS = {"P580": "start", "P582": "end", "P585": "point_in_time"}

PREFIXES_EXTRA = PREFIXES + """PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pqv: <http://www.wikidata.org/prop/qualifier/value/>
"""

STATEMENT_QUERY = PREFIXES_EXTRA + """SELECT ?h ?st ?t ?rank {selects} WHERE {{
  ?h wdt:P31 wd:Q5 ; p:{prop} ?st .
  ?st ps:{prop} ?t ; wikibase:rank ?rank .
  {optionals}
}}{limit}"""

TARGET_QUERY = PREFIXES_EXTRA + """SELECT ?t ?label ?coord ?country ?loc ?loc_coord ?jurisdiction ?jurisdiction_coord WHERE {{
  {{ SELECT DISTINCT ?t WHERE {{ ?h wdt:P31 wd:Q5 ; p:{prop} ?st . ?st ps:{prop} ?t . }}{limit} }}
  OPTIONAL {{ ?t rdfs:label ?label FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?t wdt:P625 ?coord }}
  OPTIONAL {{ ?t wdt:P17 ?country }}
  OPTIONAL {{ ?t wdt:P131|wdt:P159|wdt:P276 ?loc . ?loc wdt:P625 ?loc_coord }}
  OPTIONAL {{ ?t wdt:P1001 ?jurisdiction . OPTIONAL {{ ?jurisdiction wdt:P625 ?jurisdiction_coord }} }}
}}"""


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    print(line, flush=True)
    with PROGRESS.open("a") as handle:
        handle.write(line + "\n")


def statement_query(prop: str, limit: str) -> str:
    selects = " ".join(f"?{name} ?{name}_precision" for name in QUALIFIERS.values())
    optionals = "\n  ".join(
        f"OPTIONAL {{ ?st pqv:{pid} ?{name}_value . ?{name}_value wikibase:timeValue ?{name} ; wikibase:timePrecision ?{name}_precision }}"
        for pid, name in QUALIFIERS.items()
    )
    return STATEMENT_QUERY.format(prop=prop, selects=selects, optionals=optionals, limit=limit)


def parse_point(token: str) -> dict | None:
    """'"Point(2.35 48.85)"^^<...>' -> {latitude, longitude}."""
    text = time_value(token)
    if not text.startswith("Point("):
        return None
    longitude, latitude = text[6:-1].split()[:2]
    return {"latitude": float(latitude), "longitude": float(longitude)}


def parse_date(value: str, precision: str) -> dict | None:
    if not value:
        return None
    return {"time": time_value(value), "precision": int(float(time_value(precision))) if precision else None}


def extract_statements(prop: str, limit: str) -> dict:
    statements: dict[str, dict] = {}
    for row in tqdm(qlever_stream(statement_query(prop, limit)), desc=f"{prop} statements", unit=" rows", mininterval=10):
        row += [""] * (10 - len(row))
        human, statement, target, rank = row[:4]
        if not extract_qid(target).startswith("Q"):
            continue
        record = statements.setdefault(statement, {
            "qid": extract_qid(human),
            "target": extract_qid(target),
            "rank": rank.strip("<>").split("#")[-1].replace("Rank", "").lower(),
            **{name: None for name in QUALIFIERS.values()},
        })
        for index, name in enumerate(QUALIFIERS.values()):
            date = parse_date(row[4 + 2 * index], row[5 + 2 * index])
            if date and (record[name] is None or date["precision"] > record[name]["precision"]):
                record[name] = date
    per_human: dict[str, list] = {}
    for record in statements.values():
        per_human.setdefault(record.pop("qid"), []).append(record)
    return per_human


def extract_targets(prop: str, limit: str) -> dict:
    targets: dict[str, dict] = {}
    for row in tqdm(qlever_stream(TARGET_QUERY.format(prop=prop, limit=limit)), desc=f"{prop} targets", unit=" rows", mininterval=10):
        row += [""] * (8 - len(row))
        target, label, coord, country, location, location_coord, jurisdiction, jurisdiction_coord = row
        if not extract_qid(target).startswith("Q"):
            continue
        record = targets.setdefault(extract_qid(target), {"label_en": None, "coordinates": None, "country": None, "located_in": {}, "jurisdiction": {}})
        record["label_en"] = record["label_en"] or (clean_literal(label) or None)
        record["coordinates"] = record["coordinates"] or (parse_point(coord) if coord else None)
        record["country"] = record["country"] or (extract_qid(country) if country else None)
        if location:
            record["located_in"].setdefault(extract_qid(location), parse_point(location_coord))
        if jurisdiction:
            record["jurisdiction"].setdefault(extract_qid(jurisdiction), parse_point(jurisdiction_coord) if jurisdiction_coord else None)
    return targets


def run_step(name: str, function, prop: str, limit: str, out_file: Path) -> bool:
    if out_file.exists():
        log(f"{name} {prop}: already done, skipping ({out_file.name})")
        return True
    for attempt in (1, 2):
        start = time.time()
        try:
            result = function(prop, limit)
        except Exception as error:
            log(f"{name} {prop}: attempt {attempt} failed: {error}")
            continue
        out_file.write_text(json.dumps(result, ensure_ascii=False))
        log(f"{name} {prop}: {len(result):,} entries in {time.time() - start:.0f}s -> {out_file.name}")
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true", help="LIMIT 1000 per query, writes *.test.json")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS.parent.mkdir(exist_ok=True)
    limit = "\nLIMIT 1000" if args.test else ""
    suffix = ".test.json" if args.test else ".json"
    log(f"start ({'TEST' if args.test else 'FULL'})")

    failed = []
    for prop, name in PROPERTIES.items():
        if not run_step("statements", extract_statements, prop, limit, OUT_DIR / f"{name}_{prop}_statements{suffix}"):
            failed.append(f"statements {prop}")
        if not run_step("targets", extract_targets, prop, limit, OUT_DIR / f"{name}_{prop}_targets{suffix}"):
            failed.append(f"targets {prop}")

    report = {"finished": f"{datetime.now():%Y-%m-%d %H:%M:%S}", "failed": failed, "files": sorted(path.name for path in OUT_DIR.glob(f"*{suffix}"))}
    (OUT_DIR / f"report{suffix}").write_text(json.dumps(report, indent=1))
    log(f"done; failed steps: {failed or 'none'}")


if __name__ == "__main__":
    main()
