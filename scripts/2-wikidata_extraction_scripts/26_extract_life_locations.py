"""Extract the life-location statements of every individual of the database
(work location P937, residence P551, employer P108, educated at P69, position
held P39) with their start / end / point-in-time qualifiers and precisions, then
the coordinates of every target (directly, via its location, or via the
jurisdiction of a position).

Queries go by chunks of individuals (VALUES): a single bulk query over all
humans is silently cut by QLever after ~30 s of streaming. Each chunk is saved
in parts/ so the run can be resumed."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import duckdb
from tqdm import tqdm

from wikidata import PREFIXES, chunk, clean_literal, extract_qid, qlever_stream, time_value

ROOT = Path(__file__).resolve().parents[2]
DATABASE = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
OUT_DIR = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "life_locations"
PROGRESS = ROOT / "task.log"

PROPERTIES = {"P937": "work_location", "P551": "residence", "P108": "employer", "P69": "educated_at", "P39": "position_held"}
QUALIFIERS = {"P580": "start", "P582": "end", "P585": "point_in_time"}

PREFIXES_EXTRA = PREFIXES + """PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pqv: <http://www.wikidata.org/prop/qualifier/value/>
"""

STATEMENT_QUERY = PREFIXES_EXTRA + """SELECT ?h ?p ?st ?t ?rank {selects} WHERE {{
  VALUES ?h {{ {values} }}
  VALUES (?p ?ps) {{ {properties} }}
  ?h ?p ?st .
  ?st ?ps ?t ; wikibase:rank ?rank .
  {optionals}
}}"""

TARGET_QUERY = PREFIXES_EXTRA + """SELECT ?t ?label ?coord ?country ?loc ?loc_coord ?jurisdiction ?jurisdiction_coord WHERE {{
  VALUES ?t {{ {values} }}
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


def statement_query(qids: list[str]) -> str:
    selects = " ".join(f"?{name} ?{name}_precision" for name in QUALIFIERS.values())
    properties = " ".join(f"(p:{pid} ps:{pid})" for pid in PROPERTIES)
    optionals = "\n  ".join(
        f"OPTIONAL {{ ?st pqv:{pid} ?{name}_value . ?{name}_value wikibase:timeValue ?{name} ; wikibase:timePrecision ?{name}_precision }}"
        for pid, name in QUALIFIERS.items()
    )
    values = " ".join(f"wd:{qid}" for qid in qids)
    return STATEMENT_QUERY.format(selects=selects, values=values, properties=properties, optionals=optionals)


def parse_point(token: str) -> dict | None:
    """'POINT(2.35 48.85)' -> {latitude, longitude}."""
    text = time_value(token)
    if not text.upper().startswith("POINT("):
        return None
    longitude, latitude = text[6:-1].split()[:2]
    return {"latitude": float(latitude), "longitude": float(longitude)}


def parse_date(value: str, precision: str) -> dict | None:
    if not value:
        return None
    return {"time": time_value(value), "precision": int(float(time_value(precision))) if precision else None}


def fetch_statements(qids: list[str]) -> list[dict]:
    statements: dict[str, dict] = {}
    for row in qlever_stream(statement_query(qids)):
        row += [""] * (11 - len(row))
        human, prop, statement, target, rank = row[:5]
        if not extract_qid(target).startswith("Q"):
            continue
        record = statements.setdefault(statement, {
            "qid": extract_qid(human),
            "property": extract_qid(prop),
            "target": extract_qid(target),
            "rank": rank.strip("<>").split("#")[-1].replace("Rank", "").lower(),
            **{name: None for name in QUALIFIERS.values()},
        })
        for index, name in enumerate(QUALIFIERS.values()):
            date = parse_date(row[5 + 2 * index], row[6 + 2 * index])
            if date and (record[name] is None or (date["precision"] or 0) > (record[name]["precision"] or 0)):
                record[name] = date
    return list(statements.values())


def fetch_targets(qids: list[str]) -> dict:
    targets: dict[str, dict] = {}
    for row in qlever_stream(TARGET_QUERY.format(values=" ".join(f"wd:{qid}" for qid in qids))):
        row += [""] * (8 - len(row))
        target, label, coord, country, location, location_coord, jurisdiction, jurisdiction_coord = row
        record = targets.setdefault(extract_qid(target), {"label_en": None, "coordinates": None, "country": None, "located_in": {}, "jurisdiction": {}})
        record["label_en"] = record["label_en"] or (clean_literal(label) or None)
        record["coordinates"] = record["coordinates"] or (parse_point(coord) if coord else None)
        record["country"] = record["country"] or (extract_qid(country) if country else None)
        if location:
            record["located_in"].setdefault(extract_qid(location), parse_point(location_coord))
        if jurisdiction:
            record["jurisdiction"].setdefault(extract_qid(jurisdiction), parse_point(jurisdiction_coord) if jurisdiction_coord else None)
    return targets


def run_chunks(name: str, fetch, qids: list[str], size: int, threads: int) -> list[int]:
    """Fetch every chunk not yet saved in parts/<name>/, retry failures once; return failed chunk ids."""
    parts = OUT_DIR / "parts" / name
    parts.mkdir(parents=True, exist_ok=True)
    chunks = dict(enumerate(chunk(qids, size)))
    todo = [index for index in chunks if not (parts / f"{index:05d}.json").exists()]
    log(f"{name}: {len(chunks):,} chunks of {size:,}, {len(chunks) - len(todo):,} already done")
    for attempt in (1, 2):
        failed = []
        with ThreadPoolExecutor(max_workers=threads) as pool:
            futures = {pool.submit(fetch, chunks[index]): index for index in todo}
            for done, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc=f"{name} (attempt {attempt})", mininterval=10), 1):
                index = futures[future]
                try:
                    (parts / f"{index:05d}.json").write_text(json.dumps(future.result(), ensure_ascii=False))
                except Exception as error:
                    failed.append(index)
                    log(f"{name}: chunk {index} failed: {error}")
                if done % 50 == 0 or done == len(futures):
                    log(f"{name} (attempt {attempt}): {done:,}/{len(futures):,} chunks, {len(failed)} failed")
        todo = failed
        if not failed:
            break
    (OUT_DIR / "parts" / f"{name}_failed_chunks.json").write_text(json.dumps(todo))
    return todo


