"""Extract the *main* P31 (instance of) class for every distinct work in
data/humans_clean.sqlite3 → table ``works``.

Approach
--------
1. Read all distinct ``work_id`` values from the ``works`` table.
2. Issue chunked QLEVER queries of the form

       SELECT ?work ?cls WHERE { VALUES ?work { wd:Q1 wd:Q2 ... } ?work wdt:P31 ?cls . }

   ``wdt:P31`` is Wikidata's *truthy* predicate, so it already returns the
   preferred-rank value (or normal-rank if no preferred). When several
   classes tie at preferred rank we pick the first one returned — for
   ~95% of works this is moot.
3. Same trick for English labels of the resulting class set.

Outputs (data/all_humans/wikidata_extraction_scripts_v2/)
    work_instance_of.json       {work_qid: "Q...", ...}            (one main class)
    work_instance_of_all.json   {work_qid: ["Q...", "Q..."]}       (all P31 values)
    work_instance_labels.json   {class_qid: "English label"}
    work_instance_of.errors.json [chunk indices that failed twice]

Run
    python wikidata_extraction_scripts_v2/15_extract_work_instance_of.py --test
    python wikidata_extraction_scripts_v2/15_extract_work_instance_of.py
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import (  # noqa: E402
    QLEVER_ENDPOINT,
    clean_literal,
    extract_qid,
    qlever_stream,
)

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = (
    pathlib.Path(os.environ["WIKIDATA_OUT_DIR"])
    if os.environ.get("WIKIDATA_OUT_DIR")
    else ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"
)

# Chunk size for VALUES clauses — QLEVER comfortably handles a few thousand
# QIDs per request; larger chunks reduce round-trip overhead but raise risk
# of long requests timing out. 5,000 is a safe default seen across the v2
# scripts.
CHUNK_SIZE = 5_000

P31_TEMPLATE = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?work ?cls WHERE {{
  VALUES ?work {{ {values} }}
  ?work wdt:P31 ?cls .
}}
"""

