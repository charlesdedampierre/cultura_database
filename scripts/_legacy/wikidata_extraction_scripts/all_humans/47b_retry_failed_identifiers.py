"""Path A — retry pass for PIDs that errored in script 47.

Looks at all per-property files under
data/all_humans/identifiers_per_property/<Pxxx>.json that contain an
`error` field (HTTP 502 / 429 / timeout / connection), and re-attempts
their extraction with low concurrency (3 threads) and longer back-off,
to avoid the QLever rate-limit cluster that caused them to fail.

Per-property JSON files are overwritten on success.
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

import requests


def _find_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "data").exists() and (p / "task.log").exists():
            return p
        p = p.parent
    return Path(__file__).resolve().parents[3]


ROOT = _find_root(Path(__file__).resolve())
PROP_LIST_PATH = ROOT / "data" / "all_humans" / "all_external_id_properties.json"
OUT_DIR = ROOT / "data" / "all_humans" / "identifiers_per_property"
TASK_LOG = ROOT / "task.log"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "identifier_extraction_v2.log"
ERROR_FILE = LOG_DIR / "identifier_extraction_v2_retryB_errors.json"

QLEVER = "https://qlever.cs.uni-freiburg.de/api/wikidata"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}
THREADS = 3
TIMEOUT = 600
MAX_RETRIES = 5

_log_lock = Lock()


def log(msg: str) -> None:
    stamped = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    with _log_lock:
        print(stamped, flush=True)
        LOG_DIR.mkdir(exist_ok=True)
        with TASK_LOG.open("a") as f:
            f.write(stamped + "\n")
        with LOG_FILE.open("a") as f:
            f.write(stamped + "\n")


def out_path(pid: str) -> Path:
    return OUT_DIR / f"{pid}.json"


def query_property(pid: str) -> dict:
    sparql = f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?h ?v WHERE {{
  ?h wdt:P31 wd:Q5 .
  ?h wdt:{pid} ?v .
}}"""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(
                QLEVER,
                params={"query": sparql, "action": "tsv_export"},
                headers=HEADERS,
                timeout=TIMEOUT,
                stream=True,
            )
            if r.status_code in (429, 502, 503, 504):
                wait = (3 ** attempt) + 2
                time.sleep(wait)
                last_err = f"HTTP {r.status_code} (attempt {attempt+1})"
                continue
            r.raise_for_status()
            pairs = []
            it = r.iter_lines(decode_unicode=True)
            try:
                next(it)
            except StopIteration:
                return {"pid": pid, "n_pairs": 0, "pairs": [], "error": None}
            for line in it:
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                qid_uri = parts[0]
                qid = (qid_uri[1:-1].rsplit("/", 1)[-1]
                       if qid_uri.startswith("<") and qid_uri.endswith(">")
                       else qid_uri.rsplit("/", 1)[-1].rstrip(">"))
                if not qid.startswith("Q"):
                    continue
                value = parts[1]
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("<") and value.endswith(">"):
                    value = value[1:-1]
                pairs.append([qid, value])
            return {"pid": pid, "n_pairs": len(pairs), "pairs": pairs, "error": None}
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            time.sleep((2 ** attempt) + 2)
    return {"pid": pid, "n_pairs": 0, "pairs": [], "error": last_err}


def needs_retry(pid: str) -> bool:
    p = out_path(pid)
    if not p.exists():
        return True  # never written
    try:
        d = json.loads(p.read_text())
    except Exception:
        return True
    return bool(d.get("error"))


def process_one(pid: str) -> dict:
    res = query_property(pid)
    out_path(pid).parent.mkdir(parents=True, exist_ok=True)
    out_path(pid).write_text(json.dumps(res, ensure_ascii=False))
    return res


def collect_pids_to_retry() -> list[str]:
    canonical = json.loads(PROP_LIST_PATH.read_text())
    targets = [p["property_id"] for p in canonical["properties"]]
    return [p for p in targets if needs_retry(p) and out_path(p).exists() or
            (p in [q["property_id"] for q in canonical["properties"]] and not out_path(p).exists())]


def main() -> None:
    canonical = json.loads(PROP_LIST_PATH.read_text())
    targets = [p["property_id"] for p in canonical["properties"]]
    retry_pids = [p for p in targets if needs_retry(p)]
    log(f"[47b] retry pass: {len(retry_pids)} PIDs need re-extraction "
        f"(threads={THREADS}, exp-backoff)")

    if not retry_pids:
        log("[47b] nothing to retry, exiting")
        return

    t0 = time.time()
    n_done = 0
    n_recovered = 0
    n_still_failing = 0
    still_failing: list[dict] = []

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(process_one, p): p for p in retry_pids}
        for f in as_completed(futs):
            pid = futs[f]
            res = f.result()
            n_done += 1
            if res.get("error"):
                n_still_failing += 1
                still_failing.append({"pid": pid, "error": res["error"]})
            else:
                n_recovered += 1
            if n_done % 50 == 0 or n_done == len(retry_pids):
                rate = n_done / max(time.time() - t0, 0.01)
                eta_min = (len(retry_pids) - n_done) / max(rate, 0.01) / 60
                log(f"[47b] progress {n_done}/{len(retry_pids)} "
                    f"recovered={n_recovered} still_failing={n_still_failing} "
                    f"rate={rate:.2f} props/s eta={eta_min:.1f} min")

    ERROR_FILE.write_text(json.dumps(still_failing, indent=2))
    log(f"[47b] DONE in {(time.time()-t0)/60:.1f} min  "
        f"recovered={n_recovered} still_failing={n_still_failing}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[47b] FATAL: {e}")
        raise
