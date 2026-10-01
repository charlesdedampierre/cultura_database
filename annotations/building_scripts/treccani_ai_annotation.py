"""AI annotation of Treccani biographies, following TreccaniAnnotation in datamodel_annotations.py.

For N random individuals of the Treccani sample, a language model reads the downloaded
biography twice — once for the location, once for the productivity window — and the two
automatic checks are computed on its quotes. Saved to treccani_ai_annotations.parquet.

Usage: .venv/bin/python annotations/building_scripts/treccani_ai_annotation.py [--n 5]
"""

import argparse
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from dotenv import load_dotenv
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "datamodels"))

import datamodel_annotations as A

DB = ROOT / "data" / "cultura" / "humans_clean_v2_sample_treccani.duckdb"
FOLDER = ROOT / "annotations" / "treccani_validation"
TEXTS = FOLDER / "_cache" / "dbi_pages.jsonl"
CACHE = FOLDER / "_cache" / "ai_annotation_responses.jsonl"
OUT = FOLDER / "treccani_ai_annotations.parquet"
PROMPTS = ROOT / "scripts" / "prompts"

MODEL = "google/gemini-3.5-flash"
PROMPT_IDS = {"location_ai_extracted": "treccani_location", "productivity_window_ai_extracted": "treccani_productivity_window"}
TEXT_CAP = 25_000
SEED = 42
WORKERS = 5
API = "https://openrouter.ai/api/v1"


def normalise(text):
    return re.sub(r"\s+", " ", text or "").strip().lower()


def load_texts():
    return {row["wikidata_id"]: row for row in map(json.loads, TEXTS.open(encoding="utf-8"))}


def load_cache():
    if not CACHE.exists():
        return {}
    rows = map(json.loads, CACHE.open(encoding="utf-8"))
    return {(row["qid"], row["prompt_id"]): row for row in rows if "response" in row}


def model_price():
    models = requests.get(f"{API}/models", timeout=30).json()["data"]
    pricing = next(model["pricing"] for model in models if model["id"] == MODEL)
    return float(pricing["prompt"]), float(pricing["completion"])


def ask(prompt, key):
    response = requests.post(
        f"{API}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "usage": {"include": True}},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def query(qid, prompt_id, text, key):
    prompt = (PROMPTS / f"{prompt_id}.txt").read_text(encoding="utf-8").replace("{biography}", text[:TEXT_CAP])
    for attempt in range(2):
        try:
            return {"qid": qid, "prompt_id": prompt_id, "prompt": prompt, "response": ask(prompt, key)}
        except (requests.RequestException, ValueError) as error:
            if attempt:
                return {"qid": qid, "prompt_id": prompt_id, "prompt": prompt, "error": str(error)}


def cost(response, price):
    usage = response.get("usage") or {}
    if usage.get("cost") is not None:
        return float(usage["cost"])
    return usage.get("prompt_tokens", 0) * price[0] + usage.get("completion_tokens", 0) * price[1]


def ai_answer(cached, text, price):
    content = cached["response"]["choices"][0]["message"]["content"]
    answer = json.loads(re.sub(r"^```(json)?|```$", "", content.strip()))
    extracts = tuple(answer.get("source_verbatim") or ())
    written = answer.get("answer_as_written_in_text")
    body = normalise(text[:TEXT_CAP])
    return A.AIAnswer(
        answer=answer.get("answer"),
        answer_as_written_in_text=written,
        answer_as_written_in_text_english=answer.get("answer_as_written_in_text_english"),
        confidence=answer.get("confidence"),
        reasoning=answer.get("reasoning"),
        source_verbatim=extracts,
        source_verbatim_english=tuple(answer.get("source_verbatim_english") or ()),
        source_verbatim_not_invented=bool(extracts) and all(normalise(extract) in body for extract in extracts),
        answer_supported_by_source_verbatim=bool(written) and any(normalise(written) in normalise(extract) for extract in extracts),
        model_name=MODEL,
        prompt_id=cached["prompt_id"],
        prompt=cached["prompt"],
        cost_estimated=cost(cached["response"], price),
    )


def entities(qids):
    connection = duckdb.connect(str(DB), read_only=True)
    rows = connection.execute("SELECT entity FROM individual WHERE entity.qid IN (SELECT unnest(?))", [qids]).fetchall()
    return {entity["qid"]: A.WikidataEntity(**entity) for (entity,) in rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    key = os.environ["OPEN_ROUTER_API"]

    texts = load_texts()
    population = sorted(entities(list(texts)))
    qids = random.Random(SEED).sample(population, args.n)
    print(f"{len(population)} individuals with a downloaded text in {DB.name}; annotating {len(qids)}: {', '.join(qids)}")

    cache = load_cache()
    todo = [(qid, prompt_id) for qid in qids for prompt_id in PROMPT_IDS.values() if (qid, prompt_id) not in cache]
    print(f"{len(todo)} queries to send to {MODEL}, {len(qids) * len(PROMPT_IDS) - len(todo)} already cached")
    failures = []
    with ThreadPoolExecutor(WORKERS) as pool, CACHE.open("a", encoding="utf-8") as handle:
        for result in tqdm(pool.map(lambda job: query(*job, texts[job[0]]["text"], key), todo), total=len(todo), desc="queries"):
            if "error" in result:
                failures.append(result)
                continue
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            cache[result["qid"], result["prompt_id"]] = result
    if failures:
        raise SystemExit(f"{len(failures)} queries failed, nothing written; first error: {failures[0]['error']}")

    price = model_price()
    people = entities(qids)
    annotations = [
        A.TreccaniAnnotation(
            entity=people[qid],
            treccani_url=texts[qid]["dbi_url"],
            **{field: ai_answer(cache[qid, prompt_id], texts[qid]["text"], price) for field, prompt_id in PROMPT_IDS.items()},
        )
        for qid in qids
    ]
    pq.write_table(pa.Table.from_pylist([annotation.model_dump(mode="json") for annotation in annotations]), OUT)
    total = sum(getattr(a, field).cost_estimated or 0 for a in annotations for field in PROMPT_IDS)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(annotations)} individuals, total cost ${total:.4f}")


if __name__ == "__main__":
    main()
