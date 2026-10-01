"""Extract inception (P571) and dissolution (P576) dates — value AND
``wikibase:timePrecision`` — for every distinct place_id present in
``data/humans_clean.duckdb`` table ``places``.

Strategy
--------
Same VALUES-chunked pattern as ``19_extract_work_dates.py``:

    SELECT ?place ?date ?precision WHERE {
      VALUES ?place { wd:Q1 wd:Q2 ... }
      ?place p:P571 ?stmt .
      ?stmt psv:P571 ?val .
      ?val wikibase:timeValue ?date .
      ?val wikibase:timePrecision ?precision .
    }

Run twice (P571 inception, P576 dissolution) and merge.

Coverage will be sparse: most settlements (cities, villages) have no
inception/dissolution claims; dates concentrate on historical polities,
founded institutions, and abolished entities.

Outputs
-------
data/all_humans/wikidata_extraction_scripts_v2/
    place_inception.json    {place_qid: {"date": ISO, "precision": int}}
    place_dissolution.json  {place_qid: {"date": ISO, "precision": int}}
    place_dates.json        merged: {place_qid: {"inception": {...}|None,
                                                 "dissolution": {...}|None}}
    place_dates.errors.json failed chunks (after one retry)

Logs
----
- ``task.log`` at repo root (truncated and rewritten on launch)
- ``logs/place_dates_extraction.log`` (full per-chunk log; tail-friendly)

Run
---
    python scripts/wikidata_extraction_scripts_v2/20_extract_place_dates.py --test
    python scripts/wikidata_extraction_scripts_v2/20_extract_place_dates.py
    nohup caffeinate -i python scripts/wikidata_extraction_scripts_v2/20_extract_place_dates.py \\
          > logs/place_dates_extraction.nohup.log 2>&1 &

Note: requires no other process to hold an open connection to
``humans_clean.duckdb``. Close any duckdb CLI session first.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, qlever_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.duckdb"
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"
LOGS_DIR = ROOT / "logs"
TASK_LOG = ROOT / "task.log"

CHUNK_SIZE = 10_000
THREADS = 8

PROPS = [("P571", "inception"), ("P576", "dissolution")]

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?place ?date ?precision WHERE {{
  VALUES ?place {{ {values} }}
  ?place p:{prop} ?stmt .
  ?stmt psv:{prop} ?val .
  ?val wikibase:timeValue ?date .
  ?val wikibase:timePrecision ?precision .
}}
"""


