"""Build interfaces/meta_occupation_review.html: a stratified sample of the meta_occupation answers to mark correct or wrong.

The sample takes 10 occupations per meta occupation in each frequency tier (top 500, 500-5 000, the rest), seeded.
Verdicts are kept in the browser and exported as JSON.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/build_meta_occupation_review.py
"""

import json
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BATCHES = ROOT / "_one_off" / "meta_occupation"
OUT = Path(__file__).resolve().parents[1] / "interfaces" / "meta_occupation_review.html"
CATEGORIES = ["Culture", "Discovery/Science", "Leadership", "Sports/Games", "Other"]
TIERS = [("top 500", 0, 500), ("500 to 5,000", 500, 5000), ("tail", 5000, None)]
PER_CELL = 10
SEED = 42

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Meta Occupation Review</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect x='2' y='2' width='12' height='12' rx='2' fill='%23333'/></svg>">
<style>
:root{--fg:#222;--muted:#777;--line:#e6e6e6;--bg:#fff;--soft:#f7f7f7;--ok:#2e7d32;--ko:#c62828}
body{font-family:-apple-system,system-ui,sans-serif;max-width:900px;margin:0 auto;padding:24px 16px;color:var(--fg);background:var(--bg);line-height:1.45}
header{position:sticky;top:0;background:var(--bg);padding:10px 0;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:20px;margin:0;flex:1} h2{font-size:16px;margin:28px 0 6px}
button,select{font:inherit;font-size:13px;padding:4px 10px;border:1px solid #bbb;background:var(--soft);border-radius:5px;cursor:pointer}
table{width:100%;border-collapse:collapse;font-size:14px} td,th{padding:6px 8px 6px 0;border-bottom:1px solid var(--line);text-align:left;vertical-align:middle}
th{color:var(--muted);font-weight:500} .n{color:var(--muted);text-align:right;font-variant-numeric:tabular-nums}
.on-ok{background:#e8f5e9;border-color:var(--ok);color:var(--ok)} .on-ko{background:#ffebee;border-color:var(--ko);color:var(--ko)}
.m{color:var(--muted);font-size:13px} .wrap{overflow-x:auto}
</style></head><body>
<header><h1>Meta occupation review</h1><span id="progress" class="m"></span><button id="export">Export verdicts (JSON)</button></header>
<p class="m">__TOTAL__ occupations classified. Distribution below, then a stratified sample: mark each answer ✓ or ✗; when wrong, pick the right meta occupation.</p>
<h2>Distribution</h2><div class="wrap">__SUMMARY__</div>
<div id="tiers"></div>
<script>
const DATA = __DATA__;
const CATEGORIES = __CATEGORIES__;
const KEY = "meta_occupation_review";
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(verdicts)); } catch (e) {} progress(); };
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function progress() {
  const done = Object.values(verdicts).filter(v => v.correct !== undefined);
  const wrong = done.filter(v => v.correct === false).length;
  document.getElementById("progress").textContent = `${done.length}/${DATA.length} reviewed · ${wrong} wrong`;
}

function row(o) {
  const v = verdicts[o.qid] || {};
  const options = ['<option value="">right answer…</option>'].concat(CATEGORIES.filter(c => c !== o.meta_occupation)
    .map(c => `<option ${v.should_be === c ? "selected" : ""}>${c}</option>`)).join("");
  return `<tr data-qid="${o.qid}"><td><a href="https://www.wikidata.org/wiki/${o.qid}" target="_blank">${esc(o.label)}</a></td>
    <td class="n">${o.individuals.toLocaleString()}</td><td>${esc(o.meta_occupation)}</td>
    <td><button class="${v.correct === true ? "on-ok" : ""}" data-v="1">✓</button> <button class="${v.correct === false ? "on-ko" : ""}" data-v="0">✗</button>
    <select ${v.correct === false ? "" : "hidden"}>${options}</select></td></tr>`;
}

function render() {
  const tiers = [...new Set(DATA.map(o => o.tier))];
  document.getElementById("tiers").innerHTML = tiers.map(t => `<h2>Sample — ${t}</h2><div class="wrap"><table>
    <tr><th>Occupation</th><th class="n">Individuals</th><th>AI answer</th><th>Verdict</th></tr>
    ${DATA.filter(o => o.tier === t).map(row).join("")}</table></div>`).join("");
  progress();
}

document.addEventListener("click", e => {
  const b = e.target.closest("button[data-v]"); if (!b) return;
  const qid = b.closest("tr").dataset.qid;
  verdicts[qid] = {...(verdicts[qid] || {}), correct: b.dataset.v === "1"};
  if (verdicts[qid].correct) delete verdicts[qid].should_be;
  save(); render();
});
document.addEventListener("change", e => {
  if (e.target.tagName !== "SELECT") return;
  const qid = e.target.closest("tr").dataset.qid;
  verdicts[qid] = {...(verdicts[qid] || {}), should_be: e.target.value || undefined};
  save();
});
document.getElementById("export").onclick = () => {
  const out = DATA.map(o => ({qid: o.qid, label: o.label, tier: o.tier, meta_occupation: o.meta_occupation, ...(verdicts[o.qid] || {})}));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], {type: "application/json"}));
  a.download = "meta_occupation_verdicts.json"; a.click();
};
render();
</script></body></html>
"""


def load_answers():
    rows = []
    for path in sorted(BATCHES.glob("input_*.json")):
        output = BATCHES / path.name.replace("input_", "output_")
        held = {row["qid"]: row["individuals"] for row in json.loads(path.read_text())}
        rows += [{**answer, "individuals": held[answer["qid"]]} for answer in json.loads(output.read_text())]
    return rows


def summary_table(rows):
    occupations = Counter(row["meta_occupation"] for row in rows)
    links = Counter()
    for row in rows:
        links[row["meta_occupation"]] += row["individuals"]
    total_links = sum(links.values())
    lines = ["<table><tr><th>Meta occupation</th><th class='n'>Occupations</th><th class='n'>Links to individuals</th><th class='n'>Share of links</th></tr>"]
    for category in CATEGORIES:
        lines.append(f"<tr><td>{category}</td><td class='n'>{occupations[category]:,}</td><td class='n'>{links[category]:,}</td><td class='n'>{links[category] / total_links:.1%}</td></tr>")
    return "".join(lines) + "</table>"


def sample(rows):
    random.seed(SEED)
    chosen = []
    for tier, start, end in TIERS:
        for category in CATEGORIES:
            cell = [row for row in rows[start:end] if row["meta_occupation"] == category]
            chosen += [{**row, "tier": tier} for row in random.sample(cell, min(PER_CELL, len(cell)))]
    return chosen


def main():
    rows = load_answers()
    chosen = sample(rows)
    page = (PAGE.replace("__DATA__", json.dumps(chosen, ensure_ascii=False))
            .replace("__CATEGORIES__", json.dumps(CATEGORIES))
            .replace("__SUMMARY__", summary_table(rows))
            .replace("__TOTAL__", f"{len(rows):,}"))
    OUT.write_text(page)
    print(f"{len(chosen)} occupations to review in {OUT}")


if __name__ == "__main__":
    main()
