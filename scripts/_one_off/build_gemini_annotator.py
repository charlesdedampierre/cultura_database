"""
Build a single-file HTML annotator to spot-check Gemini's date+polity
extractions over the Wikipedia 10K sample.

It samples N records that have a Gemini extraction, joins them with the
original Wikipedia lead extract, embeds the bundle as JSON inside one HTML
file, and writes the result to disk. Open the file in any browser - no
server needed.

Annotations are kept in localStorage as you click through, and can be
downloaded as JSON at the end.
"""

from __future__ import annotations

import argparse
import html
import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "wiki_no_floruit_no_polity_sample"
PAGES_PATH = DATA_DIR / "pages.jsonl"
EXTRACTIONS_PATH = DATA_DIR / "gemini_extractions_v2b_3k.jsonl"
OUT_PATH = DATA_DIR / "gemini_annotator_v2b.html"

DEFAULT_N = 200
DEFAULT_SEED = 42


def load_pages_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    with PAGES_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("ok") and r.get("extract"):
                idx[r["wikidata_id"]] = r
    return idx


def load_extractions() -> list[dict]:
    rows: list[dict] = []
    with EXTRACTIONS_PATH.open() as f:
        for line in f:
            r = json.loads(line)
            if isinstance(r.get("extraction"), dict):
                rows.append(r)
    return rows


