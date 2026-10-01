"""Build annotations/interfaces/treccani_review.html from treccani_ai_annotations.parquet.

One card per individual with the two AI answers, their evidence and checks, and the
HumanAnnotation fields to fill in. Verdicts are kept in the browser and exported as JSON.

Usage: .venv/bin/python annotations/building_scripts/build_treccani_review.py
"""

import json
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "annotations" / "treccani_validation" / "treccani_ai_annotations.parquet"
OUT = ROOT / "annotations" / "interfaces" / "treccani_review.html"

PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Treccani AI Review</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect x='2' y='2' width='12' height='12' rx='2' fill='%23333'/></svg>">
<style>
body{font-family:-apple-system,system-ui,sans-serif;max-width:980px;margin:0 auto;padding:24px 16px;color:#222;background:#fff;line-height:1.45}
header{position:sticky;top:0;background:#fff;padding:10px 0;border-bottom:1px solid #ddd;display:flex;gap:16px;align-items:center;z-index:2}
h1{font-size:20px;margin:0;flex:1} button{font:inherit;padding:5px 12px;border:1px solid #bbb;background:#f6f6f6;border-radius:5px;cursor:pointer}
section.card{margin:26px 0;border-top:1px solid #ddd;padding-top:12px} h2{font-size:17px;margin:0 0 4px}
.links a{color:#2a5db0;text-decoration:none;margin-right:12px;font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px;margin-top:8px}
th{text-align:left;vertical-align:top;width:200px;padding:5px 10px 5px 0;color:#555;font-weight:500} td{padding:5px 0;vertical-align:top}
tr{border-bottom:1px solid #f0f0f0} h3{font-size:15px;margin:16px 0 0}
.quotes{display:grid;grid-template-columns:1fr 1fr;gap:6px 14px} .quotes div{background:#fafafa;padding:6px 8px;border-radius:4px;font-size:13px}
.ok{color:#2e7d32} .ko{color:#c62828} .m{color:#888;font-size:12.5px}
details summary{cursor:pointer;color:#555;font-size:13px} pre{white-space:pre-wrap;font-size:12px;background:#fafafa;padding:8px;max-height:300px;overflow:auto}
.verdict{background:#f7f9fc;border:1px solid #e3e8f0;border-radius:6px;padding:10px 12px;margin-top:12px;font-size:14px}
.verdict label{margin-right:14px} .verdict textarea{width:100%;box-sizing:border-box;margin-top:6px;font:inherit;min-height:44px}
@media (max-width:640px){.quotes{grid-template-columns:1fr} th{width:120px}}
</style></head><body>
<header><h1>Treccani — AI extraction review</h1><span id="progress"></span><button id="export">Export verdicts (JSON)</button></header>
<p class="m">Source: treccani_ai_annotations.parquet. For each answer, read the extracts (and the Treccani page if needed), then say whether the AI answer is correct.</p>
<div id="cards"></div>
<script>
const DATA = __DATA__;
const KEY = "treccani_review_verdicts";
const FIELDS = [
  ["location_ai_extracted", "Location", "location_ai_extracted_is_correct", "note_location"],
  ["productivity_window_ai_extracted", "Productivity window", "productivity_window_ai_extracted_is_correct", "note_productivity_window"],
];
let verdicts = {};
try { verdicts = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(verdicts)); } catch (e) {} progress(); };
const esc = s => String(s ?? "—").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const check = v => v === true ? '<span class="ok">✓ yes</span>' : v === false ? '<span class="ko">✗ no</span>' : "—";

function answerTable(a) {
  const quotes = (a.source_verbatim || []).map((q, i) =>
    `<div>${esc(q)}</div><div>${esc((a.source_verbatim_english || [])[i])}</div>`).join("");
  const rows = [
    ["Answer", `<b>${esc(a.answer)}</b>`],
    ["As written in text", `${esc(a.answer_as_written_in_text)} <span class="m">(${esc(a.answer_as_written_in_text_english)})</span>`],
    ["Confidence", esc(a.confidence)],
    ["Reasoning", esc(a.reasoning)],
    ["Source verbatim (IT · EN)", quotes ? `<div class="quotes">${quotes}</div>` : "—"],
    ["Quotes not invented", check(a.source_verbatim_not_invented)],
    ["Answer supported by quotes", check(a.answer_supported_by_source_verbatim)],
    ["Model · prompt · cost", `<span class="m">${esc(a.model_name)} · ${esc(a.prompt_id)} · $${(a.cost_estimated ?? 0).toFixed(5)}</span>`],
    ["Prompt", `<details><summary>show the full prompt</summary><pre>${esc(a.prompt)}</pre></details>`],
  ];
  return `<table>${rows.map(([k, v]) => `<tr><th>${k}</th><td>${v}</td></tr>`).join("")}</table>`;
}

function verdictBox(qid, label, field, note) {
  const v = verdicts[qid] || {};
  return `<div class="verdict" data-qid="${qid}"><b>${label} check:</b>
    <label><input type="radio" name="${qid}-${field}" data-field="${field}" value="true" ${v[field] === true ? "checked" : ""}> correct</label>
    <label><input type="radio" name="${qid}-${field}" data-field="${field}" value="false" ${v[field] === false ? "checked" : ""}> wrong</label>
    <textarea placeholder="note on the ${label.toLowerCase()}" data-field="${note}">${esc(v[note] ?? "")}</textarea></div>`;
}

document.getElementById("cards").innerHTML = DATA.map((row, i) => {
  const e = row.entity;
  return `<section class="card"><h2>${i + 1}. ${esc(e.label_en || e.label_non_en || e.qid)}</h2>
    <div class="links"><a href="https://www.wikidata.org/wiki/${e.qid}" target="_blank">Wikidata ${e.qid}</a>
    <a href="${esc(row.treccani_url)}" target="_blank">Treccani biography</a><span class="m">${esc(e.description)}</span></div>
    ${FIELDS.map(([f, label, field, note]) => `<h3>${label}</h3>${answerTable(row[f])}${verdictBox(e.qid, label, field, note)}`).join("")}
    </section>`;
}).join("");

document.querySelectorAll(".verdict").forEach(box => {
  const qid = box.dataset.qid;
  const update = ev => {
    const t = ev.target;
    verdicts[qid] = verdicts[qid] || {};
    verdicts[qid][t.dataset.field] = t.type === "radio" ? t.value === "true" : t.value;
    save();
  };
  box.addEventListener("change", update);
  box.querySelector("textarea").addEventListener("input", update);
});

function progress() {
  const done = DATA.filter(r => { const v = verdicts[r.entity.qid] || {};
    return v.location_ai_extracted_is_correct !== undefined && v.productivity_window_ai_extracted_is_correct !== undefined; }).length;
  document.getElementById("progress").textContent = `${done} / ${DATA.length} reviewed`;
}
progress();

document.getElementById("export").onclick = () => {
  const rows = DATA.map(r => ({ qid: r.entity.qid,
    location_ai_extracted_is_correct: verdicts[r.entity.qid]?.location_ai_extracted_is_correct ?? null,
    productivity_window_ai_extracted_is_correct: verdicts[r.entity.qid]?.productivity_window_ai_extracted_is_correct ?? null,
    note_location: verdicts[r.entity.qid]?.note_location || null,
    note_productivity_window: verdicts[r.entity.qid]?.note_productivity_window || null }));
  const url = URL.createObjectURL(new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: "treccani_human_annotation.json" });
  link.click();
  URL.revokeObjectURL(url);
};
</script></body></html>"""


def main():
    rows = pq.read_table(SOURCE).to_pylist()
    OUT.write_text(PAGE.replace("__DATA__", json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rows)} individuals)")


if __name__ == "__main__":
    main()
