"""HTML review of the benchmark results: one card per individual, features as rows and values in the second column.

Reads the benchmark dataset (notebooks_validation/03_cliopatria_association.ipynb), the Cultura life-stage polities and
the benchmark individuals, compares the polities of each stage as in 04_benchmark_results.ipynb (a Cultura polity among the benchmark polities
or Cliopatria candidates, directly or through a parent polity), and writes scripts/5-annotations/interfaces/benchmark_results_review.html.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/build_benchmark_results_review.py
"""

import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[3]
FOLDER = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark300"
STAGES_EXPORT = ROOT / "data" / "enriched_parquets" / "individual_life_stage_polities"
CLIOPATRIA = ROOT / "data" / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson"
OUT = ROOT / "scripts" / "5-annotations" / "interfaces" / "benchmark_results_review.html"
STAGES = ["pre_active", "active", "post_active"]


def hierarchy():
    parents = {}
    for feature in json.loads(CLIOPATRIA.read_text())["features"]:
        polity = feature["properties"]
        for parent in filter(None, polity["MemberOf"].split(";")):
            parents.setdefault(polity["Name"].strip("()"), set()).add(parent.strip("()"))
        for child in filter(None, polity["Components"].split(";")):
            parents.setdefault(child.strip("()"), set()).add(polity["Name"].strip("()"))
    return parents


def ancestors(name, parents):
    found, todo = set(), [name]
    while todo:
        for parent in parents.get(todo.pop(), ()):
            if parent not in found:
                found.add(parent)
                todo.append(parent)
    return found


def result(found, candidates, given, parents):
    """Validated when a Cultura polity is a benchmark polity or candidate, directly or through a parent polity."""
    if not candidates or not given:
        return "not compared"
    match = any(a == b or b in ancestors(a, parents) or a in ancestors(b, parents) for a in found + candidates for b in given)
    return "validated" if match else "mismatch"


