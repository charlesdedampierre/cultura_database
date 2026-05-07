"""Build annotations/floruit_period_review.html.

Stratified sample (~10 per rule) from individuals_floruit_period so every
floruit-assignment rule is represented. Outputs a single self-contained HTML
file the user can open in a browser to mark each row Yes/No and download
the annotations as JSON.

Usage: python annotations/build_floruit_period_review.py
"""

import json
import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'data' / 'humans_clean.sqlite3'
OUT = ROOT / 'annotations' / 'interfaces' / 'floruit_period_review.html'

PER_CATEGORY = 10
SEED = 42
random.seed(SEED)

# (rule_id, label, SQL filter)
RULES = [
    (
        'floruit_p1317',
        'Floruit from Wikidata floruit (P1317)',
        "method = 'floruit'",
    ),
    (
        'birth',
        'Floruit from birth date',
        "method = 'birth' "
        "AND NOT (death_year IS NOT NULL AND birth_year IS NOT NULL "
        "         AND death_year < birth_year + 55)",
    ),
    (
        'birth_century_single',
        'Birth century only (single century)',
        "method = 'birth_century' AND floruit_period NOT LIKE '%-%'",
    ),
    (
        'birth_century_span',
        'Birth century → next/later century (spans)',
        "method = 'birth_century' AND floruit_period LIKE '%-%'",
    ),
    (
        'birth_capped',
        'Floruit from birth date, capped by death',
        "method = 'birth' AND birth_year IS NOT NULL "
        "AND death_year IS NOT NULL AND death_year < birth_year + 55",
    ),
    (
        'death',
        'Floruit from death date',
        "method = 'death'",
    ),
    (
        'death_century',
        'Floruit from death date (century precision)',
        "method = 'death_century'",
    ),
]

PRECISION_NAME = {
    11: 'day', 10: 'month', 9: 'year', 8: 'decade',
    7: 'century', 6: 'millennium', 5: '10k years',
}


def precision_str(p):
    if p is None:
        return ''
    return PRECISION_NAME.get(p, f'prec={p}')


def fetch_samples():
    conn = sqlite3.connect(DB)
    rows = []
    for rule_id, label, where in RULES:
        # Prefer rows with name_en + with at least one sitelink so the user
        # can verify against Wikipedia.
        sql = f"""
            SELECT fp.wikidata_id, fp.name_en,
                   fp.birth_year, fp.birthdate_precision, fp.birthdate,
                   fp.death_year, fp.deathdate_precision, fp.deathdate,
                   fp.floruit_year, fp.floruit_precision,
                   fp.floruit_period,
                   i.description_en, i.occupations_en, i.nationalities_en,
                   i.sitelinks_count
            FROM individuals_floruit_period fp
            LEFT JOIN individuals i ON i.wikidata_id = fp.wikidata_id
            WHERE {where}
              AND fp.name_en IS NOT NULL
              AND fp.name_en != ''
              AND COALESCE(i.sitelinks_count, 0) >= 1
            ORDER BY RANDOM()
            LIMIT {PER_CATEGORY * 4}
        """
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description]
        bucket = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            d['rule_id'] = rule_id
            d['rule_label'] = label
            bucket.append(d)
        # Deterministic pick of PER_CATEGORY
        random.shuffle(bucket)
        rows.extend(bucket[:PER_CATEGORY])
    conn.close()
    # Mix the order across rules so the user is not biased by category clusters
    random.shuffle(rows)
    return rows


