"""Generate an HTML annotation page with sample individuals from each floruit rule category."""
import sqlite3
import random

DB = '../data/humans_clean.sqlite3'
OUT = 'floruit_annotation.html'
SAMPLES_PER_CAT = 10
SEED = 42

random.seed(SEED)

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Fetch all relevant rows with precision info
cur.execute("""
    SELECT wikidata_id, name_en, method,
           birth_year, birthdate_precision,
           death_year, deathdate_precision,
           floruit_year, floruit_precision,
           floruit_start, floruit_end, floruit_period
    FROM individuals_floruit_period
    WHERE method IN ('p1317_anchor','birth_death','birth_only','death_only')
      AND name_en IS NOT NULL
""")
columns = [d[0] for d in cur.description]
rows = [dict(zip(columns, r)) for r in cur.fetchall()]
conn.close()

# Classify each row
def classify(r):
    m = r['method']
    if m == 'p1317_anchor':
        return 'Floruit date'
    if m == 'death_only':
        if r['birthdate_precision'] == 7:
            return 'Death / century birth'
        return 'Death'
    if m == 'birth_death':
        b, d = r['birth_year'], r['death_year']
        if b is not None and d is not None and d < b + 55:
            return 'Floruit interrupted by death'
    # birth_only or birth_death where death didn't cap
    if m in ('birth_only', 'birth_death'):
        if r['deathdate_precision'] == 7:
            return 'Birth / century death'
    return 'Birth'

ORDER = [
    'Floruit date',
    'Birth',
    'Birth / century death',
    'Floruit interrupted by death',
    'Death',
    'Death / century birth',
]

COLORS = {
    'Floruit date':                  '#e6194b',
    'Birth':                         '#3cb44b',
    'Birth / century death':         '#ffe119',
    'Floruit interrupted by death':  '#4363d8',
    'Death':                         '#f58231',
    'Death / century birth':         '#911eb4',
}

RULES = {
    'Floruit date':
        'Uses Wikidata floruit property (P1317). Floruit spans 25 years from that date, capped by death year.',
    'Birth':
        'Year-precise birth, death either missing or past age 55. Floruit = birth+30 to birth+55.',
    'Birth / century death':
        'Year-precise birth, death known only at century precision (ignored). Floruit = birth+30 to birth+55.',
    'Floruit interrupted by death':
        'Year-precise birth and death, person died before age 55. Floruit = birth+30 to death_year (cut short).',
    'Death':
        'Year-precise death, no usable birth info. Floruit = death-25 to death.',
    'Death / century birth':
        'Year-precise death, birth known only at century precision (ignored). Floruit = death-25 to death.',
}

PRECISION_LABELS = {
    None: '-', 6: 'millennium', 7: 'century', 8: 'decade',
    9: 'year', 10: 'month', 11: 'day',
}

# Bucket rows by category and sample
buckets = {cat: [] for cat in ORDER}
for r in rows:
    cat = classify(r)
    buckets[cat].append(r)

samples = {}
for cat in ORDER:
    pool = buckets[cat]
    n = min(SAMPLES_PER_CAT, len(pool))
    samples[cat] = random.sample(pool, n)

# Build HTML
def fmt(v):
    if v is None:
        return '<span style="color:#999">-</span>'
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)

html_parts = []
html_parts.append("""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Floruit Rule Annotation</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #fafafa; }
  h1 { font-size: 1.5rem; }
  .cat-section { margin-bottom: 2.5rem; }
  .cat-header { padding: 0.6rem 1rem; color: #fff; border-radius: 6px 6px 0 0; }
  .cat-rule { background: #f0f0f0; padding: 0.5rem 1rem; font-size: 0.9rem; border-bottom: 1px solid #ddd; }
  .cat-count { font-weight: normal; font-size: 0.85rem; opacity: 0.85; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { background: #eee; text-align: left; padding: 6px 8px; position: sticky; top: 0; }
  td { padding: 6px 8px; border-bottom: 1px solid #e0e0e0; }
  tr:hover td { background: #ffffcc; }
  .anno-cell { min-width: 180px; }
  .anno-cell select { margin-right: 6px; }
  .anno-cell input { width: 140px; }
  a { color: #1a0dab; }
  .summary { margin: 1.5rem 0; padding: 1rem; background: #fff; border: 1px solid #ddd; border-radius: 6px; }
  .legend { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 1.5rem; }
  .legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.9rem; }
  .legend-swatch { width: 16px; height: 16px; border-radius: 3px; }
  #export-btn { padding: 8px 20px; font-size: 1rem; cursor: pointer; margin-top: 1rem; }
</style>
</head><body>
<h1>Floruit Period Assignment - Annotation Page</h1>
<p>Check whether each individual's floruit period was assigned correctly given the rule for its category.</p>
<div class="legend">
""")

