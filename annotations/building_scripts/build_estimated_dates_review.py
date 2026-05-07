"""Build annotations/estimated_dates_review.html.

Quick QA tool to sanity-check the life-expectancy-based birthdate /
deathdate estimates written to `individuals` by
`scripts/_one_off/add_estimated_dates_from_life_expectancy.py`.

Stratified sample across the 5 CV `level1_main_occ` categories that drove
the cascade lookup, plus a 6th "not-in-CV" bucket (estimates that fell
through to period-only or global lookup). Within each bucket we balance
birth-only-known vs death-only-known cases so both directions of the
estimate get reviewed.

Outputs a single self-contained HTML file the user opens in a browser to
mark each row Yes/No and download the annotations as JSON.

Usage: python annotations/build_estimated_dates_review.py
"""

import json
import random
import sqlite3
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "humans_clean.sqlite3"
CV_PATH = (
    ROOT
    / "data"
    / "similar_databases"
    / "cross-verified-database"
    / "cross-verified-database.utf8.csv.gz"
)
OUT = ROOT / "annotations" / "interfaces" / "estimated_dates_review.html"

PER_CATEGORY = 12  # rows per bucket; ~half birth-est, ~half death-est
SEED = 42
random.seed(SEED)

# (bucket_id, label) — bucket assignment is computed in Python after the join
CV_CATEGORIES = ["Culture", "Sports/Games", "Leadership", "Discovery/Science", "Other"]
BUCKETS = [(c, c) for c in CV_CATEGORIES] + [
    ("not_in_cv", "Not in CV (period/global cascade)")
]


def fetch_candidates() -> pl.DataFrame:
    """Pull every individual with at least one estimated date and a name,
    plus enough context columns to render the card. Then attach CV category."""
    print("Loading individuals with estimated dates...")
    conn = sqlite3.connect(DB)
    ind = pl.read_database(
        """
        SELECT wikidata_id,
               name_en,
               description_en,
               occupations_en,
               country_of_citizenship_en,
               gender,
               birthdate,
               birthdate_precision,
               deathdate,
               deathdate_precision,
               estimated_birthdate_from_life_expectancy,
               estimated_deathdate_from_life_expectancy,
               cross_verified_db,
               wikimedia_links_count
        FROM individuals
        WHERE (estimated_birthdate_from_life_expectancy IS NOT NULL
               OR estimated_deathdate_from_life_expectancy IS NOT NULL)
          AND name_en IS NOT NULL AND name_en != ''
          AND wikimedia_links_count >= 1
        """,
        conn,
    )
    conn.close()
    print(f"  {ind.height:,} candidate rows (estimated + has name + wikimedia link)")

    print("Loading CV level1_main_occ...")
    cv = (
        pl.read_csv(
            CV_PATH,
            columns=["wikidata_code", "level1_main_occ"],
            schema_overrides={"wikidata_code": pl.Utf8, "level1_main_occ": pl.Utf8},
        )
        .drop_nulls(["wikidata_code", "level1_main_occ"])
        .filter(pl.col("level1_main_occ") != "Missing")
        .rename({"wikidata_code": "wikidata_id"})
        .unique(subset=["wikidata_id"])
    )
    print(f"  {cv.height:,} CV rows with category")

    df = ind.join(cv, on="wikidata_id", how="left").with_columns(
        pl.coalesce(pl.col("level1_main_occ"), pl.lit("not_in_cv")).alias("bucket")
    )
    df = df.with_columns(
        pl.when(pl.col("estimated_birthdate_from_life_expectancy").is_not_null())
        .then(pl.lit("birth"))
        .otherwise(pl.lit("death"))
        .alias("est_kind"),
    )
    return df


