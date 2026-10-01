"""AI annotation of Treccani biographies, following TreccaniAnnotation in datamodel_annotations.py.

For N random individuals of the Treccani sample, a language model reads the downloaded
biography twice — once for the location, once for the productivity window — then matches
those two answers to a Cliopatria polity, chosen from the polities whose territory overlaps
Italy during the window. The automatic checks are computed on its quotes: against the
biography for the first two, against the candidate list for the polity.
Saved to treccani_ai_annotations.parquet.

Usage: .venv/bin/python annotations/building_scripts/treccani_ai_annotation.py [--n 5] [--model google/gemini-2.5-flash --thinking on|off|minimal --no-reasoning --out name.parquet]
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
from shapely.geometry import box, shape
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
THINKING = "default"
WRITE_REASONING = True
REASONING_OPTION = {"on": {"enabled": True}, "off": {"enabled": False}, "minimal": {"effort": "minimal"}}
TEXT_PROMPTS = {"location_ai_extracted": "treccani_location", "productivity_window_ai_extracted": "treccani_productivity_window"}
POLITY_PROMPT = "treccani_polity"
POLITY_SOURCE = "Cliopatria polities overlapping Italy during the window, from the polity table of humans_clean_v2_sample_treccani.duckdb"
ITALY = box(6.5, 36.0, 18.6, 47.1)
TEXT_CAP = 25_000
SEED = 42
WORKERS = 5
API = "https://openrouter.ai/api/v1"


def normalise(text):
    text = re.sub(r"[’‘`]", "'", text or "")
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.;:!?)\]»])|([(\[«])\s+", r"\1\2", text).strip().lower()


def supported(written, extracts):
    """The answer as written is in the quotes: every year of it when it has years, the whole of it otherwise."""
    quotes = " ".join(normalise(extract) for extract in extracts)
    years = re.findall(r"\d{3,4}", written or "")
    if years:
        return all(year in quotes for year in years)
    return bool(written) and normalise(written) in quotes


def window_years(answer):
    """The years a window answer covers: its first and last year, or the bounds of the centuries it names."""
    years = [int(year) for year in re.findall(r"\b\d{3,4}\b", answer or "")]
    if years:
        return min(years), max(years)
    centuries = [int(c) for c in re.findall(r"(\d{1,2})(?:st|nd|rd|th) century", answer or "")]
    if centuries:
        return (min(centuries) - 1) * 100 + 1, max(centuries) * 100
    return None


def load_texts():
    return {row["wikidata_id"]: row for row in map(json.loads, TEXTS.open(encoding="utf-8"))}


def parsed(response):
    """The model's JSON answer, or None when the reply was cut off or is not valid JSON."""
    choice = response["choices"][0]
    if choice.get("finish_reason") == "error":
        return None
    try:
        return json.loads(re.sub(r"^```(json)?|```$", "", choice["message"]["content"].strip()))
    except (json.JSONDecodeError, TypeError):
        return None


def load_cache():
    if not CACHE.exists():
        return {}
    rows = map(json.loads, CACHE.open(encoding="utf-8"))
    return {(row["qid"], row["prompt_id"], row.get("setting", "google/gemini-3.5-flash")): row for row in rows if "response" in row and parsed(row["response"]) is not None}


def setting():
    """The model and its thinking option, as one label: cached answers are reused only for the same one."""
    label = MODEL + {"default": "", "on": " +thinking", "off": " -thinking", "minimal": " minimal-thinking"}[THINKING]
    return label if WRITE_REASONING else label + " -reasoning"


def load_territories():
    connection = duckdb.connect(str(DB), read_only=True)
    return connection.execute("""
        SELECT polity.cliopatria_id, polity.name, territory.start_year, territory.end_year, territory.geometry
        FROM polity, unnest(polity.territories) AS unnested(territory)
        WHERE territory.start_year IS NOT NULL AND territory.end_year IS NOT NULL
    """).fetchall()


def candidates(territories, years):
    """One line per polity holding ground in Italy during the window, with the years Cliopatria gives it."""
    start, end = years
    found = {}
    for polity_id, name, first, last, geometry in territories:
        if first <= end and last >= start and shape(json.loads(geometry)).intersects(ITALY):
            low, high = found.get((polity_id, name), (first, last))
            found[polity_id, name] = (min(low, first), max(high, last))
    return "\n".join(f"{polity_id} | {name} | {low}–{high}" for (polity_id, name), (low, high) in sorted(found.items(), key=lambda item: item[0][1]))


def model_price():
    models = requests.get(f"{API}/models", timeout=30).json()["data"]
    pricing = next(model["pricing"] for model in models if model["id"] == MODEL)
    return float(pricing["prompt"]), float(pricing["completion"])


def ask(prompt, key):
    response = requests.post(
        f"{API}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": MODEL, "messages": [{"role": "user", "content": prompt}],
              "response_format": {"type": "json_object"}, "usage": {"include": True},
              **({"reasoning": REASONING_OPTION[THINKING]} if THINKING != "default" else {})},
        timeout=180,
    )
    response.raise_for_status()
    return response.json()


def query(job, key):
    qid, prompt_id, prompt = job
    for attempt in range(2):
        try:
            response = ask(prompt, key)
            if parsed(response) is None:
                raise ValueError("reply cut off or not valid JSON")
            return {"qid": qid, "prompt_id": prompt_id, "setting": setting(), "prompt": prompt, "response": response}
        except (requests.RequestException, ValueError) as error:
            if attempt:
                return {"qid": qid, "prompt_id": prompt_id, "prompt": prompt, "error": str(error)}


