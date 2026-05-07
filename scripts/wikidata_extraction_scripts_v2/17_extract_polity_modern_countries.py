"""Fetch the modern sovereign states associated with each Cliopatria polity.

For every polity in `polities_cliopatria` that carries a `wikidata_id`, we
collect every present-day country (Q with ISO 3166-1 alpha-3 / P298) that
Wikidata links to the polity through one of these patterns:

    direct:    ?polity wdt:P17 ?country
    capital:   ?polity wdt:P36 ?cap     . ?cap wdt:P17 ?country
    successor: ?polity wdt:P1366 ?succ  . ?succ wdt:P17 ?country
    parent:    ?polity wdt:P131 ?adm    . ?adm  wdt:P17 ?country

We avoid recursive paths (`P1366*` / `P131*`) — they explode and time out on
QLever for the empire-sized polities.

Output (single JSON keyed by polity QID):
    data/all_humans/wikidata_extraction_scripts_v2/polity_modern_countries.json

    {
      "Q42534": {
        "polity_qid": "Q42534",
        "countries": [
          {"country_qid": "Q668", "iso_a3_code": "IND", "source": "P17"},
          {"country_qid": "Q843", "iso_a3_code": "PAK", "source": "P17"}
        ]
      }, ...
    }

We also write `polity_modern_countries.errors.json` listing batches that
failed; the script retries them once at the end.

Run:
    python scripts/wikidata_extraction_scripts_v2/17_extract_polity_modern_countries.py --test
    python scripts/wikidata_extraction_scripts_v2/17_extract_polity_modern_countries.py
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wikidata import qlever_stream, extract_qid, clean_literal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = ROOT / "data" / "all_humans" / "wikidata_extraction_scripts_v2"
LOG_PATH = ROOT / "logs" / "17_extract_polity_modern_countries.log"
TASK_LOG = ROOT / "task.log"

QUERY_TEMPLATE = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?polity ?country ?iso3 ?src WHERE {{
  VALUES ?polity {{ {values} }}
  {{
    ?polity wdt:P17 ?country .
    ?country wdt:P298 ?iso3 .
    BIND("P17" AS ?src)
  }} UNION {{
    ?polity wdt:P36 ?cap .
    ?cap wdt:P17 ?country .
    ?country wdt:P298 ?iso3 .
    BIND("P36/P17" AS ?src)
  }} UNION {{
    ?polity wdt:P1366 ?succ .
    ?succ wdt:P17 ?country .
    ?country wdt:P298 ?iso3 .
    BIND("P1366/P17" AS ?src)
  }} UNION {{
    ?polity wdt:P131 ?adm .
    ?adm wdt:P17 ?country .
    ?country wdt:P298 ?iso3 .
    BIND("P131/P17" AS ?src)
  }}
}}
"""


def load_polity_qids(test: bool) -> list[str]:
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.execute(
        "SELECT wikidata_id FROM polities_cliopatria "
        "WHERE wikidata_id IS NOT NULL AND wikidata_id != '' "
        "ORDER BY id"
    )
    qids = [r[0] for r in cur.fetchall() if r[0] and r[0].startswith("Q")]
    conn.close()
    if test:
        return qids[:50]
    return qids


def run_batch(qids: list[str], timeout: int = 120) -> list[tuple[str, str, str, str]]:
    values = " ".join(f"wd:{q}" for q in qids)
    query = QUERY_TEMPLATE.format(values=values)
    rows: list[tuple[str, str, str, str]] = []
    for row in qlever_stream(query, timeout=timeout):
        if len(row) < 4:
            continue
        polity = extract_qid(row[0])
        country = extract_qid(row[1])
        iso3 = clean_literal(row[2]).upper()
        src = clean_literal(row[3])
        if iso3 and len(iso3) == 3 and iso3.isalpha():
            rows.append((polity, country, iso3, src))
    return rows


def write_task_log(msg: str) -> None:
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] [17] {msg}\n"
    with TASK_LOG.open("a", encoding="utf-8") as f:
        f.write(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line)
    print(line, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--test", action="store_true", help="Only run on first 50 polities.")
    parser.add_argument("--batch-size", type=int, default=50, help="Polity QIDs per QLever query.")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / (
        "polity_modern_countries.test.json" if args.test else "polity_modern_countries.json"
    )
    err_file = OUT_DIR / (
        "polity_modern_countries.test.errors.json"
        if args.test
        else "polity_modern_countries.errors.json"
    )

    qids = load_polity_qids(test=args.test)
    write_task_log(
        f"START mode={'TEST' if args.test else 'FULL'} polities={len(qids)} batch={args.batch_size}"
    )

    out: dict[str, dict] = {q: {"polity_qid": q, "countries": []} for q in qids}
    seen: dict[str, set[tuple[str, str]]] = {q: set() for q in qids}
    errors: list[dict] = []

    started = time.time()
    batches = [qids[i : i + args.batch_size] for i in range(0, len(qids), args.batch_size)]
    for batch in tqdm(batches, desc="qlever", unit="batch"):
        try:
            rows = run_batch(batch)
        except Exception as exc:  # noqa: BLE001
            errors.append({"batch": batch, "error": repr(exc)})
            write_task_log(f"  batch error ({len(batch)} polities): {exc}")
            continue
        for polity, country, iso3, src in rows:
            key = (country, src)
            if polity in out and key not in seen[polity]:
                seen[polity].add(key)
                out[polity]["countries"].append(
                    {"country_qid": country, "iso_a3_code": iso3, "source": src}
                )

    if errors:
        write_task_log(f"retrying {len(errors)} failed batches once")
        retry_errors: list[dict] = []
        for entry in errors:
            try:
                rows = run_batch(entry["batch"], timeout=180)
            except Exception as exc:  # noqa: BLE001
                retry_errors.append({"batch": entry["batch"], "error": repr(exc)})
                continue
            for polity, country, iso3, src in rows:
                key = (country, src)
                if polity in out and key not in seen[polity]:
                    seen[polity].add(key)
                    out[polity]["countries"].append(
                        {"country_qid": country, "iso_a3_code": iso3, "source": src}
                    )
        errors = retry_errors

    with out_file.open("w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    if errors:
        with err_file.open("w", encoding="utf-8") as f:
            json.dump(errors, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - started
    have_country = sum(1 for v in out.values() if v["countries"])
    n_links = sum(len(v["countries"]) for v in out.values())
    write_task_log(
        f"DONE polities={len(out)} with_country={have_country} links={n_links} "
        f"errors={len(errors)} elapsed={elapsed:.1f}s -> {out_file.name}"
    )

    print("\nsample (first 5 with countries):")
    shown = 0
    for qid, rec in out.items():
        if rec["countries"]:
            print(f"  {qid}: {rec['countries']}")
            shown += 1
            if shown >= 5:
                break


if __name__ == "__main__":
    main()