def setup_logging(test: bool) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("place_dates")
    log.setLevel(logging.INFO)
    log.handlers.clear()

    fh = logging.FileHandler(LOGS_DIR / "place_dates_extraction.log", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    log.addHandler(fh)

    th = logging.FileHandler(TASK_LOG, mode="w")
    th.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    log.addHandler(th)

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    log.addHandler(sh)

    log.info(f"[20] start ({'TEST' if test else 'FULL'})")
    return log


def load_place_ids(limit: int | None) -> list[str]:
    con = duckdb.connect()
    con.execute(f"ATTACH '{DB_PATH}' AS db (READ_ONLY)")
    sql = "SELECT DISTINCT id FROM db.places WHERE id LIKE 'Q%'"
    if limit:
        sql += f" LIMIT {limit}"
    out = [r[0] for r in con.execute(sql).fetchall()]
    con.close()
    return out


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield i, seq[i : i + size]


def fetch_chunk(qids: list[str], prop: str) -> dict[str, dict]:
    """Run one VALUES-chunked query and return {place_qid: {date, precision}}.

    If a place has multiple statements for the property, keep the most precise
    one (highest ``timePrecision`` value); ties broken by lexicographic
    earliest date.
    """
    values = " ".join(f"wd:{q}" for q in qids)
    query = QUERY.format(values=values, prop=prop)
    out: dict[str, dict] = {}
    for row in qlever_stream(query):
        if len(row) < 3:
            continue
        p = extract_qid(row[0])
        if not p.startswith("Q"):
            continue
        date_token = row[1].strip().strip('"')
        if "^^" in date_token:
            date_token = date_token.split("^^", 1)[0].strip('"')
        prec_token = row[2].strip().strip('"').split("^^", 1)[0].strip('"')
        try:
            precision = int(float(prec_token))
        except (ValueError, TypeError):
            continue
        candidate = {"date": date_token, "precision": precision}
        prev = out.get(p)
        if prev is None or (
            precision > prev["precision"]
            or (precision == prev["precision"] and date_token < prev["date"])
        ):
            out[p] = candidate
    return out


def run_property(prop: str, label: str, place_ids: list[str], log: logging.Logger,
                 chunk_size: int, threads: int) -> tuple[dict[str, dict], list[dict]]:
    chunks = list(chunked(place_ids, chunk_size))
    log.info(f"[20] {prop} ({label}): {len(place_ids):,} places, "
             f"{len(chunks):,} chunks of {chunk_size:,}")

    merged: dict[str, dict] = {}
    failed: list[dict] = []

    pbar = tqdm(total=len(place_ids), desc=f"{prop} {label}", unit="places",
                smoothing=0.05)
    last_log = time.time()

    with ThreadPoolExecutor(max_workers=threads) as pool:
        future_to_chunk = {
            pool.submit(fetch_chunk, c, prop): (i, c) for i, c in chunks
        }
        for fut in as_completed(future_to_chunk):
            i, c = future_to_chunk[fut]
            try:
                chunk_out = fut.result()
            except Exception as exc:
                failed.append({"index": i, "size": len(c), "prop": prop,
                               "error": repr(exc)})
                pbar.update(len(c))
                continue
            for p, cand in chunk_out.items():
                prev = merged.get(p)
                if prev is None or (
                    cand["precision"] > prev["precision"]
                    or (cand["precision"] == prev["precision"]
                        and cand["date"] < prev["date"])
                ):
                    merged[p] = cand
            pbar.update(len(c))

            if time.time() - last_log > 30:
                log.info(f"[20] {prop} {label}: {pbar.n:,}/{len(place_ids):,} "
                         f"places processed, {len(merged):,} dated so far, "
                         f"{len(failed)} failed chunks")
                last_log = time.time()

    pbar.close()
    log.info(f"[20] {prop} {label}: done — {len(merged):,} dated places, "
             f"{len(failed)} failed chunks")

    if failed:
        log.info(f"[20] {prop} {label}: retrying {len(failed)} failed chunks…")
        still: list[dict] = []
        for entry in failed:
            i = entry["index"]
            c = place_ids[i : i + entry["size"]]
            try:
                chunk_out = fetch_chunk(c, prop)
            except Exception as exc:
                still.append({**entry, "retry_error": repr(exc)})
                continue
            for p, cand in chunk_out.items():
                prev = merged.get(p)
                if prev is None or (
                    cand["precision"] > prev["precision"]
                    or (cand["precision"] == prev["precision"]
                        and cand["date"] < prev["date"])
                ):
                    merged[p] = cand
        failed = still
        log.info(f"[20] {prop} {label}: after retry — {len(merged):,} dated, "
                 f"{len(failed)} chunks still failing")

    return merged, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Tiny mode: only the first 5,000 place_ids.")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--threads", type=int, default=THREADS)
    args = parser.parse_args()

    log = setup_logging(args.test)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".test" if args.test else ""

    log.info(f"[20] DB        = {DB_PATH}")
    log.info(f"[20] OUT_DIR   = {OUT_DIR}")
    log.info(f"[20] chunk     = {args.chunk_size}")
    log.info(f"[20] threads   = {args.threads}")

    test_limit = 5_000 if args.test else None
    place_ids = load_place_ids(test_limit)
    log.info(f"[20] {len(place_ids):,} distinct place_ids loaded")

    t_start = time.time()
    all_failed: list[dict] = []
    per_prop: dict[str, dict[str, dict]] = {}
    for prop, label in PROPS:
        merged, failed = run_property(prop, label, place_ids, log,
                                      args.chunk_size, args.threads)
        per_prop[label] = merged
        all_failed.extend(failed)

        out_path = OUT_DIR / f"place_{label}{suffix}.json"
        with out_path.open("w") as fh:
            json.dump(merged, fh, ensure_ascii=False)
        log.info(f"[20] saved {out_path} ({len(merged):,} dated places)")

        time.sleep(2)

    universe = set().union(*per_prop.values())
    merged_all: dict[str, dict] = {
        p: {label: per_prop[label].get(p) for label in per_prop}
        for p in universe
    }
    merged_path = OUT_DIR / f"place_dates{suffix}.json"
    with merged_path.open("w") as fh:
        json.dump(merged_all, fh, ensure_ascii=False)
    log.info(f"[20] saved {merged_path} ({len(merged_all):,} places with at least one date)")

    if all_failed:
        err_path = OUT_DIR / f"place_dates.errors{suffix}.json"
        with err_path.open("w") as fh:
            json.dump(all_failed, fh, ensure_ascii=False, indent=2)
        log.info(f"[20] {len(all_failed)} chunks STILL failing -> {err_path}")
    else:
        log.info("[20] all chunks succeeded")

    elapsed = time.time() - t_start
    log.info(f"[20] total elapsed: {elapsed/60:.1f} min")

    log.info("[20] sample:")
    for p in list(merged_all.keys())[:5]:
        log.info(f"   {p}: {merged_all[p]}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
