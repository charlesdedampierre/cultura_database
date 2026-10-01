"""Extract inception (P571) and publication (P577) dates — value AND
`wikibase:timePrecision` — for every distinct work_id present in
`data/humans_clean.sqlite3` table `works`.

Strategy
--------
Same VALUES-chunked pattern as `15_extract_work_instance_of.py`:

    SELECT ?work ?date ?precision WHERE {
      VALUES ?work { wd:Q1 wd:Q2 ... }
      ?work p:P571 ?stmt .
      ?stmt psv:P571 ?val .
      ?val wikibase:timeValue ?date .
      ?val wikibase:timePrecision ?precision .
    }

We do this twice (once for P571, once for P577) and merge.

Speed-test (50k sample, run via 18_speed_test_work_dates.py) showed
chunk=10000 + threads=8 is the best stable point on QLever — bumping to 15
threads triggers HTTP 429 rate-limits and net throughput collapses.

Outputs
-------
data/all_humans/wikidata_extraction_scripts_v2/
    work_inception.json       {work_qid: {"date": ISO, "precision": int}}
    work_publication.json     {work_qid: {"date": ISO, "precision": int}}
    work_dates.json           merged: {work_qid: {"inception": {...}, "publication": {...}}}
    work_dates.errors.json    failed chunks (after one retry)

Logs
----
- ``task.log`` at repo root (truncated and rewritten on launch)
- ``logs/work_dates_extraction.log`` (full per-chunk log; tail-friendly)
- ``logs/work_dates_extraction_processed.json`` (chunk-level checkpoint)

Run
---
    python scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py --test
    python scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py
    nohup caffeinate -i python scripts/wikidata_extraction_scripts_v2/19_extract_work_dates.py \\
          > logs/work_dates_extraction.nohup.log 2>&1 &
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import extract_qid, qlever_stream  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"
LOGS_DIR = ROOT / "logs"
TASK_LOG = ROOT / "task.log"

CHUNK_SIZE = 10_000
THREADS = 8

PROPS = [("P571", "inception"), ("P577", "publication")]

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?work ?date ?precision WHERE {{
  VALUES ?work {{ {values} }}
  ?work p:{prop} ?stmt .
  ?stmt psv:{prop} ?val .
  ?val wikibase:timeValue ?date .
  ?val wikibase:timePrecision ?precision .
}}
"""