def merge_statements() -> set[str]:
    per_property: dict[str, dict[str, list]] = {pid: {} for pid in PROPERTIES}
    for path in sorted((OUT_DIR / "parts" / "statements").glob("*.json")):
        for record in json.loads(path.read_text()):
            per_property[record.pop("property")].setdefault(record.pop("qid"), []).append(record)
    targets = set()
    for pid, people in per_property.items():
        (OUT_DIR / f"{PROPERTIES[pid]}_{pid}_statements.json").write_text(json.dumps(people, ensure_ascii=False))
        statements = [record for records in people.values() for record in records]
        targets.update(record["target"] for record in statements)
        log(f"merged {pid}: {len(people):,} individuals, {len(statements):,} statements")
    return targets


def merge_targets() -> None:
    targets = {}
    for path in sorted((OUT_DIR / "parts" / "targets").glob("*.json")):
        targets.update(json.loads(path.read_text()))
    (OUT_DIR / "targets.json").write_text(json.dumps(targets, ensure_ascii=False))
    log(f"merged targets: {len(targets):,}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, default=500, help="individuals per chunk; qlever.dev rejects queries above ~8 KB, about 600 qids")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--test", action="store_true", help="first 20,000 individuals, written under life_locations/test/")
    args = parser.parse_args()
    global OUT_DIR
    if args.test:
        OUT_DIR = OUT_DIR / "test"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start = time.time()
    qids = [row[0] for row in duckdb.connect(str(DATABASE), read_only=True).sql("select entity.qid from individual order by entity.qid").fetchall()]
    qids = qids[:20_000] if args.test else qids
    log(f"start: {len(qids):,} individuals, chunks of {args.size:,}, {args.threads} threads")

    failed_statements = run_chunks("statements", fetch_statements, qids, args.size, args.threads)
    targets = sorted(merge_statements())
    failed_targets = run_chunks("targets", fetch_targets, targets, args.size, args.threads)
    merge_targets()

    report = {
        "finished": f"{datetime.now():%Y-%m-%d %H:%M:%S}",
        "minutes": round((time.time() - start) / 60, 1),
        "individuals": len(qids),
        "targets": len(targets),
        "failed_statement_chunks": failed_statements,
        "failed_target_chunks": failed_targets,
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=1))
    log(f"done in {report['minutes']} min; failed chunks: {len(failed_statements)} statements, {len(failed_targets)} targets")


if __name__ == "__main__":
    main()
