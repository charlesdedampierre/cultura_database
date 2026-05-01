"""
Generate a self-contained HTML page showing 50 random cities with the urban
classifier's prediction, for manual annotation by Dr de Dampierre.

Sampling: stratified — 25 cities where is_urban_settlement=1 and 25 where
is_urban_settlement=0, so both sides of the classifier get probed.

Output: annotations/urban_classifier_review.html
The page lets you mark each row as "correct" / "wrong" / skip, and export the
annotations as JSON (downloaded by the browser).
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = "data/humans_clean.sqlite3"
OUT_PATH = "annotations/urban_classifier_review.html"
N_PER_CLASS = 25  # 25 urban + 25 non-urban = 50


SQL = """
SELECT id, name_en, entity_type, entity_type_ids, iso_a3_code, original_country_name
FROM cities
WHERE is_urban_settlement = ?
  AND entity_type IS NOT NULL
  AND name_en IS NOT NULL
ORDER BY RANDOM()
LIMIT ?
"""


def fetch_sample(db_path: str, is_urban: int, n: int) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(SQL, (is_urban, n))
        rows = cur.fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "name": r[1],
                "entity_type": r[2] or "",
                "entity_type_ids": r[3] or "",
                "iso_a3": r[4] or "",
                "country": r[5] or "",
                "prediction": bool(is_urban),
            }
        )
    return out


def render_html(rows: list[dict]) -> str:
    data_json = json.dumps(rows, ensure_ascii=False)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Urban classifier review — {len(rows)} cities</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect x='2' y='6' width='3' height='8' fill='%232b6cb0'/%3E%3Crect x='6' y='3' width='4' height='11' fill='%232b6cb0'/%3E%3Crect x='11' y='8' width='3' height='6' fill='%232b6cb0'/%3E%3C/svg%3E">
<style>
  :root {{
    --bg:#fafafa; --card:#fff; --line:#e5e5e5; --ink:#1a1a1a; --muted:#666;
    --ok:#0f9d58; --ok-bg:#e6f4ea;
    --bad:#d93025; --bad-bg:#fce8e6;
    --hl:#2b6cb0;
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background:var(--bg); color:var(--ink);
  }}
  header {{
    position:sticky; top:0; z-index:10;
    background:#fff; border-bottom:1px solid var(--line);
    padding:14px 22px; display:flex; align-items:center; gap:20px; flex-wrap:wrap;
  }}
  header h1 {{ margin:0; font-size:16px; font-weight:600; }}
  header .meta {{ color:var(--muted); font-size:12px; }}
  .counters {{ display:flex; gap:14px; font-size:12px; color:var(--muted); }}
  .counters b {{ color:var(--ink); }}
  button {{
    font: inherit; cursor:pointer; border:1px solid var(--line); background:#fff;
    padding:6px 12px; border-radius:6px;
  }}
  button:hover {{ background:#f3f3f3; }}
  .primary {{ background:var(--hl); color:#fff; border-color:var(--hl); }}
  .primary:hover {{ filter:brightness(.95); background:var(--hl); }}
  main {{ padding:18px 22px 80px; max-width:1000px; margin:0 auto; }}
  .row {{
    background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:14px 16px; margin-bottom:10px;
    display:grid; grid-template-columns: 42px 1fr 220px; gap:12px; align-items:start;
  }}
  .row.annotated.correct {{ border-color:#b6dfc1; background:#f7fcf9; }}
  .row.annotated.wrong   {{ border-color:#f3b7b0; background:#fdf6f5; }}
  .idx {{ color:var(--muted); font-variant-numeric: tabular-nums; }}
  .name {{ font-weight:600; }}
  .name a {{ color:var(--ink); text-decoration:none; }}
  .name a:hover {{ color:var(--hl); text-decoration:underline; }}
  .meta2 {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .types {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }}
  .chip {{
    background:#f1f1f1; border:1px solid var(--line); color:#333;
    padding:1px 8px; border-radius:999px; font-size:11.5px;
  }}
  .pred {{ display:flex; flex-direction:column; gap:8px; align-items:flex-end; }}
  .pred-label {{ font-size:12px; color:var(--muted); }}
  .pred-val {{
    font-weight:600; padding:3px 10px; border-radius:999px; font-size:12px;
    border:1px solid var(--line);
  }}
  .pred-val.yes {{ background:var(--ok-bg); color:var(--ok); border-color:#c6e7cf; }}
  .pred-val.no  {{ background:var(--bad-bg); color:var(--bad); border-color:#f4c7c0; }}
  .buttons {{ display:flex; gap:6px; }}
  .buttons button {{ padding:5px 10px; font-size:12px; }}
  .buttons .correct {{ border-color:#9cd5aa; color:var(--ok); }}
  .buttons .correct.active {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .buttons .wrong   {{ border-color:#ecb2ab; color:var(--bad); }}
  .buttons .wrong.active {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  footer {{
    position:fixed; bottom:0; left:0; right:0; background:#fff;
    border-top:1px solid var(--line); padding:10px 22px;
    display:flex; justify-content:space-between; gap:12px;
  }}
</style>
</head>
<body>
<header>
  <h1>Urban classifier review</h1>
  <span class="meta">{len(rows)} cities · generated {now}</span>
  <div class="counters" id="counters">
    <span>annotated <b id="cnt-done">0</b>/{len(rows)}</span>
    <span>correct <b id="cnt-ok">0</b></span>
    <span>wrong <b id="cnt-bad">0</b></span>
  </div>
</header>

<main id="rows"></main>

<footer>
  <span class="meta">Click <b>Correct</b> if the prediction is right for your urbanisation study, <b>Wrong</b> if it should flip.</span>
  <div>
    <button id="clear">Clear all</button>
    <button id="export" class="primary">Export JSON</button>
  </div>
</footer>

<script>
const DATA = {data_json};
const STORAGE_KEY = "urban-annotations-v1";

function load() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }}
  catch {{ return {{}}; }}
}}
function save(ann) {{ localStorage.setItem(STORAGE_KEY, JSON.stringify(ann)); }}

const state = load();

function render() {{
  const root = document.getElementById("rows");
  root.innerHTML = "";
  let done=0, ok=0, bad=0;
  DATA.forEach((r, i) => {{
    const a = state[r.id];
    if (a) {{ done++; if (a==="correct") ok++; else if (a==="wrong") bad++; }}
    const div = document.createElement("div");
    div.className = "row" + (a ? " annotated " + a : "");
    const predClass = r.prediction ? "yes" : "no";
    const predText  = r.prediction ? "URBAN" : "NOT URBAN";
    const chips = (r.entity_type||"").split("|").filter(Boolean)
      .map(t => `<span class="chip">${{t.replace(/</g,"&lt;")}}</span>`).join("");
    const loc = [r.country, r.iso_a3].filter(Boolean).join(" · ");
    div.innerHTML = `
      <div class="idx">#${{i+1}}</div>
      <div>
        <div class="name"><a href="https://www.wikidata.org/wiki/${{r.id}}" target="_blank" rel="noopener">${{r.name}}</a>
          <span class="meta2">${{r.id}}${{loc?" · "+loc:""}}</span>
        </div>
        <div class="types">${{chips}}</div>
      </div>
      <div class="pred">
        <span class="pred-label">classifier says</span>
        <span class="pred-val ${{predClass}}">${{predText}}</span>
        <div class="buttons" data-id="${{r.id}}">
          <button class="correct ${{a==="correct"?"active":""}}" data-val="correct">✓ Correct</button>
          <button class="wrong ${{a==="wrong"?"active":""}}" data-val="wrong">✗ Wrong</button>
        </div>
      </div>`;
    root.appendChild(div);
  }});
  document.getElementById("cnt-done").textContent = done;
  document.getElementById("cnt-ok").textContent = ok;
  document.getElementById("cnt-bad").textContent = bad;
}}

document.addEventListener("click", (e) => {{
  const btn = e.target.closest(".buttons button");
  if (!btn) return;
  const id = btn.parentElement.dataset.id;
  const val = btn.dataset.val;
  if (state[id] === val) delete state[id]; else state[id] = val;
  save(state);
  render();
}});

document.getElementById("clear").addEventListener("click", () => {{
  if (!confirm("Clear all your annotations?")) return;
  for (const k of Object.keys(state)) delete state[k];
  save(state);
  render();
}});

document.getElementById("export").addEventListener("click", () => {{
  const payload = {{
    generated_at: "{now}",
    total: DATA.length,
    annotations: DATA.map(r => ({{
      id: r.id, name: r.name, prediction: r.prediction,
      entity_type: r.entity_type, country: r.country,
      annotation: state[r.id] || null,
      flip: state[r.id] === "wrong" ? !r.prediction : (state[r.id] === "correct" ? r.prediction : null)
    }}))
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "urban_annotations.json";
  a.click();
  URL.revokeObjectURL(url);
}});

render();
</script>
</body>
</html>
"""


def main() -> int:
    db_path = sys.argv[1] if len(sys.argv) > 1 else DB_PATH
    out_path = Path(sys.argv[2] if len(sys.argv) > 2 else OUT_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    random.seed()
    urban = fetch_sample(db_path, 1, N_PER_CLASS)
    non_urban = fetch_sample(db_path, 0, N_PER_CLASS)

    rows = urban + non_urban
    random.shuffle(rows)

    html = render_html(rows)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path}  ({len(rows)} cities: {len(urban)} urban + {len(non_urban)} non-urban)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