def to_card(d):
    return {
        'wikidata_id':   d['wikidata_id'],
        'name':          d['name_en'],
        'description':   d.get('description_en') or '',
        'occupations':   d.get('occupations_en') or '',
        'nationalities': d.get('nationalities_en') or '',
        'birth_year':    d['birth_year'],
        'birth_prec':    precision_str(d['birthdate_precision']),
        'birthdate':     d['birthdate'],
        'death_year':    d['death_year'],
        'death_prec':    precision_str(d['deathdate_precision']),
        'deathdate':     d['deathdate'],
        'floruit_year':  d['floruit_year'],
        'floruit_prec':  precision_str(d['floruit_precision']),
        'floruit_period': d['floruit_period'],
        'rule_id':       d['rule_id'],
        'rule_label':    d['rule_label'],
    }


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Floruit period review — {N} individuals</title>
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
  .filters {{ display:flex; gap:6px; flex-wrap:wrap; font-size:12px; }}
  .filters label {{
    border:1px solid var(--line); padding:4px 8px; border-radius:14px;
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
  main {{ padding:18px 22px 80px; max-width:1100px; margin:0 auto; }}
  .row {{
    background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:14px 16px; margin-bottom:10px;
    display:grid; grid-template-columns: 42px 1fr 280px 220px; gap:14px; align-items:start;
  }}
  .row.annotated.correct {{ border-color:#b6dfc1; background:#f7fcf9; }}
  .row.annotated.wrong   {{ border-color:#f3b7b0; background:#fdf6f5; }}
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
  .rule-chip {{
    display:inline-block; padding:3px 9px; font-size:11px; border-radius:12px;
    font-weight:600;
  }}
  .rule-floruit_p1317        {{ background:#fde2e7; color:#a01231; }}
  .rule-birth                {{ background:#e3f2dc; color:#256025; }}
  .rule-birth_century_single {{ background:#fff5cf; color:#7a5b00; }}
  .rule-birth_century_span   {{ background:#ffd966; color:#5e4400; }}
  .rule-birth_capped         {{ background:#dde6f8; color:#1d3a8a; }}
  .rule-death                {{ background:#fde0cf; color:#a04d11; }}
  .rule-death_century        {{ background:#ecdcf3; color:#4d1372; }}
  .dates {{
    display:grid; grid-template-columns:auto 1fr; column-gap:8px; row-gap:3px;
    font-size:12.5px; line-height:1.4;
  }}
  .dates .k {{ color:var(--muted); }}
  .dates .v {{ font-variant-numeric: tabular-nums; }}
  .period {{
    margin-top:8px; font-size:15px; font-weight:700;
    color:var(--hl); font-variant-numeric: tabular-nums;
    letter-spacing:0.2px;
  }}
  .actions {{ display:flex; flex-direction:column; gap:6px; align-items:flex-end; }}
  .actions .row-buttons {{ display:flex; gap:6px; }}
  .btn-yes, .btn-no {{
    width:46px; padding:6px 0; text-align:center; border-radius:6px;
    border:1px solid var(--line);
  }}
  .row.annotated.correct .btn-yes {{ background:var(--ok); color:#fff; border-color:var(--ok); }}
  .row.annotated.wrong   .btn-no  {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
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
</style>
</head>
<body>

<header>
  <h1>Floruit period review</h1>
  <span class="meta">{N} rows · 6 rules · stratified random sample</span>
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
  <span>Annotations are saved to your browser (localStorage). Click <b>Download annotations</b> to save them as JSON.</span>
  <span><kbd>y</kbd>/<kbd>n</kbd> on the focused row</span>
</footer>

<script>
const DATA = {DATA_JSON};
const STORAGE_KEY = 'floruit_period_review_v1';

const RULE_IDS = [
  ['floruit_p1317',         'Floruit from Wikidata floruit (P1317)'],
  ['birth',                 'Floruit from birth date'],
  ['birth_century_single',  'Birth century only (single)'],
  ['birth_century_span',    'Birth century → next/later century (spans)'],
  ['birth_capped',          'Floruit from birth date, capped by death'],
  ['death',                 'Floruit from death date'],
  ['death_century',         'Floruit from death date (century precision)'],
];

const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
const activeRules = new Set(RULE_IDS.map(r => r[0]));

function fmt(v) {{
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}}

function render() {{
  const main = document.getElementById('rows');
  main.innerHTML = '';
  let yes = 0, no = 0, pending = 0;

  DATA.forEach((d, i) => {{
    if (!activeRules.has(d.rule_id)) return;
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
        <div class="dates">
          <span class="k">Birth:</span>
          <span class="v">${{fmt(d.birth_year)}} ${{d.birth_prec ? '(' + d.birth_prec + ')' : ''}}</span>
          <span class="k">Death:</span>
          <span class="v">${{fmt(d.death_year)}} ${{d.death_prec ? '(' + d.death_prec + ')' : ''}}</span>
          ${{d.floruit_year !== null ? `
            <span class="k">P1317:</span>
            <span class="v">${{d.floruit_year}} ${{d.floruit_prec ? '(' + d.floruit_prec + ')' : ''}}</span>` : ''}}
        </div>
        <div class="period">Floruit: ${{fmt(d.floruit_period)}}</div>
        <div style="margin-top:6px;">
          <span class="rule-chip rule-${{d.rule_id}}">${{d.rule_label}}</span>
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
  RULE_IDS.forEach(([id, label]) => {{
    const lab = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.addEventListener('change', () => {{
      if (cb.checked) activeRules.add(id);
      else activeRules.delete(id);
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
    rule_id: d.rule_id,
    rule_label: d.rule_label,
    birth_year: d.birth_year,
    death_year: d.death_year,
    floruit_year: d.floruit_year,
    floruit_period: d.floruit_period,
    verdict: state[d.wikidata_id]?.verdict || null,
    note:    state[d.wikidata_id]?.note    || '',
  }}));
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'floruit_period_annotations.json';
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
    html = HTML.format(N=len(cards), DATA_JSON=json.dumps(cards, ensure_ascii=False))
    OUT.write_text(html, encoding='utf-8')
    print(f'Wrote {len(cards)} rows -> {OUT}')

    # Show per-rule counts so user can sanity check
    from collections import Counter
    c = Counter(r['rule_id'] for r in cards)
    for rid, label, _ in RULES:
        print(f'  {rid:18s} {c[rid]:3d}   {label}')


if __name__ == '__main__':
    main()