def setup_logging(test: bool) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("work_dates")
    log.setLevel(logging.INFO)
    log.handlers.clear()

    fh = logging.FileHandler(LOGS_DIR / "work_dates_extraction.log", mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    log.addHandler(fh)

    th = logging.FileHandler(TASK_LOG, mode="w")
    th.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    log.addHandler(th)

    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s  %(message)s"))
    log.addHandler(sh)

    log.info(f"[19] start ({'TEST' if test else 'FULL'})")
    return log


def load_work_ids(limit: int | None) -> list[str]:
    con = sqlite3.connect(str(DB_PATH))
    sql = "SELECT DISTINCT work_id FROM works WHERE work_id LIKE 'Q%'"
    if limit:
        sql += f" LIMIT {limit}"
    cur = con.execute(sql)
    out = [r[0] for r in cur.fetchall()]
    con.close()
    return out


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield i, seq[i : i + size]


def fetch_chunk(qids: list[str], prop: str) -> dict[str, dict]:
    """Run one VALUES-chunked query and return {work_qid: {date, precision}}.

    If a work has multiple statements for the property, keep the most precise
    one (highest ``timePrecision`` value); ties broken by lexicographic
    earliest date (typically the earliest publication / inception edition).
    """
    values = " ".join(f"wd:{q}" for q in qids)
    query = QUERY.format(values=values, prop=prop)
    out: dict[str, dict] = {}
    for row in qlever_stream(query):
        if len(row) < 3:
            continue
        w = extract_qid(row[0])
        if not w.startswith("Q"):
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
        prev = out.get(w)
        if prev is None or (
            precision > prev["precision"]
            or (precision == prev["precision"] and date_token < prev["date"])
        ):
            out[w] = candidate
    return out


def run_property(prop: str, label: str, work_ids: list[str], log: logging.Logger,
                 chunk_size: int, threads: int) -> tuple[dict[str, dict], list[dict]]:
    chunks = list(chunked(work_ids, chunk_size))
    log.info(f"[19] {prop} ({label}): {len(work_ids):,} works, "
             f"{len(chunks):,} chunks of {chunk_size:,}")

    merged: dict[str, dict] = {}
    failed: list[dict] = []

    pbar = tqdm(total=len(work_ids), desc=f"{prop} {label}", unit="works",
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
            # Merge: keep most-precise / earliest tie-break
            for w, cand in chunk_out.items():
                prev = merged.get(w)
                if prev is None or (
                    cand["precision"] > prev["precision"]
                    or (cand["precision"] == prev["precision"]
                        and cand["date"] < prev["date"])
                ):
                    merged[w] = cand
            pbar.update(len(c))

            if time.time() - last_log > 30:
                log.info(f"[19] {prop} {label}: {pbar.n:,}/{len(work_ids):,} "
                         f"works processed, {len(merged):,} dated so far, "
                         f"{len(failed)} failed chunks")
                last_log = time.time()

    pbar.close()
    log.info(f"[19] {prop} {label}: done — {len(merged):,} dated works, "
             f"{len(failed)} failed chunks")

    if failed:
        log.info(f"[19] {prop} {label}: retrying {len(failed)} failed chunks…")
        still: list[dict] = []
        for entry in failed:
            i = entry["index"]
            c = work_ids[i : i + entry["size"]]
            try:
                chunk_out = fetch_chunk(c, prop)
            except Exception as exc:
                still.append({**entry, "retry_error": repr(exc)})
                continue
            for w, cand in chunk_out.items():
                prev = merged.get(w)
                if prev is None or (
                    cand["precision"] > prev["precision"]
                    or (cand["precision"] == prev["precision"]
                        and cand["date"] < prev["date"])
                ):
                    merged[w] = cand
        failed = still
        log.info(f"[19] {prop} {label}: after retry — {len(merged):,} dated, "
                 f"{len(failed)} chunks still failing")

    return merged, failed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true",
                        help="Tiny mode: only the first 5,000 work_ids.")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE)
    parser.add_argument("--threads", type=int, default=THREADS)
    args = parser.parse_args()

    log = setup_logging(args.test)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".test" if args.test else ""

    log.info(f"[19] DB        = {DB_PATH}")
    log.info(f"[19] OUT_DIR   = {OUT_DIR}")
    log.info(f"[19] chunk     = {args.chunk_size}")
    log.info(f"[19] threads   = {args.threads}")

    test_limit = 5_000 if args.test else None
    work_ids = load_work_ids(test_limit)
    log.info(f"[19] {len(work_ids):,} distinct work_ids loaded")

    t_start = time.time()
    all_failed: list[dict] = []
    per_prop: dict[str, dict[str, dict]] = {}
    for prop, label in PROPS:
        merged, failed = run_property(prop, label, work_ids, log,
                                      args.chunk_size, args.threads)
        per_prop[label] = merged
        all_failed.extend(failed)

        out_path = OUT_DIR / f"work_{label}{suffix}.json"
        with out_path.open("w") as fh:
            json.dump(merged, fh, ensure_ascii=False)
        log.info(f"[19] saved {out_path} ({len(merged):,} dated works)")

        time.sleep(2)  # be gentle with QLever between props

    # Merged convenience file
    universe = set().union(*per_prop.values())
    merged_all: dict[str, dict] = {
        w: {label: per_prop[label].get(w) for label in per_prop}
        for w in universe
    }
    merged_path = OUT_DIR / f"work_dates{suffix}.json"
    with merged_path.open("w") as fh:
        json.dump(merged_all, fh, ensure_ascii=False)
    log.info(f"[19] saved {merged_path} ({len(merged_all):,} works with at least one date)")

    if all_failed:
        err_path = OUT_DIR / f"work_dates.errors{suffix}.json"
        with err_path.open("w") as fh:
            json.dump(all_failed, fh, ensure_ascii=False, indent=2)
        log.info(f"[19] {len(all_failed)} chunks STILL failing -> {err_path}")
    else:
        log.info("[19] all chunks succeeded")

    elapsed = time.time() - t_start
    log.info(f"[19] total elapsed: {elapsed/60:.1f} min")

    # Quick sample
    log.info("[19] sample:")
    for w in list(merged_all.keys())[:5]:
        log.info(f"   {w}: {merged_all[w]}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
