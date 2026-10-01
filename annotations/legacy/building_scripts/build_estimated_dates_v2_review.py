"""Build a self-contained HTML annotation tool from the v2 estimator CSV.

Reads `data/estimated_dates_v2_sample.csv` (or the path passed via
`--csv`) and writes a single-file HTML page the user can open in a
browser to mark each estimate Yes / No / Unsure with optional notes,
then download all annotations as JSON.

The HTML is self-contained: it embeds the CSV rows as inline JSON. No
network requests, no build step.

Usage:
    python annotations/build_estimated_dates_v2_review.py
    python annotations/build_estimated_dates_v2_review.py \\
        --csv data/estimated_dates_v2_sample.csv \\
        --out annotations/estimated_dates_v2_review.html
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CSV = ROOT / "data" / "estimated_dates_v2_sample.csv"
DEFAULT_OUT = ROOT / "annotations" / "interfaces" / "estimated_dates_v2_review.html"


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Estimated dates v2 review &mdash; {N} individuals</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6' fill='none' stroke='%232b6cb0' stroke-width='1.5'/%3E%3Cpath d='M8 4v4l2.5 2.5' stroke='%232b6cb0' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
  :root {{
    --bg:#fafafa; --card:#fff; --line:#e5e5e5; --ink:#1a1a1a; --muted:#666;
    --ok:#0f9d58; --bad:#d93025; --hl:#2b6cb0; --warn:#b76e00;
    --est-bg:#fff8e6; --est-line:#f1d68a;
    --low-prec-bg:#fbe9e7; --low-prec-fg:#8a3a13;
  }}
  * {{ box-sizing:border-box; }}
  html, body {{ margin:0; padding:0; }}
  body {{
    font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background:var(--bg); color:var(--ink);
  }}
  header {{
    position:sticky; top:0; z-index:10;
    background:#fff; border-bottom:1px solid var(--line);
    padding:14px 22px; display:flex; align-items:center; gap:18px; flex-wrap:wrap;
  }}
  header h1 {{ margin:0; font-size:16px; font-weight:600; }}
  header .meta {{ color:var(--muted); font-size:12px; }}
  .counters {{ display:flex; gap:14px; font-size:12px; color:var(--muted); }}
  .counters b {{ color:var(--ink); }}
  .filters {{ display:flex; gap:6px; flex-wrap:wrap; font-size:12px; }}
  .filters label {{
    border:1px solid var(--line); padding:4px 9px; border-radius:14px;
    cursor:pointer; user-select:none; background:#fff;
  }}
  .filters input {{ display:none; }}
  .filters input:checked + span {{ color:var(--hl); font-weight:600; }}
  button {{
    font: inherit; cursor:pointer; border:1px solid var(--line); background:#fff;
    padding:6px 12px; border-radius:6px;
  }}
  button:hover {{ background:#f3f3f3; }}
  .primary {{ background:var(--hl); color:#fff; border-color:var(--hl); }}
  .primary:hover {{ filter:brightness(.95); background:var(--hl); }}
  main {{ padding:18px 22px 90px; max-width:1180px; margin:0 auto; }}
  .row {{
    background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:14px 16px; margin-bottom:10px;
    display:grid; grid-template-columns: 42px 1fr 340px 220px; gap:14px; align-items:start;
  }}
  .row.annotated.correct {{ border-color:#b6dfc1; background:#f7fcf9; }}
  .row.annotated.wrong   {{ border-color:#f3b7b0; background:#fdf6f5; }}
  .row.annotated.unsure  {{ border-color:#e2cea2; background:#fdf9ef; }}
  .idx {{ color:var(--muted); font-variant-numeric: tabular-nums; padding-top:2px; }}
  .name {{ font-weight:600; }}
  .name a {{ color:var(--ink); text-decoration:none; }}
  .name a:hover {{ color:var(--hl); text-decoration:underline; }}
  .desc {{ color:var(--muted); font-size:12px; margin-top:2px; }}
  .tags {{ margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }}
  .chip {{
    border:1px solid var(--line); border-radius:12px;
    padding:2px 8px; font-size:11px; color:var(--muted);
  }}
  .bucket-chip {{
    display:inline-block; padding:3px 9px; font-size:11px; border-radius:12px;
    font-weight:600;
  }}
  .b-Culture            {{ background:#fde2e7; color:#a01231; }}
  .b-SportsGames        {{ background:#e3f2dc; color:#256025; }}
  .b-Leadership         {{ background:#dde6f8; color:#1d3a8a; }}
  .b-DiscoveryScience   {{ background:#fff5cf; color:#7a5b00; }}
  .b-Other              {{ background:#ecdcf3; color:#4d1372; }}
  .b-no_cv              {{ background:#eee; color:#444; border:1px dashed #bbb; }}
  .dates {{
    display:grid; grid-template-columns:auto 1fr; column-gap:10px; row-gap:4px;
    font-size:12.8px; line-height:1.4;
  }}
  .dates .k {{ color:var(--muted); }}
  .dates .v {{ font-variant-numeric: tabular-nums; }}
  .prec-low {{
    display:inline-block; margin-left:6px; padding:1px 7px;
    background:var(--low-prec-bg); color:var(--low-prec-fg);
    border-radius:10px; font-size:10.5px; font-weight:600;
  }}
  .est-row {{
    background:var(--est-bg); border:1px solid var(--est-line);
    border-radius:6px; padding:5px 9px; margin-top:6px;
    display:flex; align-items:baseline; gap:8px;
    font-variant-numeric: tabular-nums;
  }}
  .est-row .lbl {{ color:var(--warn); font-weight:700; font-size:11px; text-transform:uppercase; letter-spacing:0.4px; }}
  .est-row .val {{ font-size:14px; font-weight:700; color:var(--warn); }}
  .lifespan {{ margin-top:6px; font-size:12px; color:var(--muted); }}
  .lifespan b {{ color:var(--ink); font-variant-numeric: tabular-nums; }}
  .source-line {{ margin-top:4px; font-size:11.5px; color:var(--muted); font-variant-numeric: tabular-nums; }}
  .actions {{ display:flex; flex-direction:column; gap:6px; align-items:flex-end; }}
  .actions .row-buttons {{ display:flex; gap:6px; }}
  .btn-yes, .btn-no, .btn-unsure {{
    width:54px; padding:6px 0; text-align:center; border-radius:6px;
    border:1px solid var(--line);
  }}
  .row.annotated.correct .btn-yes    {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .row.annotated.wrong   .btn-no     {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  .row.annotated.unsure  .btn-unsure {{ background:var(--warn); color:#fff; border-color:var(--warn); }}
  .note {{ width:100%; min-height:34px; font: inherit; padding:6px 8px;
           border:1px solid var(--line); border-radius:6px; resize:vertical; }}
  .links a {{ color:var(--hl); text-decoration:none; font-size:12px; margin-right:8px; }}
  .links a:hover {{ text-decoration:underline; }}
  footer {{
    position:fixed; left:0; right:0; bottom:0;
    background:#fff; border-top:1px solid var(--line);
    padding:10px 22px; display:flex; gap:14px; align-items:center; justify-content:space-between;
    font-size:12px; color:var(--muted);
  }}
  kbd {{
    border:1px solid var(--line); border-bottom-width:2px; border-radius:4px;
    padding:1px 5px; font-size:11px; background:#fafafa; font-family: ui-monospace, monospace;
  }}
</style>
</head>
<body>

<header>
  <h1>Estimated dates v2 review</h1>
  <span class="meta">{N} rows &middot; 50-yr bins, n&ge;50 lookup &middot; cascade: (CV category &times; period) &rarr; (period only)</span>
  <div class="counters">
    <span><b id="cnt-yes">0</b> plausible</span>
    <span><b id="cnt-no">0</b> wrong</span>
    <span><b id="cnt-unsure">0</b> unsure</span>
    <span><b id="cnt-pending">{N}</b> pending</span>
  </div>
  <div class="filters" id="filters"></div>
  <button id="export" class="primary">Download annotations</button>
</header>

<main id="rows"></main>

<footer>
  <span>Annotations are saved to your browser (localStorage). Click <b>Download annotations</b> to save them as JSON.</span>
  <span><kbd>y</kbd> plausible &middot; <kbd>n</kbd> wrong &middot; <kbd>u</kbd> unsure</span>
</footer>

<script>
const DATA = {DATA_JSON};
const STORAGE_KEY = 'estimated_dates_v2_review_v1';

const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
const buckets = Array.from(new Set(DATA.map(d => d.cv_category || 'no_cv')));
const activeBuckets = new Set(buckets);

function fmt(v) {{
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}}

function bucketKey(cat) {{ return cat ? cat.replace(/[^A-Za-z]/g, '') : 'no_cv'; }}

function precChip(p, label) {{
  if (!p && p !== 0) return '';
  if (p >= 9) return ` <span class="chip">${{label}}</span>`;
  return ` <span class="prec-low">${{label || ('prec=' + p)}} (placeholder)</span>`;
}}

function render() {{
  const main = document.getElementById('rows');
  main.innerHTML = '';
  let yes = 0, no = 0, unsure = 0, pending = 0;

  DATA.forEach((d, i) => {{
    const cat = d.cv_category || 'no_cv';
    if (!activeBuckets.has(cat)) return;
    const verdict = state[d.wikidata_id]?.verdict;
    const note    = state[d.wikidata_id]?.note || '';
    if (verdict === 'yes') yes++;
    else if (verdict === 'no') no++;
    else if (verdict === 'unsure') unsure++;
    else pending++;

    const cls = verdict === 'yes' ? 'correct' : verdict === 'no' ? 'wrong' : verdict === 'unsure' ? 'unsure' : '';
    const row = document.createElement('div');
    row.className = 'row' + (verdict ? ' annotated ' + cls : '');
    row.dataset.qid = d.wikidata_id;
    row.tabIndex = 0;

    const occ = d.occupations_en ? String(d.occupations_en).split(';').slice(0, 3).join(' · ') : '';
    const nat = d.country_of_citizenship_en ? String(d.country_of_citizenship_en).split(';').slice(0, 2).join(' · ') : '';

    const realBirthLine = d.real_birth
      ? `<span class="k">Birth (real):</span><span class="v">${{d.real_birth}}${{precChip(d.real_birth_precision, d.real_birth_precision_label)}}</span>`
      : '';
    const realDeathLine = d.real_death
      ? `<span class="k">Death (real):</span><span class="v">${{d.real_death}}${{precChip(d.real_death_precision, d.real_death_precision_label)}}</span>`
      : '';

    const estLine = d.est_kind === 'birth'
      ? `<div class="est-row"><span class="lbl">Birth estimated</span><span class="val">${{d.est_date || ''}}</span></div>`
      : `<div class="est-row"><span class="lbl">Death estimated</span><span class="val">${{d.est_date || ''}}</span></div>`;

    // Implied lifespan: prefer the est date over a low-precision real
    const realPrec = d.est_kind === 'birth' ? d.real_death_precision : d.real_birth_precision;
    const lifespanLine = d.implied_lifespan != null
      ? `<div class="lifespan">Implied lifespan (est ↔ anchor): <b>${{d.implied_lifespan}}</b> yr ` +
        `(median used: ${{Number(d.median_life_expectancy_used).toFixed(1)}} yr)</div>` : '';

    const sourceLine = `<div class="source-line">Source: ${{d.lookup_source}} &middot; period bin ${{d.period_bin}} &middot; anchor ${{d.anchor_kind}}=${{d.anchor_year}}</div>`;

    const bk = bucketKey(d.cv_category);

    row.innerHTML = `
      <div class="idx">${{i + 1}}</div>
      <div>
        <div class="name">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">${{fmt(d.name_en)}}</a>
        </div>
        ${{d.description_en ? `<div class="desc">${{d.description_en}}</div>` : ''}}
        <div class="tags">
          ${{occ ? `<span class="chip">${{occ}}</span>` : ''}}
          ${{nat ? `<span class="chip">${{nat}}</span>` : ''}}
          ${{d.gender ? `<span class="chip">${{d.gender}}</span>` : ''}}
          <span class="chip">${{d.wikidata_id}}</span>
          ${{d.in_cv ? '<span class="chip" style="color:#1d3a8a;border-color:#bcd;">in CV</span>' : ''}}
          ${{d.wikimedia_links_count ? `<span class="chip">${{d.wikimedia_links_count}} wiki link${{d.wikimedia_links_count > 1 ? 's' : ''}}</span>` : ''}}
        </div>
        <div class="links" style="margin-top:6px;">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">Wikidata</a>
          <a href="https://en.wikipedia.org/wiki/Special:Search/${{encodeURIComponent(d.name_en || d.wikidata_id)}}" target="_blank">Wikipedia</a>
          <a href="https://www.google.com/search?q=${{encodeURIComponent((d.name_en || '') + ' ' + (d.description_en || ''))}}" target="_blank">Google</a>
        </div>
      </div>
      <div>
        <div class="dates">
          ${{realBirthLine}}
          ${{realDeathLine}}
        </div>
        ${{estLine}}
        ${{lifespanLine}}
        ${{sourceLine}}
        <div style="margin-top:8px;">
          <span class="b-${{bk}} bucket-chip">${{d.cv_category || 'no CV category'}}</span>
        </div>
      </div>
      <div class="actions">
        <div class="row-buttons">
          <button class="btn-yes"    data-verdict="yes"    title="Plausible (y)">Yes</button>
          <button class="btn-no"     data-verdict="no"     title="Wrong (n)">No</button>
          <button class="btn-unsure" data-verdict="unsure" title="Unsure (u)">?</button>
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
  document.getElementById('cnt-unsure').textContent = unsure;
  document.getElementById('cnt-pending').textContent = pending;
}}

function mark(qid, verdict) {{
  const cur = state[qid] || {{}};
  if (cur.verdict === verdict) {{
    delete cur.verdict;
  }} else {{
    cur.verdict = verdict;
  }}
  state[qid] = cur;
  persist();
  render();
}}

function persist() {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}}

function buildFilters() {{
  const cont = document.getElementById('filters');
  buckets.forEach(b => {{
    const lab = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.addEventListener('change', () => {{
      if (cb.checked) activeBuckets.add(b);
      else activeBuckets.delete(b);
      render();
    }});
    const span = document.createElement('span');
    span.textContent = b === 'no_cv' ? 'no CV category' : b;
    lab.appendChild(cb);
    lab.appendChild(span);
    cont.appendChild(lab);
  }});
}}

document.getElementById('export').addEventListener('click', () => {{
  const out = DATA.map(d => ({{
    wikidata_id: d.wikidata_id,
    name: d.name_en,
    cv_category: d.cv_category,
    est_kind: d.est_kind,
    real_birth: d.real_birth,
    real_birth_precision: d.real_birth_precision,
    real_death: d.real_death,
    real_death_precision: d.real_death_precision,
    est_date: d.est_date,
    median_life_expectancy_used: d.median_life_expectancy_used,
    lookup_source: d.lookup_source,
    period_bin: d.period_bin,
    implied_lifespan: d.implied_lifespan,
    in_cv: d.in_cv,
    verdict: state[d.wikidata_id]?.verdict || null,
    note:    state[d.wikidata_id]?.note    || '',
  }}));
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'estimated_dates_v2_annotations.json';
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
  else if (e.key === 'u') mark(qid, 'unsure');
}});

buildFilters();
render();
</script>
</body>
</html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"CSV not found: {args.csv}")

    df = pl.read_csv(args.csv)
    rows = df.to_dicts()
    print(f"Loaded {len(rows)} rows from {args.csv}")

    html = HTML_TEMPLATE.format(
        N=len(rows),
        DATA_JSON=json.dumps(rows, ensure_ascii=False, default=str),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote annotation tool -> {args.out}")
    print(f"Open it in a browser:  file://{args.out.resolve()}")


if __name__ == "__main__":
    main()
