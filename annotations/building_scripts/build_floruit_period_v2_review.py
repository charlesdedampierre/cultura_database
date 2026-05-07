"""Build annotations/floruit_period_v2_review.html.

Stratified sample (~10 per method) from the CSV produced by
`scripts/database_consolidation/01_individuals_floruit_period.py`. Joins
back to `humans_clean.duckdb` to surface occupations, Wikipedia URLs and
the raw description so each card is fully verifiable. Output is a single
self-contained HTML page; annotations are saved to the browser's
localStorage and exported as JSON.

Usage: python annotations/build_floruit_period_v2_review.py
"""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
CSV = ROOT / "temp_files" / "individuals_floruit_period.csv"
DUCKDB_PATH = ROOT / "data" / "humans_clean.duckdb"
OUT = ROOT / "annotations" / "interfaces" / "floruit_period_v2_review.html"

PER_METHOD = 10
SEED = 42

# Each tuple: (method_id, label). Display order on the filter bar.
METHODS = [
    ("floruit_property", "Floruit · Wikidata P1317"),
    ("floruit_description", "Floruit · description ('fl 1645')"),
    ("floruit_wikipedia", "Floruit · Wikipedia (single year)"),
    ("floruit_wikipedia_span", "Floruit · Wikipedia (span)"),
    ("works_span", "Works · multi-year span"),
    ("works_single", "Works · single year (expanded)"),
    ("birth_death_property", "Birth+Death · Wikidata"),
    ("birth_death_description", "Birth+Death · description"),
    ("birth_death_cv", "Birth+Death · CV database"),
    ("birth_death_wikipedia", "Birth+Death · Wikipedia"),
    ("birth_only_property", "Birth only · Wikidata"),
    ("birth_only_description", "Birth only · description"),
    ("birth_death_estimated_birth", "Birth+Death · estimated birth (life exp.)"),
    ("birth_death_estimated_death", "Birth+Death · estimated death (life exp.)"),
    ("floruit_property_century", "Floruit · Wikidata (century)"),
    ("floruit_property_decade", "Floruit · Wikidata (decade)"),
    ("birth_death_century", "Birth+Death · century"),
    ("birth_century", "Birth only · century"),
    ("death_century", "Death only · century"),
]


def fetch_samples():
    random.seed(SEED)
    conn = duckdb.connect(str(DUCKDB_PATH), read_only=True)

    # Materialise the CSV into a DuckDB table we can join against.
    conn.execute(
        f"CREATE TEMP VIEW fp AS SELECT * FROM read_csv_auto('{CSV}', header=true)"
    )

    selected = []
    for method_id, label in METHODS:
        rows = conn.execute(f"""
            SELECT
                fp.wikidata_id,
                fp.name_en,
                fp.birth_year, fp.birth_precision,
                fp.death_year, fp.death_precision,
                fp.floruit_year_property, fp.floruit_property_precision,
                fp.floruit_year_in_description,
                fp.works_period,
                fp.floruit_period_start, fp.floruit_period_end,
                fp.floruit_period,
                fp.method, fp.source, fp.precision_class, fp.estimated,
                i.description_en,
                i.dates_in_description,
                i.birthdate_in_description,
                i.deathdate_in_description,
                i.occupations_en,
                i.country_of_citizenship_en,
                i.birthdate, i.birthdate_precision,
                i.deathdate, i.deathdate_precision,
                i.floruit_date, i.floruit_precision,
                i.birthdate_from_CV,
                i.deathdate_from_CV,
                i.birthdate_from_wikipedia,
                i.deathdate_from_wikipedia,
                i.floruit_from_wikipedia,
                i.birthdate_from_life_expectancy,
                i.deathdate_from_life_expectancy,
                i.life_expectancy_lookup_source,
                i.life_expectancy_median_used,
                i.wikimedia_links_count
            FROM fp
            LEFT JOIN individuals i USING (wikidata_id)
            WHERE fp.method = '{method_id}'
              AND fp.name_en IS NOT NULL AND fp.name_en <> ''
              AND COALESCE(i.wikimedia_links_count, 0) >= 1
            ORDER BY hash(fp.wikidata_id || '{SEED}')
            LIMIT {PER_METHOD * 4}
        """).fetchall()
        cols = [d[0] for d in conn.description]
        bucket = [dict(zip(cols, r)) for r in rows]
        random.shuffle(bucket)
        selected.extend(bucket[:PER_METHOD])

    conn.close()
    random.shuffle(selected)
    return selected