LABEL_TEMPLATE = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?cls ?label WHERE {{
  VALUES ?cls {{ {values} }}
  ?cls rdfs:label ?label .
  FILTER(LANG(?label) = 'en')
}}
"""


def load_work_ids(limit: int | None = None) -> list[str]:
    """Distinct work_ids from the works table (Q-prefixed only)."""
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    sql = "SELECT DISTINCT work_id FROM works WHERE work_id LIKE 'Q%'"
    if limit:
        sql += f" LIMIT {limit}"
    cur.execute(sql)
    out = [row[0] for row in cur.fetchall()]
    con.close()
    return out


def chunked(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield i, seq[i : i + size]


def fetch_p31_chunk(qids: list[str]) -> dict[str, list[str]]:
    """Return {work_qid: [class_qid, ...]} for one VALUES chunk."""
    values = " ".join(f"wd:{q}" for q in qids)
    query = P31_TEMPLATE.format(values=values)
    out: dict[str, list[str]] = defaultdict(list)
    for row in qlever_stream(query):
        if len(row) < 2:
            continue
        w = extract_qid(row[0])
        c = extract_qid(row[1])
        if w.startswith("Q") and c.startswith("Q"):
            out[w].append(c)
    return out


def fetch_label_chunk(qids: list[str]) -> dict[str, str]:
    values = " ".join(f"wd:{q}" for q in qids)
    query = LABEL_TEMPLATE.format(values=values)
    out: dict[str, str] = {}
    for row in qlever_stream(query):
        if len(row) < 2:
            continue
        c = extract_qid(row[0])
        label = clean_literal(row[1])
        if c.startswith("Q") and label and c not in out:
            out[c] = label
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--test", action="store_true",
        help="Tiny mode: only the first 1,000 work_ids."
    )
    parser.add_argument(
        "--chunk-size", type=int, default=CHUNK_SIZE,
        help=f"QIDs per VALUES query (default {CHUNK_SIZE}).",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".test" if args.test else ""
    print(f"[15] DB:        {DB_PATH}")
    print(f"[15] OUT_DIR:   {OUT_DIR}")
    print(f"[15] endpoint:  {QLEVER_ENDPOINT}")
    print(f"[15] chunk:     {args.chunk_size}")

    test_limit = 1_000 if args.test else None
    work_ids = load_work_ids(limit=test_limit)
    print(f"[15] {len(work_ids):,} distinct work_ids loaded "
          f"({'TEST' if args.test else 'FULL'})")

    work_classes: dict[str, list[str]] = {}
    failed_chunks: list[dict] = []

    pbar = tqdm(total=len(work_ids), desc="P31", unit=" works", smoothing=0.1)
    for chunk_idx, chunk in chunked(work_ids, args.chunk_size):
        try:
            chunk_out = fetch_p31_chunk(chunk)
        except Exception as exc:
            failed_chunks.append({"index": chunk_idx, "size": len(chunk),
                                  "error": repr(exc)})
            pbar.update(len(chunk))
            continue
        for w, classes in chunk_out.items():
            work_classes[w] = classes
        pbar.update(len(chunk))
    pbar.close()

    # Retry failed chunks once.
    if failed_chunks:
        print(f"[15] retrying {len(failed_chunks)} failed chunk(s)…")
        still_failed = []
        for entry in failed_chunks:
            i = entry["index"]
            chunk = work_ids[i : i + entry["size"]]
            try:
                chunk_out = fetch_p31_chunk(chunk)
            except Exception as exc:
                still_failed.append({**entry, "retry_error": repr(exc)})
                continue
            for w, classes in chunk_out.items():
                work_classes[w] = classes
        failed_chunks = still_failed

    # Pick a single "main" class per work — first returned (truthy already
    # respects rank). Multi-class works keep their full list in *_all.json.
    main_class: dict[str, str] = {w: classes[0] for w, classes in work_classes.items()}

    # Now fetch English labels for the unique class set.
    classes_universe = sorted({c for cs in work_classes.values() for c in cs})
    print(f"[15] {len(classes_universe):,} unique P31 classes — fetching labels")
    class_labels: dict[str, str] = {}
    pbar = tqdm(total=len(classes_universe), desc="labels", unit=" cls", smoothing=0.1)
    for chunk_idx, chunk in chunked(classes_universe, args.chunk_size):
        try:
            class_labels.update(fetch_label_chunk(chunk))
        except Exception as exc:
            failed_chunks.append({"phase": "labels", "index": chunk_idx,
                                  "size": len(chunk), "error": repr(exc)})
        pbar.update(len(chunk))
    pbar.close()

    # Persist outputs.
    out_main = OUT_DIR / f"work_instance_of{suffix}.json"
    out_all = OUT_DIR / f"work_instance_of_all{suffix}.json"
    out_lab = OUT_DIR / f"work_instance_labels{suffix}.json"
    err_path = OUT_DIR / f"work_instance_of.errors{suffix}.json"

    with out_main.open("w") as fh:
        json.dump(main_class, fh, ensure_ascii=False)
    with out_all.open("w") as fh:
        json.dump(work_classes, fh, ensure_ascii=False)
    with out_lab.open("w") as fh:
        json.dump(class_labels, fh, ensure_ascii=False)
    if failed_chunks:
        with err_path.open("w") as fh:
            json.dump(failed_chunks, fh, ensure_ascii=False, indent=2)

    print(f"[15] saved {out_main} ({len(main_class):,} works → main P31)")
    print(f"[15] saved {out_all} (full list per work)")
    print(f"[15] saved {out_lab} ({len(class_labels):,} unique class labels)")
    if failed_chunks:
        print(f"[15] {len(failed_chunks)} chunks STILL failing → {err_path}")
    else:
        print("[15] all chunks succeeded")

    # Sample.
    print("\n[15] sample:")
    for qid, cls in list(main_class.items())[:8]:
        all_cs = work_classes[qid]
        extras = "" if len(all_cs) == 1 else f"  (+{len(all_cs)-1} more: {all_cs[1:5]})"
        print(f"  {qid} → {cls} ({class_labels.get(cls, '?')}){extras}")


if __name__ == "__main__":
    # Surface unhandled exceptions to logs/.
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