def stratified_sample(df: pl.DataFrame) -> list[dict]:
    rows = []
    for bucket_id, label in BUCKETS:
        sub = df.filter(pl.col("bucket") == bucket_id)
        # split birth-vs-death estimates roughly evenly
        birth = sub.filter(pl.col("est_kind") == "birth").sample(
            n=min(PER_CATEGORY // 2, sub.filter(pl.col("est_kind") == "birth").height),
            seed=SEED,
        )
        death = sub.filter(pl.col("est_kind") == "death").sample(
            n=min(
                PER_CATEGORY - birth.height,
                sub.filter(pl.col("est_kind") == "death").height,
            ),
            seed=SEED,
        )
        picked = pl.concat([birth, death])
        for r in picked.to_dicts():
            r["bucket_label"] = label
            rows.append(r)
        print(
            f"  {bucket_id:18s} {picked.height:3d} rows "
            f"(birth-est {birth.height}, death-est {death.height})"
        )
    random.shuffle(rows)  # mix order to avoid bucket-clustered bias
    return rows


PRECISION_NAME = {
    11: "day",
    10: "month",
    9: "year",
    8: "decade",
    7: "century",
    6: "millennium",
    5: "10k years",
}


def precision_str(p):
    if p is None:
        return ""
    return PRECISION_NAME.get(int(p), f"prec={p}")


def _year_from_iso(s):
    if not s:
        return None
    try:
        if s.startswith("-"):
            return -int(s[1:].split("-", 1)[0])
        return int(s.split("-", 1)[0])
    except Exception:
        return None


def to_card(d: dict) -> dict:
    real_b = (
        d.get("birthdate")
        if d.get("birthdate") and not str(d.get("birthdate", "")).startswith("_:")
        else None
    )
    real_d = (
        d.get("deathdate")
        if d.get("deathdate") and not str(d.get("deathdate", "")).startswith("_:")
        else None
    )
    est_b = d.get("estimated_birthdate_from_life_expectancy")
    est_d = d.get("estimated_deathdate_from_life_expectancy")

    eff_b_year = _year_from_iso(real_b) if real_b else _year_from_iso(est_b)
    eff_d_year = _year_from_iso(real_d) if real_d else _year_from_iso(est_d)
    longevity = (
        (eff_d_year - eff_b_year)
        if (eff_b_year is not None and eff_d_year is not None)
        else None
    )

    return {
        "wikidata_id": d["wikidata_id"],
        "name": d.get("name_en") or "",
        "description": d.get("description_en") or "",
        "occupations": d.get("occupations_en") or "",
        "nationality": d.get("country_of_citizenship_en") or "",
        "gender": d.get("gender") or "",
        "real_birth": real_b,
        "real_birth_prec": precision_str(d.get("birthdate_precision")),
        "real_death": real_d,
        "real_death_prec": precision_str(d.get("deathdate_precision")),
        "est_birth": est_b,
        "est_death": est_d,
        "est_kind": d.get("est_kind"),
        "longevity": longevity,
        "bucket": d.get("bucket"),
        "bucket_label": d.get("bucket_label"),
        "in_cv": int(d.get("cross_verified_db") or 0),
    }


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Estimated dates review &mdash; {N} individuals</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='6' fill='none' stroke='%232b6cb0' stroke-width='1.5'/%3E%3Cpath d='M8 4v4l2.5 2.5' stroke='%232b6cb0' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
  :root {{
    --bg:#fafafa; --card:#fff; --line:#e5e5e5; --ink:#1a1a1a; --muted:#666;
    --ok:#0f9d58; --bad:#d93025; --hl:#2b6cb0; --warn:#b76e00;
    --est-bg:#fff8e6; --est-line:#f1d68a;
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
    display:grid; grid-template-columns: 42px 1fr 320px 220px; gap:14px; align-items:start;
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
  .bucket-Culture            {{ background:#fde2e7; color:#a01231; }}
  .bucket-Sports\\/Games      {{ background:#e3f2dc; color:#256025; }}
  .bucket-Leadership         {{ background:#dde6f8; color:#1d3a8a; }}
  .bucket-Discovery\\/Science {{ background:#fff5cf; color:#7a5b00; }}
  .bucket-Other              {{ background:#ecdcf3; color:#4d1372; }}
  .bucket-not_in_cv          {{ background:#eee; color:#444; border:1px dashed #bbb; }}
  .dates {{
    display:grid; grid-template-columns:auto 1fr; column-gap:10px; row-gap:4px;
    font-size:12.8px; line-height:1.4;
  }}
  .dates .k {{ color:var(--muted); }}
  .dates .v {{ font-variant-numeric: tabular-nums; }}
  .est-row {{
    background:var(--est-bg); border:1px solid var(--est-line);
    border-radius:6px; padding:4px 8px; margin-top:6px;
    display:flex; align-items:baseline; gap:8px;
    font-variant-numeric: tabular-nums;
  }}
  .est-row .lbl {{ color:var(--warn); font-weight:700; font-size:11px; text-transform:uppercase; letter-spacing:0.4px; }}
  .est-row .val {{ font-size:14px; font-weight:700; color:var(--warn); }}
  .longevity {{ margin-top:6px; font-size:12px; color:var(--muted); }}
  .longevity b {{ color:var(--ink); font-variant-numeric: tabular-nums; }}
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
  <h1>Estimated dates review</h1>
  <span class="meta">{N} rows &middot; 6 buckets (5 CV categories + not-in-CV) &middot; stratified random sample</span>
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
const STORAGE_KEY = 'estimated_dates_review_v1';

const BUCKET_IDS = {BUCKETS_JSON};

const state = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
const activeBuckets = new Set(BUCKET_IDS.map(b => b[0]));

function fmt(v) {{
  if (v === null || v === undefined || v === '') return '—';
  return String(v);
}}

function bucketCssClass(id) {{
  return 'bucket-' + id.replace(/\\//g, '\\\\/');
}}

function render() {{
  const main = document.getElementById('rows');
  main.innerHTML = '';
  let yes = 0, no = 0, unsure = 0, pending = 0;

  DATA.forEach((d, i) => {{
    if (!activeBuckets.has(d.bucket)) return;
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

    const occ = d.occupations ? d.occupations.split(';').slice(0, 3).join(' · ') : '';
    const nat = d.nationality ? d.nationality.split(';').slice(0, 2).join(' · ') : '';

    const realBirthLine = d.real_birth
      ? `<span class="k">Birth (real):</span><span class="v">${{d.real_birth}}${{d.real_birth_prec ? ' (' + d.real_birth_prec + ')' : ''}}</span>`
      : '';
    const realDeathLine = d.real_death
      ? `<span class="k">Death (real):</span><span class="v">${{d.real_death}}${{d.real_death_prec ? ' (' + d.real_death_prec + ')' : ''}}</span>`
      : '';

    const estLine = d.est_kind === 'birth'
      ? `<div class="est-row"><span class="lbl">Birth estimated</span><span class="val">${{d.est_birth || ''}}</span></div>`
      : `<div class="est-row"><span class="lbl">Death estimated</span><span class="val">${{d.est_death || ''}}</span></div>`;

    const longLine = d.longevity != null
      ? `<div class="longevity">Implied lifespan: <b>${{d.longevity}}</b> yr</div>` : '';

    const bucketClass = `bucket-${{d.bucket.replace(/[^A-Za-z_]/g, '_')}}`;

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
          ${{d.gender ? `<span class="chip">${{d.gender}}</span>` : ''}}
          <span class="chip">${{d.wikidata_id}}</span>
          ${{d.in_cv ? '<span class="chip" style="color:#1d3a8a;border-color:#bcd;">in CV</span>' : ''}}
        </div>
        <div class="links" style="margin-top:6px;">
          <a href="https://www.wikidata.org/wiki/${{d.wikidata_id}}" target="_blank">Wikidata</a>
          <a href="https://en.wikipedia.org/wiki/Special:Search/${{encodeURIComponent(d.name || d.wikidata_id)}}" target="_blank">Wikipedia search</a>
          <a href="https://www.google.com/search?q=${{encodeURIComponent((d.name || '') + ' ' + (d.description || ''))}}" target="_blank">Google</a>
        </div>
      </div>
      <div>
        <div class="dates">
          ${{realBirthLine}}
          ${{realDeathLine}}
        </div>
        ${{estLine}}
        ${{longLine}}
        <div style="margin-top:8px;">
          <span class="${{bucketClass}} bucket-chip">${{d.bucket_label}}</span>
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
  BUCKET_IDS.forEach(([id, label]) => {{
    const lab = document.createElement('label');
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    cb.addEventListener('change', () => {{
      if (cb.checked) activeBuckets.add(id);
      else activeBuckets.delete(id);
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
    bucket: d.bucket,
    bucket_label: d.bucket_label,
    est_kind: d.est_kind,
    real_birth: d.real_birth,
    real_death: d.real_death,
    est_birth: d.est_birth,
    est_death: d.est_death,
    longevity: d.longevity,
    in_cv: d.in_cv,
    verdict: state[d.wikidata_id]?.verdict || null,
    note:    state[d.wikidata_id]?.note    || '',
  }}));
  const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: 'application/json' }});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'estimated_dates_annotations.json';
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


def main():
    df = fetch_candidates()
    rows = stratified_sample(df)
    cards = [to_card(r) for r in rows]
    html = HTML_TEMPLATE.format(
        N=len(cards),
        DATA_JSON=json.dumps(cards, ensure_ascii=False),
        BUCKETS_JSON=json.dumps(BUCKETS, ensure_ascii=False),
    )
    OUT.write_text(html, encoding="utf-8")
    print(f"\nWrote {len(cards)} rows -> {OUT}")


if __name__ == "__main__":
    main()