for cat in ORDER:
    html_parts.append(
        f'<div class="legend-item"><div class="legend-swatch" style="background:{COLORS[cat]}"></div>{cat} ({len(buckets[cat]):,})</div>'
    )

html_parts.append('</div>')

SHOW_COLS = [
    ('wikidata_id', 'Wikidata ID'),
    ('name_en', 'Name'),
    ('birth_year', 'Birth year'),
    ('birthdate_precision', 'Birth prec.'),
    ('death_year', 'Death year'),
    ('deathdate_precision', 'Death prec.'),
    ('floruit_year', 'Floruit (P1317)'),
    ('floruit_start', 'Floruit start'),
    ('floruit_end', 'Floruit end'),
]

for cat in ORDER:
    color = COLORS[cat]
    # darken text for yellow
    text_color = '#000' if cat == 'Birth / century death' else '#fff'
    html_parts.append(f'<div class="cat-section">')
    html_parts.append(f'<div class="cat-header" style="background:{color};color:{text_color}">'
                      f'{cat} <span class="cat-count">({len(buckets[cat]):,} total)</span></div>')
    html_parts.append(f'<div class="cat-rule"><strong>Rule:</strong> {RULES[cat]}</div>')
    html_parts.append('<table><thead><tr>')
    html_parts.append('<th>#</th>')
    for _, label in SHOW_COLS:
        html_parts.append(f'<th>{label}</th>')
    html_parts.append('<th class="anno-cell">Annotation</th>')
    html_parts.append('</tr></thead><tbody>')

    for i, r in enumerate(samples[cat], 1):
        html_parts.append('<tr>')
        html_parts.append(f'<td>{i}</td>')
        for col, _ in SHOW_COLS:
            v = r[col]
            if col == 'wikidata_id':
                html_parts.append(f'<td><a href="https://www.wikidata.org/wiki/{v}" target="_blank">{v}</a></td>')
            elif col in ('birthdate_precision', 'deathdate_precision'):
                html_parts.append(f'<td>{PRECISION_LABELS.get(v, v)}</td>')
            else:
                html_parts.append(f'<td>{fmt(v)}</td>')
        # Annotation column
        row_id = f'{cat.replace(" ","_").replace("/","_")}_{i}'
        html_parts.append(f'''<td class="anno-cell">
            <select id="sel_{row_id}" data-cat="{cat}" data-wikidata="{r['wikidata_id']}">
                <option value="">--</option>
                <option value="correct">Correct</option>
                <option value="wrong_category">Wrong category</option>
                <option value="wrong_period">Wrong period</option>
                <option value="unclear">Unclear</option>
            </select>
            <input id="note_{row_id}" placeholder="note..." />
        </td>''')
        html_parts.append('</tr>')

    html_parts.append('</tbody></table></div>')

html_parts.append("""
<button id="export-btn" onclick="exportAnnotations()">Export annotations as JSON</button>
<pre id="export-output" style="display:none; background:#fff; padding:1rem; border:1px solid #ccc; margin-top:1rem; max-height:400px; overflow:auto;"></pre>
<script>
function exportAnnotations() {
    const selects = document.querySelectorAll('select[data-cat]');
    const results = [];
    selects.forEach(sel => {
        const id = sel.id.replace('sel_', '');
        const note = document.getElementById('note_' + id)?.value || '';
        if (sel.value || note) {
            results.push({
                wikidata_id: sel.dataset.wikidata,
                category: sel.dataset.cat,
                verdict: sel.value,
                note: note
            });
        }
    });
    const out = document.getElementById('export-output');
    out.style.display = 'block';
    out.textContent = JSON.stringify(results, null, 2);
}
</script>
</body></html>
""")

with open(OUT, 'w') as f:
    f.write('\n'.join(html_parts))

print(f'Wrote {OUT}')
for cat in ORDER:
    print(f'  {cat}: {len(samples[cat])} samples (of {len(buckets[cat]):,})')
