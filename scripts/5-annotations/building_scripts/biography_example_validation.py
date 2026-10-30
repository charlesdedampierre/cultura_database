"""Polity validation on the 13 biography examples of the paper table (notebooks_validation/01_benchmark_creation.ipynb).

Claude read each biography and wrote, for the early, active and late stage, the most granular
place the text gives, with word-for-word extracts and coordinates (biography_examples/claude_extraction.json).
Each place is mapped to the Cliopatria polities holding it over the years Cultura gives the stage,
keeping the smallest polity of the hierarchy, as in notebooks_polity/01_life_stage_polities_export.py.
A stage is validated when a benchmark polity matches a Cultura polity directly or through a parent
polity of the hierarchy; it is compared only when both sides have a polity.
Saved to biography_examples/biography_example_validation.json (BiographyDatabaseValidation) and
biography_examples/biography_examples_benchmark.tsv (one row per individual and stage).

With --benchmark 50 or --benchmark 300, the same comparison runs on the benchmark individuals of
benchmark50_texts.py or benchmark300_texts.py, extracted by agents (benchmark/benchmark{N}/extraction/agent_*.json;
individuals no longer in the benchmark are left out), and is saved to benchmark/benchmark{N}/benchmark{N}_validation.json
and benchmark{N}.tsv.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/biography_example_validation.py [--benchmark 50|300]
"""

import argparse
import json
import sys
from pathlib import Path

import duckdb
import polars as pl
from shapely import STRtree, make_valid, points
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
from datamodel_annotations import AIAnswer, BiographyData, BiographyDatabase, BiographyDatabaseValidation
from datamodel_in_duckdb import Polity, WikidataEntity

FOLDER = ROOT / "scripts" / "5-annotations" / "biography_examples"
EXTRACTION = FOLDER / "claude_extraction.json"
TEXTS = ROOT / "scripts" / "5-annotations" / "dictionary_exploration" / "dictionary_texts.json"
TRECCANI = ROOT / "scripts" / "5-annotations" / "legacy" / "treccani_validation" / "treccani_texts.parquet"
BENCHMARKS = ROOT / "scripts" / "5-annotations" / "benchmark"
STAGES_EXPORT = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities"
CLIOPATRIA = ROOT / "data" / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson"
ENRICHED_DB = ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"
STAGES = ["early", "active", "late"]
MODEL = "claude-opus-5-5 (in a Claude Code session)"


class Cliopatria:
    def __init__(self):
        features = json.loads(CLIOPATRIA.read_text())["features"]
        self.tree = STRtree(make_valid([shape(feature["geometry"]) for feature in features]))
        self.properties = [feature["properties"] for feature in features]
        self.parents = {}
        for properties in self.properties:
            for parent in filter(None, properties["MemberOf"].split(";")):
                self.parents.setdefault(properties["Name"], set()).add(parent)
            for child in filter(None, properties["Components"].split(";")):
                self.parents.setdefault(child, set()).add(properties["Name"])

    def ancestors(self, name):
        found, todo = set(), [name]
        while todo:
            for parent in self.parents.get(todo.pop(), ()):
                if parent not in found:
                    found.add(parent)
                    todo.append(parent)
        return found

    def smallest(self, indices, start, end):
        years = {}
        for index in indices:
            low, high = max(self.properties[index]["FromYear"], start), min(self.properties[index]["ToYear"], end)
            if low <= high:
                years.setdefault(self.properties[index]["Name"], set()).update(range(low, high + 1))
        above = {parent for name in years for parent in self.ancestors(name)}
        return {name: len(covered) for name, covered in years.items() if name not in above}

    def polities(self, spots, start, end):
        """Smallest polity holding each spot over the most years of [start, end], most years first."""
        ranked = {}
        by_spot = {}
        for spot, index in zip(*self.tree.query(points([(longitude, latitude) for _, longitude, latitude in spots]), predicate="within")):
            by_spot.setdefault(int(spot), []).append(int(index))
        for indices in by_spot.values():
            found = self.smallest(indices, start, end)
            if found:
                polity = max(found, key=found.get)
                ranked[polity] = max(found[polity], ranked.get(polity, 0))
        return sorted(ranked, key=ranked.get, reverse=True)

    def match(self, benchmark, cultura):
        """Benchmark and Cultura polities that are the same polity, or one a parent of the other."""
        pairs = []
        for found in benchmark:
            for given in cultura:
                if bare(found) == bare(given) or bare(given) in map(bare, self.ancestors(found)) or bare(found) in map(bare, self.ancestors(given)):
                    pairs.append(f"{bare(found)} = {bare(given)}" if bare(found) == bare(given) else f"{bare(found)} ~ {bare(given)}")
        return pairs


def bare(name):
    return name.strip("()")


def texts():
    downloaded = json.loads(TEXTS.read_text())
    found = {entry["qid"]: entry for entry in downloaded.values() if entry.get("text")}
    treccani = pl.read_parquet(TRECCANI).filter(pl.col("wikidata_id") == "Q569615").row(0, named=True)
    found["Q569615"] = {"dictionary": "treccani", "name": "Dizionario Biografico degli Italiani (Treccani)", "home": "https://www.treccani.it",
                        "id": treccani["dbi_url"].rstrip("/").rsplit("/", 1)[-1], "url": treccani["dbi_url"], "text": treccani["text"]}
    return found