# Every date-bearing column we want to surface, in the order that should
# appear in the per-card table. (column name in `individuals`, source group)
# `source` maps to the values produced by the algorithm so the picked row
# can be highlighted.
DATE_COLUMNS = [
    ("birthdate",                       "wikidata_property"),
    ("deathdate",                       "wikidata_property"),
    ("floruit_date",                    "wikidata_property"),
    ("floruit_year",                    "wikidata_property"),
    ("dates_in_description",            "wikidata_description"),
    ("birthdate_in_description",        "wikidata_description"),
    ("deathdate_in_description",        "wikidata_description"),
    ("floruit_year_in_description",     "wikidata_description"),
    ("birthdate_from_CV",               "cv_database"),
    ("deathdate_from_CV",               "cv_database"),
    ("birthdate_from_wikipedia",        "wikipedia"),
    ("deathdate_from_wikipedia",        "wikipedia"),
    ("floruit_from_wikipedia",          "wikipedia"),
    ("works_period",                    "works"),
    ("birthdate_from_life_expectancy",  "life_expectancy"),
    ("deathdate_from_life_expectancy",  "life_expectancy"),
    ("life_expectancy_lookup_source",   "life_expectancy"),
    ("life_expectancy_median_used",     "life_expectancy"),
]


PRECISION_NAME = {11: "day", 10: "month", 9: "year", 8: "decade",
                  7: "century", 6: "millennium", 5: "10k years"}

# Map a date column to the precision column that qualifies it.
PRECISION_COL = {
    "birthdate":     "birthdate_precision",
    "deathdate":     "deathdate_precision",
    "floruit_date":  "floruit_precision",
}


def precision_suffix(d, col):
    pcol = PRECISION_COL.get(col)
    if not pcol:
        return ""
    p = d.get(pcol)
    if p is None or p == "":
        return ""
    label = PRECISION_NAME.get(int(p), f"prec={p}")
    return f"  ({label})"