def main():
    parents = hierarchy()
    people = {person["qid"]: person for person in json.loads((FOLDER / "benchmark300_texts.json").read_text(encoding="utf-8"))}
    benchmark = pl.read_parquet(FOLDER / "benchmark_life_stage_polities.parquet")
    cultura = (pl.scan_parquet(STAGES_EXPORT / "batch_*.parquet").filter(pl.col("qid").is_in(benchmark["qid"].unique().implode())).collect())
    cultura = {(row["qid"], row["stage"]): row for row in cultura.iter_rows(named=True)}
    individuals = {}
    for row in benchmark.sort("qid", pl.col("stage").cast(pl.Enum(STAGES))).iter_rows(named=True):
        person = people[row["qid"]]
        given = cultura.get((row["qid"], row["stage"]), {})
        entry = individuals.setdefault(row["qid"], {
            "qid": row["qid"], "label": row["label"], "region": person["claude_estimated_region"], "notability": person["notability"],
            "birth": person["cultura_birth_date_year"], "death": person["cultura_death_date_year"],
            "dictionary": row["dictionary_name"], "url": row["biography_url"], "stages": []})
        entry["stages"].append({
            "stage": row["stage"], "result": result(row["polities"], row["candidate_polities"], given.get("polities") or [], parents),
            "benchmark_years": [row["biography_start_year"], row["biography_end_year"]],
            "cultura_years": [given.get("start_year"), given.get("end_year")],
            "place": row["place"], "written": row["place_as_written"], "verbatim": row["verbatim_english"],
            "candidates": row["candidate_polities"], "claude": row["claude_polities"], "polities": row["polities"],
            "confidence": row["association_confidence"], "reasoning": row["association_reasoning"],
            "cultura_polities": given.get("polities") or [], "cultura_field": given.get("wikidata_field"), "cultura_location": given.get("location"),
        })
    data = json.dumps(list(individuals.values()), ensure_ascii=False)
    OUT.write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    print(f"{len(individuals)} individuals written to {OUT.relative_to(ROOT)}")


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Benchmark results review</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><circle cx='8' cy='8' r='7' fill='%233b6ea8'/><path d='M4.5 8.2l2.3 2.3 4.7-4.9' stroke='white' stroke-width='1.8' fill='none'/></svg>">
<style>
  body { font-family: -apple-system, "Helvetica Neue", sans-serif; margin: 0; background: #f6f7f9; color: #222; font-size: 13px; }
  header { position: sticky; top: 0; background: white; border-bottom: 1px solid #e3e6ea; padding: 12px 24px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; z-index: 2; }
  header h1 { font-size: 16px; margin: 0 16px 0 0; font-weight: 600; }
  select, input { font-size: 13px; padding: 4px 8px; border: 1px solid #cfd4da; border-radius: 4px; }
  #summary { color: #666; margin-left: auto; }
  main { max-width: 1100px; margin: 0 auto; padding: 16px 24px; }
  .card { background: white; border: 1px solid #e3e6ea; border-radius: 6px; margin-bottom: 18px; }
  .card h2 { font-size: 14px; margin: 0; padding: 10px 14px; border-bottom: 1px solid #e3e6ea; display: flex; gap: 10px; align-items: baseline; }
  .card h2 a { color: #3b6ea8; text-decoration: none; font-weight: normal; font-size: 12px; }
  table { border-collapse: collapse; width: 100%; }
  td { border-top: 1px solid #eef0f2; padding: 5px 14px; vertical-align: top; }
  td.key { width: 210px; color: #666; background: #fafbfc; }
  tr.bio td { background: #f1f6fc; } tr.bio td.key { border-left: 4px solid #5b8fc9; color: #3d5f86; }
  tr.cultura td { background: #fcf6ec; } tr.cultura td.key { border-left: 4px solid #d29b4a; color: #86602a; }
  .legend { display: flex; gap: 10px; font-size: 12px; } .legend span { padding: 2px 8px; border-radius: 3px; }
  .legend .bio { background: #f1f6fc; border-left: 4px solid #5b8fc9; } .legend .cultura { background: #fcf6ec; border-left: 4px solid #d29b4a; }
  tr.stage td { background: #eef2f7; font-weight: 600; color: #333; }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; margin-left: 8px; }
  .validated { background: #e3f1e6; color: #2f6b3a; }
  .mismatch { background: #f8e3e1; color: #9b3128; }
  .not.compared, .not-compared { background: #eceef0; color: #666; }
  .muted { color: #999; }
  ul { margin: 0; padding-left: 16px; }
</style>
</head>
<body>
<header>
  <h1>Benchmark results review</h1>
  <select id="result"><option value="">All stage results</option><option value="mismatch">Has a mismatch</option><option value="validated">Has a validated stage</option><option value="not compared">Has a stage not compared</option></select>
  <select id="stage"><option value="">All stages</option><option value="pre_active">Pre-active</option><option value="active">Active</option><option value="post_active">Post-active</option></select>
  <select id="region"><option value="">All regions</option></select>
  <input id="search" placeholder="Search name, QID, polity" size="26">
  <span class="legend"><span class="bio">Biography (benchmark)</span><span class="cultura">Cultura</span></span>
  <span id="summary"></span>
</header>
<main id="cards"></main>
<script>
const DATA = __DATA__;
const NAMES = {pre_active: "Pre-active life", active: "Active life", post_active: "Post-active life"};
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const years = y => (y[0] == null && y[1] == null) ? '<span class="muted">none</span>' : `${y[0] ?? "?"} – ${y[1] ?? "?"}`;
const list = l => l && l.length ? esc(l.join("; ")) : '<span class="muted">none</span>';
const text = t => t ? esc(t) : '<span class="muted">none</span>';
const row = (key, value, source = "") => `<tr class="${source}"><td class="key">${key}</td><td>${value}</td></tr>`;
const regions = [...new Set(DATA.map(d => d.region))].sort();
document.getElementById("region").innerHTML += regions.map(r => `<option>${esc(r)}</option>`).join("");

function card(d, stageFilter) {
  let rows = row("QID", `<a href="https://www.wikidata.org/wiki/${d.qid}" target="_blank">${d.qid}</a>`)
    + row("Region", esc(d.region)) + row("Notability", esc(d.notability))
    + row("Cultura birth – death", years([d.birth, d.death]), "cultura")
    + row("Biography", `<a href="${esc(d.url)}" target="_blank">${esc(d.dictionary)}</a>`, "bio");
  for (const s of d.stages) {
    if (stageFilter && s.stage !== stageFilter) continue;
    rows += `<tr class="stage"><td colspan="2">${NAMES[s.stage]}<span class="badge ${s.result.replace(" ", "-")}">${s.result}</span></td></tr>`
      + row("Cultura polities", list(s.cultura_polities), "cultura")
      + row("Cultura years", years(s.cultura_years), "cultura")
      + row("Cultura source field", text(s.cultura_field), "cultura")
      + row("Cultura location", text(s.cultura_location), "cultura")
      + row("Benchmark polities", list(s.polities), "bio")
      + row("Biography years", years(s.benchmark_years), "bio")
      + row("Biography place", text(s.place), "bio")
      + row("As written", text(s.written), "bio")
      + row("Extracts (English)", s.verbatim && s.verbatim.length ? "<ul>" + s.verbatim.map(v => `<li>${esc(v)}</li>`).join("") + "</ul>" : '<span class="muted">none</span>', "bio")
      + row("Cliopatria candidates", list(s.candidates), "bio")
      + (JSON.stringify(s.claude) !== JSON.stringify(s.polities) ? row("Claude choice (before smallest)", list(s.claude), "bio") : "")
      + row("Association", s.confidence ? `${esc(s.confidence)} — ${esc(s.reasoning)}` : '<span class="muted">none</span>', "bio");
  }
  return `<div class="card"><h2>${esc(d.label)}</h2><table>${rows}</table></div>`;
}

function render() {
  const result = document.getElementById("result").value, stage = document.getElementById("stage").value;
  const region = document.getElementById("region").value, query = document.getElementById("search").value.toLowerCase();
  const shown = DATA.filter(d => (!region || d.region === region)
    && (!result || d.stages.some(s => s.result === result && (!stage || s.stage === stage)))
    && (!query || JSON.stringify(d).toLowerCase().includes(query)));
  const stages = shown.flatMap(d => d.stages.filter(s => !stage || s.stage === stage));
  const compared = stages.filter(s => s.result !== "not compared"), ok = compared.filter(s => s.result === "validated").length;
  document.getElementById("summary").textContent = `${shown.length} individuals · ${ok} / ${compared.length} stages validated (${compared.length ? (100 * ok / compared.length).toFixed(1) : 0}%)`;
  document.getElementById("cards").innerHTML = shown.map(d => card(d, stage)).join("");
}
const params = new URLSearchParams(location.search);
["result", "stage", "region", "search"].forEach(id => {
  if (params.has(id)) document.getElementById(id).value = params.get(id);
  document.getElementById(id).addEventListener("input", render);
});
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