def benchmark_texts(folder, size):
    return {person["qid"]: {"name": person["dictionary_name"], "id": str(person["dictionary_id"]), "url": person["biography_url"], "text": person["text"]}
            for person in json.loads((folder / f"benchmark{size}_texts.json").read_text())}


def answer(stage, url):
    if not stage:
        return AIAnswer()
    return AIAnswer(answer=stage["place"], answer_as_written_in_text=stage["written"],
                    answer_as_written_in_text_english=stage["written_en"], confidence=stage["confidence"], reasoning=stage["reasoning"],
                    source=url, source_verbatim=tuple(stage["verbatim"]),
                    source_verbatim_english=tuple(stage["verbatim_en"]), model_name=MODEL, prompt_id="biography_polity_extraction")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", choices=["50", "300"])
    size = parser.parse_args().benchmark
    if size:
        folder = BENCHMARKS / f"benchmark{size}"
        sources, validation_file, table_file = benchmark_texts(folder, size), f"benchmark{size}_validation.json", f"benchmark{size}.tsv"
        extraction = {qid: person for path in sorted((folder / "extraction").glob("agent_*.json")) for qid, person in json.loads(path.read_text()).items() if qid in sources}
    else:
        extraction = json.loads(EXTRACTION.read_text())
        sources, folder, validation_file, table_file = texts(), FOLDER, "biography_example_validation.json", "biography_examples_benchmark.tsv"
    cultura = pl.scan_parquet(STAGES_EXPORT / "batch_*.parquet").filter(pl.col("qid").is_in(list(extraction))).collect()
    cultura = {(row["qid"], row["stage"]): row for row in cultura.iter_rows(named=True)}
    labels = dict(duckdb.connect(str(ENRICHED_DB), read_only=True).execute(
        "SELECT entity.qid, entity.label_en FROM individual_enriched WHERE entity.qid IN (SELECT unnest(?))", [list(extraction)]).fetchall())
    cliopatria = Cliopatria()

    rows, validations = [], []
    for qid, person in extraction.items():
        source = sources[qid]
        for stage in STAGES:
            given = cultura.get((qid, stage))
            found = cliopatria.polities(person[stage]["points"], given["start_year"], given["end_year"]) if person[stage] and given else []
            cultura_polities = given["polities"] if given else []
            pairs = cliopatria.match(found, cultura_polities)
            extracted = person[stage] or {}
            rows.append({
                "qid": qid, "label": labels.get(qid), "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
                "dictionary_name": source.get("name"), "biography_url": source.get("url"), "stage": stage,
                "cultura_stage_start_year": given["start_year"] if given else None, "cultura_stage_end_year": given["end_year"] if given else None,
                "benchmark_place": extracted.get("place"),
                "benchmark_place_as_written": extracted.get("written"),
                "benchmark_place_as_written_english": extracted.get("written_en"),
                "benchmark_verbatim": " | ".join(extracted.get("verbatim", [])) or None,
                "benchmark_verbatim_english": " | ".join(extracted.get("verbatim_en", [])) or None,
                "benchmark_confidence": extracted.get("confidence"),
                "benchmark_reasoning": extracted.get("reasoning"),
                "benchmark_coordinates": " | ".join(f"{name} ({latitude}, {longitude})" for name, longitude, latitude in extracted.get("points", [])) or None,
                "benchmark_polity": "; ".join(map(bare, found)) or None,
                "cultura_polity": "; ".join(cultura_polities) or None,
                "cultura_wikidata_field": given["wikidata_field"] if given else None,
                "cultura_location": given["location"] if given else None,
                "compared": bool(found and cultura_polities),
                "validated": bool(pairs) if found and cultura_polities else None,
                "match": "; ".join(pairs) or None,
                "model_name": MODEL if extracted else None,
            })
            person[f"{stage}_polities"] = found
        data = BiographyData(**{f"{stage}_stage_place": answer(person[stage], source["url"]) for stage in STAGES},
                             **{f"{stage}_stage_polity": tuple(Polity(name=bare(name)) for name in person[f"{stage}_polities"]) for stage in STAGES})
        validations.append(BiographyDatabaseValidation(
            wikidata_entity=WikidataEntity(qid=qid, label_en=labels.get(qid)),
            biography_database=BiographyDatabase(name=person["dictionary"], description=source.get("name"), url=source.get("home")),
            biography_database_id=source.get("id"), biography_database_url=source.get("url"),
            biography_database_structured_data=data))

    (folder / validation_file).write_text(json.dumps([v.model_dump(exclude_defaults=True) for v in validations], ensure_ascii=False, indent=1))
    table = pl.DataFrame(rows)
    table.write_csv(folder / table_file, separator="\t")
    compared = table.filter(pl.col("compared"))
    print(f"{table['qid'].n_unique()} individuals, {len(compared)} stages compared of {len(table)}")
    print(compared.group_by("stage").agg(compared=pl.len(), validated=pl.col("validated").sum()).sort(pl.col("stage").cast(pl.Enum(STAGES)))
          .with_columns(accuracy=(100 * pl.col("validated") / pl.col("compared")).round(1)))
    print(f"all stages: {compared['validated'].sum()} / {len(compared)} ({100 * compared['validated'].mean():.1f}%)")


if __name__ == "__main__":
    main()