def to_card(d):
    """Render every date column verbatim — even when null — as a 2-column
    (field, value) list. Date columns are annotated with their precision in
    parentheses. The `source` field of the picked candidate is used to
    highlight the corresponding rows."""
    fields = []
    for col, source in DATE_COLUMNS:
        v = d.get(col)
        if v is None or v == "":
            display = None
        elif isinstance(v, float):
            display = f"{v:.0f}" if v.is_integer() else str(v)
        else:
            display = str(v)
        if display is not None:
            display += precision_suffix(d, col)
        fields.append({"col": col, "value": display, "source": source})

    return {
        "wikidata_id":   d["wikidata_id"],
        "name":          d["name_en"],
        "description":   d.get("description_en") or "",
        "occupations":   d.get("occupations_en") or "",
        "nationalities": d.get("country_of_citizenship_en") or "",
        "fields":        fields,
        "period_start":  d["floruit_period_start"],
        "period_end":    d["floruit_period_end"],
        "floruit_period": d["floruit_period"],
        "method":        d["method"],
        "source":        d["source"],
        "precision":     d["precision_class"],
        "estimated":     int(d["estimated"]) if d["estimated"] is not None else 0,
    }


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Floruit period v2 review — {N} individuals</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect x='2' y='6' width='3' height='8' fill='%232b6cb0'/%3E%3Crect x='6' y='3' width='4' height='11' fill='%232b6cb0'/%3E%3Crect x='11' y='8' width='3' height='6' fill='%232b6cb0'/%3E%3C/svg%3E">
<style>
  :root {{
    --bg:#fafafa; --card:#fff; --line:#e5e5e5; --ink:#1a1a1a; --muted:#666;
    --ok:#0f9d58; --bad:#d93025; --hl:#2b6cb0;
  }}
  * {{ box-sizing:border-box; }}
  html,body {{ margin:0; padding:0; }}
  body {{
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
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
  .filters {{ display:flex; gap:6px; flex-wrap:wrap; font-size:11px; max-width:60%; }}
  .filters label {{
    border:1px solid var(--line); padding:3px 7px; border-radius:12px;
    cursor:pointer; user-select:none; background:#fff;
  }}
  .filters input {{ display:none; }}
  .filters input:checked + span {{ color:var(--hl); font-weight:600; }}
  button {{
    font:inherit; cursor:pointer; border:1px solid var(--line); background:#fff;
    padding:6px 12px; border-radius:6px;
  }}
  button:hover {{ background:#f3f3f3; }}
  .primary {{ background:var(--hl); color:#fff; border-color:var(--hl); }}
  main {{ padding:18px 22px 80px; max-width:1200px; margin:0 auto; }}
  .row {{
    background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:14px 16px; margin-bottom:10px;
    display:grid; grid-template-columns: 36px 1fr 420px 200px; gap:16px; align-items:start;
  }}
  .row.annotated.correct {{ border-color:#b6dfc1; background:#f7fcf9; }}
  .row.annotated.wrong   {{ border-color:#f3b7b0; background:#fdf6f5; }}
  .idx {{ color:var(--muted); font-variant-numeric:tabular-nums; padding-top:2px; }}
  .name {{ font-weight:600; }}
  .name a {{ color:var(--ink); text-decoration:none; }}
  .name a:hover {{ color:var(--hl); text-decoration:underline; }}
  .desc {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .tags {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }}
  .chip {{
    border:1px solid var(--line); border-radius:12px;
    padding:2px 8px; font-size:11px; color:var(--muted);
  }}
  .method-chip {{
    display:inline-block; padding:3px 10px; font-size:11px; border-radius:12px;
    background:#eaf2ff; color:#1d3a8a; font-weight:600;
  }}
  .source-chip {{
    display:inline-block; padding:3px 10px; font-size:11px; border-radius:12px;
    background:#f3eaff; color:#4d1372; margin-left:4px;
  }}
  .precision-chip-year   {{ background:#e6f4ea; color:#0f5d33; }}
  .precision-chip-decade {{ background:#fff5cf; color:#7a5b00; }}
  .precision-chip-century{{ background:#ffe7d1; color:#8a4500; }}
  .precision-chip {{ display:inline-block; padding:3px 10px; font-size:11px; border-radius:12px; margin-left:4px; }}
  table.fields {{
    width:100%; border-collapse:collapse; font-size:12px; line-height:1.35;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  }}
  table.fields td {{
    padding:2px 8px; border-bottom:1px solid #f1f1f1; vertical-align:top;
  }}
  table.fields td.k {{
    color:var(--muted); white-space:nowrap; width:42%;
  }}
  table.fields td.v {{
    font-variant-numeric:tabular-nums; word-break:break-word;
  }}
  table.fields td.v.null {{ color:#bbb; }}
  table.fields tr.picked td {{
    background:#eaf2ff;
  }}
  table.fields tr.picked td.k {{ color:var(--hl); font-weight:600; }}
  table.fields tr.picked td.v {{ color:var(--hl); font-weight:600; }}
  .period {{
    margin-top:8px; font-size:16px; font-weight:700;
    color:var(--hl); font-variant-numeric:tabular-nums;
  }}
  .actions {{ display:flex; flex-direction:column; gap:6px; align-items:flex-end; }}
  .row-buttons {{ display:flex; gap:6px; }}
  .btn-yes, .btn-no {{
    width:46px; padding:6px 0; text-align:center; border-radius:6px;
    border:1px solid var(--line);
  }}
  .row.annotated.correct .btn-yes {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .row.annotated.wrong   .btn-no  {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  .note {{ width:100%; min-height:34px; font:inherit; padding:6px 8px;
           border:1px solid var(--line); border-radius:6px; resize:vertical; }}
  .links a {{ color:var(--hl); text-decoration:none; font-size:12px; margin-right:8px; }}
  .links a:hover {{ text-decoration:underline; }}
  footer {{
    position:fixed; left:0; right:0; bottom:0;
    background:#fff; border-top:1px solid var(--line);
    padding:10px 22px; display:flex; gap:14px; align-items:center; justify-content:space-between;
    font-size:12px; color:var(--muted);
  }}
</style>
</head>
<body>

<header>
  <h1>Floruit period · v2 review</h1>
  <span class="meta">{N} rows · {NMETHODS} methods · stratified random sample</span>
  <div class="counters">
    <span><b id="cnt-yes">0</b> correct</span>
    <span><b id="cnt-no">0</b> wrong</span>
    <span><b id="cnt-pending">{N}</b> pending</span>
  </div>
  <div class="filters" id="filters"></div>
  <button id="export" class="primary">Download annotations</button>
</header>

<main id="rows"></main>

<footer>
  <span>Saved to your browser (localStorage). Click <b>Download annotations</b> to export as JSON.</span>
  <span><kbd>y</kbd>/<kbd>n</kbd> on the focused row</span>
</footer>

<script>
const DATA = {DATA_JSON};
const METHODS = {METHODS_JSON};
const STORAGE_KEY = 'floruit_period_v2_review_v1';

const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
const activeMethods = new Set(METHODS.map(m => m[0]));

function fmt(v) {{
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}}

function renderFields(fields, source) {{
  const rows = fields.map(f => {{
    const isPicked = f.source === source;
    const isNull = f.value === null || f.value === undefined || f.value === '';
    return `<tr class="${{isPicked ? 'picked' : ''}}">
      <td class="k">${{f.col}}</td>
      <td class="v ${{isNull ? 'null' : ''}}">${{isNull ? '—' : f.value}}</td>
    </tr>`;
  }}).join('');
  return `<table class="fields">${{rows}}</table>`;
}}

function render() {{
  const main = document.getElementById('rows');
  main.innerHTML = '';
  let yes = 0, no = 0, pending = 0;

  DATA.forEach((d, i) => {{
    if (!activeMethods.has(d.method)) return;
    const verdict = state[d.wikidata_id]?.verdict;
    const note    = state[d.wikidata_id]?.note || '';
    if (verdict === 'yes') yes++;
    else if (verdict === 'no') no++;
    else pending++;

    const row = document.createElement('div');
    row.className = 'row' + (verdict ? ' annotated ' + (verdict === 'yes' ? 'correct' : 'wrong') : '');
    row.dataset.qid = d.wikidata_id;
    row.tabIndex = 0;

    const occ = d.occupations ? d.occupations.split(';').slice(0, 3).join(' · ') : '';
    const nat = d.nationalities ? d.nationalities.split(';').slice(0, 3).join(' · ') : '';
    const precClass = `precision-chip-${{d.precision || 'unknown'}}`;

    row.innerHTML = `
      <div class="idx">${{i + 1}}</div>
      <div>
        <div class="name">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">${{fmt(d.name)}}</a>
        </div>
        ${{d.description ? `<div class="desc">${{d.description}}</div>` : ''}}
        <div class="tags">
          ${{occ ? `<span class="chip">${{occ}}</span>` : ''}}
          ${{nat ? `<span class="chip">${{nat}}</span>` : ''}}
          <span class="chip">${{d.wikidata_id}}</span>
        </div>
        <div class="links" style="margin-top:6px;">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">Wikidata</a>
          <a href="https://en.wikipedia.org/wiki/Special:Search/${{encodeURIComponent(d.name || d.wikidata_id)}}" target="_blank">Wikipedia search</a>
          <a href="https://www.google.com/search?q=${{encodeURIComponent((d.name || '') + ' ' + (d.description || ''))}}" target="_blank">Google</a>
        </div>
      </div>
      <div>
        ${{renderFields(d.fields, d.source)}}
        <div class="period">→ ${{fmt(d.floruit_period)}}</div>
        <div style="margin-top:6px;">
          <span class="method-chip">${{d.method}}</span>
          <span class="source-chip">${{d.source}}</span>
          <span class="precision-chip ${{precClass}}">${{d.precision || 'n/a'}}</span>
          ${{d.estimated ? '<span class="chip" style="margin-left:4px;background:#fff5cf;color:#7a5b00;">estimated</span>' : ''}}
        </div>
      </div>
      <div class="actions">
        <div class="row-buttons">
          <button class="btn-yes" data-verdict="yes" title="Correct (y)">Yes</button>
          <button class="btn-no"  data-verdict="no"  title="Wrong (n)">No</button>
        </div>
        <textarea class="note" placeholder="Optional note">${{note.replace(/</g, '&lt;')}}</textarea>
      </div>
    `;

    row.querySelectorAll('button').forEach(btn => {{
      btn.addEventListener('click', () => mark(d.wikidata_id, btn.dataset.verdict));
    }});
    row.querySelector('.note').addEventListener('change', e => {{
      state[d.wikidata_id] = state[d.wikidata_id] || {{}};
      state[d.wikidata_id].note = e.target.value;
      persist();
    }});

    main.appendChild(row);
  }});

  document.getElementById('cnt-yes').textContent = yes;
  document.getElementById('cnt-no').textContent = no;
  document.getElementById('cnt-pending').textContent = pending;
}}

function mark(qid, verdict) {{
  const cur = state[qid] || {{}};
  if (cur.verdict === verdict) delete cur.verdict;
  else cur.verdict = verdict;
  state[qid] = cur;
  persist();
  render();
}}

function persist() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}}

function buildFilters() {{
  const cont = document.getElementById('filters');
  METHODS.forEach(([id, label]) => {{
    const lab = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.addEventListener('change', () => {{
      if (cb.checked) activeMethods.add(id);
      else activeMethods.delete(id);
      render();
    }});
    const span = document.createElement('span');
    span.textContent = label;
    lab.appendChild(cb);
    lab.appendChild(span);
    cont.appendChild(lab);
  }});
}}

document.getElementById('export').addEventListener('click', () => {{
  const out = DATA.map(d => ({{
    wikidata_id: d.wikidata_id,
    name: d.name,
    method: d.method, source: d.source, precision: d.precision,
    fields: d.fields,
    floruit_period: d.floruit_period,
    period_start: d.period_start, period_end: d.period_end,
    verdict: state[d.wikidata_id]?.verdict || null,
    note:    state[d.wikidata_id]?.note    || '',
  }}));
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'floruit_period_v2_annotations.json';
  a.click();
  URL.revokeObjectURL(url);
}});

document.addEventListener('keydown', e => {{
  if (e.target.tagName === 'TEXTAREA' || e.target.tagName === 'INPUT') return;
  const focused = document.activeElement;
  if (!focused || !focused.classList.contains('row')) return;
  const qid = focused.dataset.qid;
  if (e.key === 'y') mark(qid, 'yes');
  else if (e.key === 'n') mark(qid, 'no');
}});

buildFilters();
render();
</script>
</body>
</html>
"""


def main():
    rows = fetch_samples()
    cards = [to_card(r) for r in rows]
    methods_for_filter = [[m, l] for m, l in METHODS]
    html = HTML.format(
        N=len(cards),
        NMETHODS=len(METHODS),
        DATA_JSON=json.dumps(cards, ensure_ascii=False),
        METHODS_JSON=json.dumps(methods_for_filter, ensure_ascii=False),
    )
    OUT.write_text(html, encoding="utf-8")

    counts = Counter(r["method"] for r in rows)
    print(f"Wrote {len(cards)} cards -> {OUT}")
    for mid, label in METHODS:
        print(f"  {mid:30s} {counts.get(mid, 0):3d}   {label}")


if __name__ == "__main__":
    main()