def send(jobs, cache, key):
    """Send the jobs whose exact prompt is not cached yet, and cache the answers."""
    todo = [job for job in jobs if cache.get((*job[:2], setting()), {}).get("prompt") != job[2]]
    print(f"{len(todo)} queries to send to {setting()}, {len(jobs) - len(todo)} already cached")
    failures = []
    with ThreadPoolExecutor(WORKERS) as pool, CACHE.open("a", encoding="utf-8") as handle:
        for result in tqdm(pool.map(lambda job: query(job, key), todo), total=len(todo), desc="queries"):
            if "error" in result:
                failures.append(result)
                continue
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            cache[result["qid"], result["prompt_id"], setting()] = result
    if failures:
        raise SystemExit(f"{len(failures)} queries failed, nothing written; first error: {failures[0]['error']}")


def cost(response, price):
    usage = response.get("usage") or {}
    if usage.get("cost") is not None:
        return float(usage["cost"])
    return usage.get("prompt_tokens", 0) * price[0] + usage.get("completion_tokens", 0) * price[1]


def ai_answer(cached, source_text, source, price):
    answer = parsed(cached["response"])
    extracts = tuple(answer.get("source_verbatim") or ())
    written = answer.get("answer_as_written_in_text")
    body = normalise(source_text)
    return A.AIAnswer(
        answer=answer.get("answer"),
        answer_as_written_in_text=written,
        answer_as_written_in_text_english=answer.get("answer_as_written_in_text_english"),
        confidence=answer.get("confidence"),
        reasoning=answer.get("reasoning"),
        source=source,
        source_verbatim=extracts,
        source_verbatim_english=tuple(answer.get("source_verbatim_english") or ()),
        source_verbatim_not_invented=bool(extracts) and all(normalise(extract) in body for extract in extracts),
        answer_supported_by_source_verbatim=supported(written, extracts),
        model_name=setting(),
        prompt_id=cached["prompt_id"],
        prompt=cached["prompt"],
        cost_estimated=cost(cached["response"], price),
    )


def template_of(prompt_id):
    """The prompt file, without the reasoning field when the model is not asked to write one."""
    template = (PROMPTS / f"{prompt_id}.txt").read_text(encoding="utf-8")
    return template if WRITE_REASONING else re.sub(r'\n\s*"reasoning": [^\n]*', "", template)


def polity_prompt(location, window, candidate_lines):
    template = template_of(POLITY_PROMPT)
    place = f"{location.answer} (written in the biography as '{location.answer_as_written_in_text}')"
    return template.replace("{location}", place).replace("{window}", window.answer or "").replace("{candidates}", candidate_lines)


def entities(qids):
    connection = duckdb.connect(str(DB), read_only=True)
    rows = connection.execute("SELECT entity FROM individual WHERE entity.qid IN (SELECT unnest(?))", [qids]).fetchall()
    return {entity["qid"]: A.WikidataEntity(**entity) for (entity,) in rows}


def main():
    global MODEL, THINKING, WRITE_REASONING
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--thinking", choices=("default", "on", "off", "minimal"), default="default")
    parser.add_argument("--no-reasoning", action="store_true")
    parser.add_argument("--out", default=OUT.name)
    args = parser.parse_args()
    MODEL, THINKING, WRITE_REASONING = args.model, args.thinking, not args.no_reasoning
    out = FOLDER / args.out
    load_dotenv(ROOT / ".env")
    key = os.environ["OPEN_ROUTER_API"]

    texts = load_texts()
    population = sorted(entities(list(texts)))
    qids = random.Random(SEED).sample(population, args.n)
    print(f"{len(population)} individuals with a downloaded text in {DB.name}; annotating {len(qids)}: {', '.join(qids)}")
    cache = load_cache()
    price = model_price()

    template = {prompt_id: template_of(prompt_id) for prompt_id in TEXT_PROMPTS.values()}
    biography = {qid: texts[qid]["text"][:TEXT_CAP] for qid in qids}
    send([(qid, prompt_id, template[prompt_id].replace("{biography}", biography[qid])) for qid in qids for prompt_id in TEXT_PROMPTS.values()], cache, key)
    answers = {qid: {field: ai_answer(cache[qid, prompt_id, setting()], biography[qid], texts[qid]["dbi_url"], price) for field, prompt_id in TEXT_PROMPTS.items()} for qid in qids}

    territories = load_territories()
    candidate_lines = {}
    for qid in qids:
        years = window_years(answers[qid]["productivity_window_ai_extracted"].answer)
        candidate_lines[qid] = candidates(territories, years) if years else ""
    polity_jobs = [(qid, POLITY_PROMPT, polity_prompt(answers[qid]["location_ai_extracted"], answers[qid]["productivity_window_ai_extracted"], candidate_lines[qid]))
                   for qid in qids if candidate_lines[qid] and answers[qid]["location_ai_extracted"].answer]
    send(polity_jobs, cache, key)
    for qid in qids:
        if cache.get((qid, POLITY_PROMPT, setting())) and candidate_lines[qid]:
            answers[qid]["polity_ai_matched"] = ai_answer(cache[qid, POLITY_PROMPT, setting()], candidate_lines[qid], POLITY_SOURCE, price)
        else:
            answers[qid]["polity_ai_matched"] = A.AIAnswer(prompt_id=POLITY_PROMPT, reasoning="Not asked: no location or no datable window to build the candidate list from.")

    people = entities(qids)
    annotations = [A.TreccaniAnnotation(entity=people[qid], treccani_url=texts[qid]["dbi_url"], **answers[qid]) for qid in qids]
    pq.write_table(pa.Table.from_pylist([annotation.model_dump(mode="json") for annotation in annotations]), out)
    total = sum(answer.cost_estimated or 0 for qid in qids for answer in answers[qid].values())
    print(f"wrote {out.relative_to(ROOT)}: {len(annotations)} individuals, {setting()}, total cost ${total:.4f}")


if __name__ == "__main__":
    main()
