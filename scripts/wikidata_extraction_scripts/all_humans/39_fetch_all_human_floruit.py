"""
Fetch floruit (P1317) for all Q5 (human) entities using QLever bulk query.

Outputs:
- data/all_humans/all_human_floruit.json       -> {qid: {"floruit_date": "+1450-01-01T00:00:00Z", "floruit_precision": 9}, ...}
- logs/floruit_extraction.log                  -> progress log
- task.log                                     -> live status at repo root

Precision values:
- 11 = day, 10 = month, 9 = year, 8 = decade, 7 = century, 6 = 10x century
"""

import json
import os
import time
import requests
from tqdm import tqdm

QLEVER_ENDPOINT = "https://qlever.cs.uni-freiburg.de/api/wikidata"

FLORUIT_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>

SELECT ?human ?floruit WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human wdt:P1317 ?floruit .
}
"""

FLORUIT_PRECISION_QUERY = """
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX psv: <http://www.wikidata.org/prop/statement/value/>
PREFIX wikibase: <http://wikiba.se/ontology#>

SELECT ?human ?precision WHERE {
  ?human wdt:P31 wd:Q5 .
  ?human p:P1317 ?stmt .
  ?stmt psv:P1317 ?val .
  ?val wikibase:timePrecision ?precision .
}
"""

OUTPUT_FILE = "data/all_humans/all_human_floruit.json"
RAW_DATE_FILE = "data/all_humans/all_human_floruit_raw_dates.json"
RAW_PREC_FILE = "data/all_humans/all_human_floruit_raw_precision.json"
LOG_FILE = "logs/floruit_extraction.log"
TASK_LOG = "task.log"


def extract_qid(uri: str) -> str:
    if "/Q" in uri:
        return uri.split("/")[-1].rstrip(">")
    return uri


def write_task_log(msg: str) -> None:
    with open(TASK_LOG, "w") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def append_log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def fetch_tsv(query: str, label: str) -> dict:
    append_log(f"Querying QLever for {label}")
    write_task_log(f"floruit extraction: querying {label}")

    params = {"query": query, "action": "tsv_export"}
    response = requests.get(QLEVER_ENDPOINT, params=params, stream=True, timeout=900)
    response.raise_for_status()

    out: dict = {}
    lines = response.iter_lines(decode_unicode=True)
    next(lines)  # header

    parsed = 0
    for line in tqdm(lines, desc=f"Parsing {label}", unit=" rows"):
        if not line:
            continue
        parts = line.strip().split("\t")
        if len(parts) < 2:
            continue
        qid = extract_qid(parts[0])
        out[qid] = parts[1]
        parsed += 1
        if parsed % 5000 == 0:
            write_task_log(f"floruit extraction: {label} parsed {parsed:,}")

    append_log(f"{label}: {len(out):,} rows")
    return out


def main() -> None:
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    if os.path.exists(TASK_LOG):
        os.remove(TASK_LOG)

    t0 = time.time()
    write_task_log("floruit extraction: starting")
    append_log("=== START floruit extraction (P1317) ===")

    # 1) Floruit values
    floruit_dates = fetch_tsv(FLORUIT_QUERY, "floruit dates")
    with open(RAW_DATE_FILE, "w") as f:
        json.dump(floruit_dates, f)

    # 2) Floruit precision (statement-level)
    floruit_precision_raw = fetch_tsv(FLORUIT_PRECISION_QUERY, "floruit precision")
    floruit_precision: dict = {}
    for qid, raw in floruit_precision_raw.items():
        try:
            p = int(float(raw))
            if qid not in floruit_precision or p > floruit_precision[qid]:
                floruit_precision[qid] = p
        except (ValueError, TypeError):
            continue
    with open(RAW_PREC_FILE, "w") as f:
        json.dump(floruit_precision, f)

    # 3) Combine
    combined: dict = {}
    for qid, dt in floruit_dates.items():
        combined[qid] = {
            "floruit_date": dt,
            "floruit_precision": floruit_precision.get(qid),
        }

    with open(OUTPUT_FILE, "w") as f:
        json.dump(combined, f)

    elapsed = time.time() - t0
    msg = (
        f"floruit extraction complete: {len(combined):,} humans, "
        f"with precision: {sum(1 for v in combined.values() if v['floruit_precision'] is not None):,}, "
        f"elapsed: {elapsed/60:.1f} min"
    )
    append_log(msg)
    write_task_log(msg)
    print(msg)
    print(f"Saved -> {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