def build_records(n: int, seed: int) -> list[dict]:
    pages_idx = load_pages_index()
    extractions = load_extractions()
    rng = random.Random(seed)
    rng.shuffle(extractions)
    out: list[dict] = []
    for r in extractions:
        page = pages_idx.get(r["wikidata_id"])
        if not page:
            continue
        out.append(
            {
                "wikidata_id": r["wikidata_id"],
                "site": r["site"],
                "title": r.get("title") or page.get("resolved_title"),
                "url": r.get("url") or page.get("fullurl"),
                "description": page.get("description"),
                "extract": page.get("extract"),
                "extraction": r["extraction"],
            }
        )
        if len(out) >= n:
            break
    return out


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Gemini extraction · annotator</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='3' fill='%23111'/%3E%3Ctext x='8' y='12' text-anchor='middle' font-family='ui-monospace,monospace' font-size='10' fill='white'%3EQA%3C/text%3E%3C/svg%3E">
<style>
  :root {
    --bg: #fafaf8;
    --fg: #111;
    --mute: #666;
    --line: #e6e3dd;
    --good: #2f7a3a;
    --bad: #b03030;
    --warn: #b07a30;
    --accent: #1a4f8a;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", system-ui, sans-serif;
    font-size: 14px; line-height: 1.5; }
  header { padding: 14px 24px; border-bottom: 1px solid var(--line);
    display: flex; align-items: center; gap: 16px; position: sticky; top: 0;
    background: var(--bg); z-index: 10; }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .stats { color: var(--mute); font-variant-numeric: tabular-nums; }
  header .actions { margin-left: auto; display: flex; gap: 8px; }
  button { font: inherit; padding: 6px 12px; border: 1px solid var(--line);
    background: white; cursor: pointer; border-radius: 4px; }
  button:hover { background: #f0eee8; }
  button.primary { background: var(--fg); color: white; border-color: var(--fg); }
  button.primary:hover { opacity: 0.85; }
  main { max-width: 1300px; margin: 0 auto; padding: 24px; }
  .card { background: white; border: 1px solid var(--line); border-radius: 6px;
    padding: 20px 24px; margin-bottom: 24px; }
  .meta { color: var(--mute); font-size: 12px; margin-bottom: 6px;
    font-variant-numeric: tabular-nums; }
  .title { font-size: 18px; font-weight: 600; margin: 0 0 4px 0; }
  .title a { color: var(--accent); text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .desc { color: var(--mute); font-style: italic; margin-bottom: 12px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 12px; }
  .col h3 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--mute); margin: 0 0 8px 0; font-weight: 600; }
  .extract { font-size: 13px; line-height: 1.6; max-height: 360px; overflow: auto;
    padding-right: 8px; white-space: pre-wrap; }
  table.kv { width: 100%; border-collapse: collapse; }
  table.kv td { padding: 6px 8px; border-bottom: 1px solid var(--line);
    vertical-align: top; }
  table.kv td.k { color: var(--mute); width: 38%; font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.03em; }
  table.kv td.v { font-variant-numeric: tabular-nums; }
  .reasoning { font-size: 13px; color: #333; margin-top: 8px;
    background: #f7f5f0; padding: 10px 12px; border-radius: 4px; }
  .verdict-row { display: flex; gap: 8px; align-items: center; margin-top: 16px;
    padding-top: 16px; border-top: 1px solid var(--line); flex-wrap: wrap; }
  .verdict-row label { color: var(--mute); font-size: 12px; margin-right: 4px; }
  .vbtn { padding: 6px 14px; }
  .vbtn[data-state="good"]    { background: #d8eedb; border-color: var(--good); color: var(--good); }
  .vbtn[data-state="partial"] { background: #f5e8cb; border-color: var(--warn); color: var(--warn); }
  .vbtn[data-state="bad"]     { background: #f3d4d4; border-color: var(--bad);  color: var(--bad);  }
  .vbtn[data-state="skip"]    { background: #ececec; border-color: var(--mute); color: var(--mute); }
  textarea { width: 100%; min-height: 56px; font: inherit; padding: 8px 10px;
    border: 1px solid var(--line); border-radius: 4px; background: white; resize: vertical;
    margin-top: 12px; }
  .nav { display: flex; gap: 8px; align-items: center; justify-content: space-between;
    margin-top: 8px; }
  .nav .progress { color: var(--mute); font-variant-numeric: tabular-nums; }
  kbd { font-family: ui-monospace, monospace; background: #ececec; padding: 1px 6px;
    border-radius: 3px; border: 1px solid var(--line); font-size: 11px; }
  .hint { color: var(--mute); font-size: 12px; margin-top: 8px; }
  .pol-list { display: flex; flex-wrap: wrap; gap: 4px; }
  .pol-tag { background: #eef2f7; color: var(--accent); padding: 2px 8px;
    border-radius: 999px; font-size: 12px; }
</style>
</head>
<body>
<header>
  <h1>Gemini extraction · annotator</h1>
  <span class="stats" id="stats">0 / 0</span>
  <div class="actions">
    <button id="btn-prev">← Prev</button>
    <button id="btn-next" class="primary">Next →</button>
    <button id="btn-export">Download annotations</button>
    <button id="btn-clear">Clear all</button>
  </div>
</header>

<main>
  <div class="card" id="card">
    <div class="meta" id="meta"></div>
    <h2 class="title"><a id="link" target="_blank" rel="noopener"></a></h2>
    <div class="desc" id="desc"></div>
    <div class="grid">
      <div class="col">
        <h3>Wikipedia lead extract</h3>
        <div class="extract" id="extract"></div>
      </div>
      <div class="col">
        <h3>Gemini extraction (translated to English)</h3>
        <table class="kv">
          <tr><td class="k">birth_year</td>            <td class="v" id="f-by"></td></tr>
          <tr><td class="k">death_year</td>            <td class="v" id="f-dy"></td></tr>
          <tr><td class="k">floruit_period_start</td>  <td class="v" id="f-fps"></td></tr>
          <tr><td class="k">floruit_period_end</td>    <td class="v" id="f-fpe"></td></tr>
          <tr><td class="k">floruit_precision</td>     <td class="v" id="f-fprec"></td></tr>
          <tr><td class="k">polities</td>              <td class="v" id="f-pol"></td></tr>
          <tr><td class="k">confidence</td>            <td class="v" id="f-conf"></td></tr>
        </table>
        <div class="reasoning" id="f-reason"></div>
      </div>
    </div>
    <div class="verdict-row">
      <label>Dates verdict:</label>
      <button class="vbtn" data-axis="dates" data-val="good">Correct</button>
      <button class="vbtn" data-axis="dates" data-val="partial">Partial</button>
      <button class="vbtn" data-axis="dates" data-val="bad">Wrong</button>
      <button class="vbtn" data-axis="dates" data-val="skip">N/A</button>
    </div>
    <div class="verdict-row">
      <label>Polities verdict:</label>
      <button class="vbtn" data-axis="polities" data-val="good">Correct</button>
      <button class="vbtn" data-axis="polities" data-val="partial">Partial</button>
      <button class="vbtn" data-axis="polities" data-val="bad">Wrong</button>
      <button class="vbtn" data-axis="polities" data-val="skip">N/A</button>
    </div>
    <textarea id="notes" placeholder="Notes (optional)"></textarea>
    <div class="nav">
      <span class="progress" id="prog"></span>
      <div class="hint">Shortcuts: <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd> dates good/partial/bad &nbsp; <kbd>q</kbd>/<kbd>w</kbd>/<kbd>e</kbd> polities &nbsp; <kbd>←</kbd>/<kbd>→</kbd> nav</div>
    </div>
  </div>
</main>

<script id="DATA" type="application/json">__DATA_JSON__</script>
<script>
  const DATA = JSON.parse(document.getElementById("DATA").textContent);
  const STORE_KEY = "gemini_annotator_v2b";

  const state = {
    i: 0,
    annotations: JSON.parse(localStorage.getItem(STORE_KEY) || "{}"),
  };

  function save() { localStorage.setItem(STORE_KEY, JSON.stringify(state.annotations)); }

  function fmtPolities(arr) {
    if (!Array.isArray(arr) || arr.length === 0) return "<span style='color:#999'>—</span>";
    return '<span class="pol-list">' + arr.map(p =>
      '<span class="pol-tag">' + escapeHTML(String(p)) + '</span>').join('') + '</span>';
  }
  function escapeHTML(s) {
    return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }
  function fmt(v) {
    if (v === null || v === undefined) return "<span style='color:#999'>null</span>";
    return escapeHTML(String(v));
  }

  function render() {
    const r = DATA[state.i];
    document.getElementById("stats").textContent = (state.i + 1) + " / " + DATA.length;
    document.getElementById("prog").textContent =
      "annotated: " + Object.keys(state.annotations).length + " / " + DATA.length;
    document.getElementById("meta").textContent =
      r.wikidata_id + " · " + r.site;
    const link = document.getElementById("link");
    link.textContent = r.title || r.wikidata_id;
    link.href = r.url || ("https://www.wikidata.org/wiki/" + r.wikidata_id);
    document.getElementById("desc").textContent = r.description || "";
    document.getElementById("extract").textContent = r.extract || "";

    const e = r.extraction || {};
    document.getElementById("f-by").innerHTML   = fmt(e.birth_year);
    document.getElementById("f-dy").innerHTML   = fmt(e.death_year);
    document.getElementById("f-fps").innerHTML  = fmt(e.floruit_period_start);
    document.getElementById("f-fpe").innerHTML  = fmt(e.floruit_period_end);
    document.getElementById("f-fprec").innerHTML = fmt(e.floruit_precision);
    document.getElementById("f-pol").innerHTML  = fmtPolities(e.polities);
    document.getElementById("f-conf").innerHTML = fmt(e.confidence);
    document.getElementById("f-reason").textContent = e.reasoning || "";

    // restore selection
    const a = state.annotations[r.wikidata_id] || {};
    document.querySelectorAll(".vbtn").forEach(btn => {
      const axis = btn.dataset.axis, val = btn.dataset.val;
      btn.dataset.state = a[axis] === val ? val : "";
    });
    document.getElementById("notes").value = a.notes || "";
  }

  function setVerdict(axis, val) {
    const r = DATA[state.i];
    const a = state.annotations[r.wikidata_id] || {};
    a[axis] = val;
    a.ts = Date.now();
    state.annotations[r.wikidata_id] = a;
    save();
    render();
  }

  document.querySelectorAll(".vbtn").forEach(btn => {
    btn.addEventListener("click", () => setVerdict(btn.dataset.axis, btn.dataset.val));
  });

  document.getElementById("notes").addEventListener("input", e => {
    const r = DATA[state.i];
    const a = state.annotations[r.wikidata_id] || {};
    a.notes = e.target.value;
    state.annotations[r.wikidata_id] = a;
    save();
    document.getElementById("prog").textContent =
      "annotated: " + Object.keys(state.annotations).length + " / " + DATA.length;
  });

  document.getElementById("btn-next").addEventListener("click", () => {
    state.i = Math.min(state.i + 1, DATA.length - 1); render();
  });
  document.getElementById("btn-prev").addEventListener("click", () => {
    state.i = Math.max(state.i - 1, 0); render();
  });

  document.addEventListener("keydown", e => {
    if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
    if (e.key === "ArrowRight") document.getElementById("btn-next").click();
    if (e.key === "ArrowLeft")  document.getElementById("btn-prev").click();
    if (e.key === "1") setVerdict("dates", "good");
    if (e.key === "2") setVerdict("dates", "partial");
    if (e.key === "3") setVerdict("dates", "bad");
    if (e.key === "q") setVerdict("polities", "good");
    if (e.key === "w") setVerdict("polities", "partial");
    if (e.key === "e") setVerdict("polities", "bad");
  });

  document.getElementById("btn-export").addEventListener("click", () => {
    const out = DATA.map(r => ({
      wikidata_id: r.wikidata_id,
      site: r.site,
      title: r.title,
      url: r.url,
      extraction: r.extraction,
      annotation: state.annotations[r.wikidata_id] || null,
    }));
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "gemini_annotations.json";
    a.click();
  });

  document.getElementById("btn-clear").addEventListener("click", () => {
    if (!confirm("Clear all local annotations?")) return;
    state.annotations = {};
    save(); render();
  });

  render();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=DEFAULT_N,
                        help=f"sample size (default {DEFAULT_N})")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    print(f"[info] sampling {args.n} records (seed={args.seed})")
    records = build_records(args.n, args.seed)
    print(f"[info] embedded {len(records)} records")

    payload = json.dumps(records, ensure_ascii=False)
    # safe injection inside <script type="application/json">
    payload = payload.replace("</", "<\\/")

    html_doc = HTML_TEMPLATE.replace("__DATA_JSON__", payload)
    args.out.write_text(html_doc, encoding="utf-8")
    print(f"[info] wrote {args.out}")
    print(f"[info] open with: open '{args.out}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
