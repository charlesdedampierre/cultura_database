"""
Classify every unique Wikidata P31 class that appears in the `cities` table as
an urban settlement (urban_settlement: true) or not, using Google
Gemini 3 Flash Preview through the OpenRouter API.

"Urban settlement" means the entity denotes a populated place suitable for an
urbanisation study — cities, towns, villages, hamlets, suburbs, communes,
municipalities, neighborhoods, urban settlements, etc.

Not urban settlements: administrative regions at country/state/county/province
level, streets, buildings, monuments, islands without a settlement focus,
natural features, events, etc.

Input  : data/all_humans/city_entity_types.json
Output : data/all_humans/entity_type_classification.json
         data/all_humans/entity_type_classification_errors.json
API key: loaded from .env as OPEN_ROUTER_API
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
from dotenv import load_dotenv
from tqdm import tqdm

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "google/gemini-3-flash-preview"

INPUT_PATH = "data/all_humans/city_entity_types.json"
OUT_PATH = "data/all_humans/entity_type_classification.json"
ERR_PATH = "data/all_humans/entity_type_classification_errors.json"
TASK_LOG = "task.log"

BATCH_SIZE = 40        # types per API request
MAX_RETRIES = 4
TIMEOUT = 120
NUM_WORKERS = 8        # parallel HTTP workers (I/O bound)
SAVE_EVERY = 20        # flush partial JSON every N completed batches

SYSTEM_PROMPT = """You classify Wikidata P31 (instance-of) classes.
For each class you receive (id + English label), decide whether it denotes
an URBAN SETTLEMENT: a populated place (any size) that a researcher studying
urbanisation would count as a "city-like" location on a map.

urban_settlement = true  ->  city, town, village, hamlet, borough, suburb,
    neighborhood, metropolis, megacity, commune, municipality, comune,
    frazione, Ortsteil, human settlement, populated place, locality,
    census-designated place, unincorporated community, etc.
    Anything that is fundamentally "a place where people live as a settlement"
    including small/rural ones, and sub-city units like districts/quarters.

urban_settlement = false ->  country, sovereign state, U.S. state,
    federal subject, region, province, county, district-as-admin-division
    (when it is the whole admin unit, not a settlement), island without a
    settlement focus, building type (hospital, castle, château, station),
    street, road, bridge, square, park, monument, cemetery, natural
    feature, event, organization, company, ethnic group, geopolitical
    entity, etc. Also false for things like "former country", "historical
    state", "dissolved municipality" (dissolved => no longer a place on
    today's map) UNLESS the label clearly still refers to a settlement.

If a label is ambiguous (e.g. contains "settlement" + "administrative"),
prefer true if it is primarily a populated place, false if primarily an
admin region. When in doubt for mixed admin/settlement classes that CONTAIN
a settlement (e.g. "commune of France", "municipality of X"), return true.

Return STRICT JSON with the exact schema:
{
  "results": [
    {"id": "Q...", "urban_settlement": true, "reason": "short phrase"},
    ...
  ]
}
No prose outside the JSON. Include every id you were given, in the same order.
"""


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_unique_types() -> dict[str, str]:
    with open(INPUT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    types: dict[str, str] = {}
    for _qid, info in data.items():
        for t in info.get("types", []):
            tid = t.get("id")
            if tid and tid not in types:
                types[tid] = t.get("label") or tid
    return types


def classify_batch(api_key: str, items: list[tuple[str, str]]) -> list[dict]:
    """Classify one batch. Returns list aligned with input order."""
    user_payload = {
        "types": [{"id": qid, "label": label} for qid, label in items]
    }
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "Classify these P31 classes:\n"
                + json.dumps(user_payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bunka.ai/",
        "X-Title": "Cultura urbanisation classifier",
    }

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json=body,
                timeout=TIMEOUT,
            )
            if resp.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
                wait = 1.5 * (2**attempt)
                time.sleep(wait)
                last_exc = requests.HTTPError(f"{resp.status_code} {resp.reason}")
                continue
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            results = parsed.get("results")
            if not isinstance(results, list):
                raise ValueError("model did not return a results list")
            return results
        except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError) as e:
            last_exc = e
            time.sleep(1.5 * (2**attempt))
    raise last_exc if last_exc else RuntimeError("classify_batch: unknown error")


def main() -> int:
    load_dotenv()
    api_key = os.getenv("OPEN_ROUTER_API")
    if not api_key:
        log("ERROR: OPEN_ROUTER_API not set in .env")
        return 1

    log("=" * 60)
    log("CLASSIFY URBAN SETTLEMENTS (P31 types)")
    log(f"model: {MODEL}")
    log("=" * 60)

    types = load_unique_types()
    log(f"Loaded {len(types):,} unique P31 classes from {INPUT_PATH}")

    # Resume support: if OUT_PATH exists, skip already-classified ids
    existing: dict[str, dict] = {}
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH, encoding="utf-8") as f:
            existing = json.load(f)
        log(f"Resuming: {len(existing):,} already classified")

    todo = [(qid, lbl) for qid, lbl in types.items() if qid not in existing]
    log(f"To classify: {len(todo):,}")

    if not todo:
        log("Nothing to do. Exiting.")
        return 0

    batches = [todo[i : i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    log(f"Prepared {len(batches)} batches of up to {BATCH_SIZE} items")
    log(f"Running {NUM_WORKERS} parallel workers")

    errors: list[dict] = []
    lock = threading.Lock()
    processed_batches = 0

    def worker(batch: list[tuple[str, str]]):
        try:
            results = classify_batch(api_key, batch)
            results_by_id = {r.get("id"): r for r in results if isinstance(r, dict)}
            local_updates: dict[str, dict] = {}
            local_errors: list[dict] = []
            for qid, label in batch:
                r = results_by_id.get(qid)
                if r is None:
                    local_errors.append(
                        {"id": qid, "label": label, "error": "missing in response"}
                    )
                    continue
                local_updates[qid] = {
                    "label": label,
                    "urban_settlement": bool(r.get("urban_settlement")),
                    "reason": r.get("reason", ""),
                }
            return local_updates, local_errors, None
        except Exception as e:  # noqa: BLE001
            return {}, [{"id": q, "label": l, "error": str(e)} for q, l in batch], e

    pbar = tqdm(total=len(batches), desc="Classifying", unit="batch")
    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as pool:
        futures = [pool.submit(worker, b) for b in batches]
        for fut in as_completed(futures):
            updates, errs, exc = fut.result()
            with lock:
                existing.update(updates)
                errors.extend(errs)
                processed_batches += 1
                if exc is not None:
                    log(f"  batch failed after retries: {exc}")
                pbar.set_postfix({"done": len(existing), "errors": len(errors)})
                pbar.update(1)
                if processed_batches % SAVE_EVERY == 0:
                    with open(OUT_PATH, "w", encoding="utf-8") as f:
                        json.dump(existing, f, ensure_ascii=False)
    pbar.close()

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False)
    if errors:
        with open(ERR_PATH, "w", encoding="utf-8") as f:
            json.dump(errors, f, ensure_ascii=False)

    urban = sum(1 for v in existing.values() if v.get("urban_settlement"))
    log(f"Classified: {len(existing):,}")
    log(f"  urban_settlement=true : {urban:,}")
    log(f"  urban_settlement=false: {len(existing) - urban:,}")
    log(f"  errors: {len(errors)}")
    log(f"Wrote {OUT_PATH}")
    log("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
