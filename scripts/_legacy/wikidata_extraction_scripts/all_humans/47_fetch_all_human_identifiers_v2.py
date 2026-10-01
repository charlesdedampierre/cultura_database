"""Path A — step 3.

Bulk extract all (human, value) pairs from QLever ONLY for external-ID
properties that are MISSING from the local DB — i.e., properties present
in the canonical list (`all_external_id_properties.json`) but NOT in the
existing `identifier_types` table of `data/humans_clean.sqlite3`. Properties
already in the DB are left alone (we keep the rows we have).

Per-property JSON is written under
`data/all_humans/identifiers_per_property/<Pxxx>.json`. Existing files are
skipped on resume, giving free checkpointing.

Concurrency: 8 worker threads (QLever rate-limits aggressively above ~10).
Each 429 response is retried up to 3 times with exponential backoff.

Errors are logged to `logs/identifier_extraction_v2_errors.json` and
re-tried once at the end of the run.

Progress (every PROGRESS_EVERY properties) is appended to
`task.log` at repo root, plus `logs/identifier_extraction_v2.log`.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

import requests

ROOT = Path(__file__).resolve().parents[2]
PROP_LIST = ROOT / "data" / "all_humans" / "all_external_id_properties.json"
DB = ROOT / "data" / "humans_clean.sqlite3"
OUT_DIR = ROOT / "data" / "all_humans" / "identifiers_per_property"
TASK_LOG = ROOT / "task.log"
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "identifier_extraction_v2.log"
PROCESSED_FILE = LOG_DIR / "identifier_extraction_v2_processed.json"
ERROR_FILE = LOG_DIR / "identifier_extraction_v2_errors.json"
MISSING_PIDS_FILE = LOG_DIR / "identifier_extraction_v2_missing_pids.json"

QLEVER = "https://qlever.cs.uni-freiburg.de/api/wikidata"
HEADERS = {"User-Agent": "cultura-database-research/1.0 (cdedampierre@bunka.ai)"}

THREADS = 8
PROGRESS_EVERY = 50
TIMEOUT = 600
MAX_RETRIES = 3

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


def query_property(pid: str) -> dict:
    """Fetch all (human, value) pairs for one property. Returns
    {pid, n_pairs, pairs: [[qid, value], ...], error: None|str}."""
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
            if r.status_code == 429:
                wait = (4 ** attempt) + 1
                time.sleep(wait)
                last_err = f"HTTP 429 (attempt {attempt+1})"
                continue
            r.raise_for_status()
            pairs = []
            it = r.iter_lines(decode_unicode=True)
            try:
                next(it)  # header
            except StopIteration:
                return {"pid": pid, "n_pairs": 0, "pairs": [], "error": None}
            for line in it:
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                qid_uri = parts[0]
                if qid_uri.startswith("<") and qid_uri.endswith(">"):
                    qid = qid_uri[1:-1].rsplit("/", 1)[-1]
                else:
                    qid = qid_uri.rsplit("/", 1)[-1].rstrip(">")
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
            time.sleep((2 ** attempt) + 1)
    return {"pid": pid, "n_pairs": 0, "pairs": [], "error": last_err}


def out_path(pid: str) -> Path:
    return OUT_DIR / f"{pid}.json"


def already_done(pid: str) -> bool:
    p = out_path(pid)
    if not p.exists():
        return False
    try:
        d = json.loads(p.read_text())
        return d.get("error") is None
    except Exception:
        return False


def process_one(pid: str) -> dict:
    if already_done(pid):
        return {"pid": pid, "skipped": True}
    result = query_property(pid)
    out_path(pid).parent.mkdir(parents=True, exist_ok=True)
    out_path(pid).write_text(json.dumps(result, ensure_ascii=False))
    return result


def load_property_list() -> list[str]:
    data = json.loads(PROP_LIST.read_text())
    return [p["property_id"] for p in data["properties"]]


def load_existing_pids_from_db() -> set[str]:
    """Property IDs already present in the local identifier_types table —
    we will NOT re-extract these."""
    if not DB.exists():
        return set()
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT property_id FROM identifier_types").fetchall()
    conn.close()
    return {r[0] for r in rows if r and r[0]}


def missing_pids() -> list[str]:
    """All canonical external-ID properties NOT yet in the local DB."""
    canonical = load_property_list()
    existing = load_existing_pids_from_db()
    missing = [p for p in canonical if p not in existing]
    MISSING_PIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MISSING_PIDS_FILE.write_text(json.dumps({
        "computed_at": datetime.now().isoformat(timespec="seconds"),
        "n_canonical": len(canonical),
        "n_existing_in_db": len(existing),
        "n_missing": len(missing),
        "missing": missing,
    }, indent=2))
    return missing


def main(retry_errors: bool = True) -> None:
    if not PROP_LIST.exists():
        log("[47] property list not found; run script 45 first")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_pids = missing_pids()
    pending = [p for p in all_pids if not already_done(p)]
    log(f"[47] starting v2 identifier extraction (MISSING PIDS ONLY): "
        f"total_missing={len(all_pids):,} "
        f"already_done={len(all_pids)-len(pending):,} pending={len(pending):,} "
        f"threads={THREADS}")

    t0 = time.time()
    n_done = len(all_pids) - len(pending)
    n_total = len(all_pids)
    n_errors = 0
    errors: list[dict] = []

    with ThreadPoolExecutor(max_workers=THREADS) as ex:
        futs = {ex.submit(process_one, p): p for p in pending}
        for f in as_completed(futs):
            pid = futs[f]
            res = f.result()
            n_done += 1
            if res.get("error"):
                n_errors += 1
                errors.append({"pid": pid, "error": res["error"]})
            if n_done % PROGRESS_EVERY == 0 or n_done == n_total:
                rate = (n_done - (n_total - len(pending))) / max(time.time() - t0, 0.01)
                eta_s = (n_total - n_done) / max(rate, 0.01)
                log(f"[47] progress {n_done}/{n_total} "
                    f"({n_done/n_total*100:.1f}%)  "
                    f"errors={n_errors}  "
                    f"rate={rate:.2f} props/s  "
                    f"eta={eta_s/60:.1f} min")

    ERROR_FILE.write_text(json.dumps(errors, indent=2))
    log(f"[47] first pass complete: {n_done}/{n_total}, errors={n_errors}")

    if retry_errors and errors:
        log(f"[47] retrying {len(errors)} errored properties...")
        retry_pids = [e["pid"] for e in errors]
        for p in retry_pids:
            try:
                out_path(p).unlink(missing_ok=True)
            except Exception:
                pass
        retry_errors_2: list[dict] = []
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            futs = {ex.submit(process_one, p): p for p in retry_pids}
            for f in as_completed(futs):
                pid = futs[f]
                res = f.result()
                if res.get("error"):
                    retry_errors_2.append({"pid": pid, "error": res["error"]})
        ERROR_FILE.write_text(json.dumps(retry_errors_2, indent=2))
        log(f"[47] retry pass complete: {len(retry_pids) - len(retry_errors_2)} recovered, "
            f"{len(retry_errors_2)} still failing")

    PROCESSED_FILE.write_text(json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "n_total_properties": n_total,
        "n_completed": n_total - n_errors,
        "n_errors": n_errors,
    }, indent=2))
    log(f"[47] DONE in {(time.time()-t0)/60:.1f} min")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"[47] FATAL: {e}")
        raise
