"""Build a 100-individual annotation sample as a self-contained HTML page.

Sampling is stratified by century so that ancient, medieval, early-modern,
and modern figures all appear — without this stratification a uniform
random draw would be ~95% post-1800 (where the data lives).

Strata (by floruit_year midpoint):
  - Antiquity            : year < 0
  - Late Antiquity       : 0   ≤ year < 500
  - Early Medieval       : 500 ≤ year < 1000
  - High/Late Medieval   : 1000 ≤ year < 1500
  - Early Modern         : 1500 ≤ year < 1800
  - 19th century         : 1800 ≤ year < 1900
  - 20th–21st century    : year ≥ 1900
Allocated equally across populated strata; remainder filled randomly.

For each sampled individual we show:
  - name, description, occupation, country of citizenship
  - assigned polity (semicolon-joined names)
  - the polity / place that produced the match (matched_name)
  - assigned floruit period (start..end)
  - matching method + origin
  - link to the Wikipedia page (English by default, else any wiki the
    individual happens to have)

The annotator marks each row Correct / Incorrect. If Incorrect, they pick
ONE failure reason from:
  1. Reliability of Wikidata information
  2. Reliability of Cliopatria boundaries
  3. Robustness of the rules designed to assign an individual to a polity
  4. Robustness of the rules designed to assign an individual to a floruit period
  5. Reliability of the matching procedure

Annotations are saved to a JSON download via a button at the bottom.
"""
from __future__ import annotations

import json
import random
import sqlite3
from html import escape
from pathlib import Path

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")
OUT = Path(__file__).with_suffix(".html")
N = 100
SEED = 20260503

PREFERRED_SITES = (
    "en.wikipedia.org",
    "fr.wikipedia.org",
    "de.wikipedia.org",
    "es.wikipedia.org",
    "it.wikipedia.org",
    "ru.wikipedia.org",
    "ar.wikipedia.org",
)

# (label, lower_inclusive, upper_exclusive); None = open
STRATA = [
    ("Antiquity (<0)",         None,  0),
    ("Late Antiquity (0–500)",     0, 500),
    ("Early Medieval (500–1000)",  500, 1000),
    ("Medieval (1000–1500)",       1000, 1500),
    ("Early Modern (1500–1800)",   1500, 1800),
    ("19th century (1800–1900)",   1800, 1900),
    ("20th–21st century (1900+)",  1900, None),
]


def clean_date(s: str | None) -> str:
    """Empty / blank-node 'somevalue' tokens render as '?'."""
    if not s:
        return ""
    s = s.strip()
    if not s or s.startswith("_:"):
        return "?"  # Wikidata 'somevalue' — date exists but is unknown
    return s


def pick_wiki_url(rows: list[tuple[str, str]]) -> tuple[str, str]:
    """rows = list of (site, url). Returns (site, url) preferring English."""
    by_site = {s: u for s, u in rows if u}
    for s in PREFERRED_SITES:
        if s in by_site:
            return s, by_site[s]
    if by_site:
        s = next(iter(by_site))
        return s, by_site[s]
    return "", ""


def stratum_predicate(lo: int | None, hi: int | None, col: str = "floruit_year") -> str:
    parts = []
    if lo is not None:
        parts.append(f"{col} >= {lo}")
    if hi is not None:
        parts.append(f"{col} <  {hi}")
    return " AND ".join(parts) if parts else "1=1"


def fetch_stratum(conn: sqlite3.Connection, lo: int | None, hi: int | None,
                  k: int, seed_offset: int) -> list[tuple]:
    """Pull k * 4 random rows from one stratum (over-sample for wiki-link drop)."""
    sql = f"""
        SELECT c.wikidata_id, c.name_en, c.polity_name, c.polity_id,
               c.origin, c.matched_name, c.method,
               c.floruit_period_start, c.floruit_period_end, c.floruit_year,
               i.description_en, i.occupations_en,
               i.country_of_citizenship_en, i.birthcity_en, i.deathcity_en,
               i.birthdate, i.deathdate, i.floruit_date
        FROM individuals_cliopatria c
        JOIN individuals i USING(wikidata_id)
        WHERE c.floruit_year IS NOT NULL
          AND {stratum_predicate(lo, hi, "c.floruit_year")}
        ORDER BY RANDOM()
        LIMIT ?
    """
    return conn.execute(sql, (k * 4,)).fetchall()


def main() -> None:
    rng = random.Random(SEED)
    per_stratum = N // len(STRATA)  # 100 // 7 = 14
    leftover = N - per_stratum * len(STRATA)  # 2 — given to the smallest strata

    with sqlite3.connect(DB) as conn:
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")

        # Allocate quotas (smallest strata get the leftover slots)
        strata_pop = []
        for label, lo, hi in STRATA:
            n = conn.execute(
                f"SELECT COUNT(*) FROM individuals_cliopatria "
                f"WHERE floruit_year IS NOT NULL AND {stratum_predicate(lo, hi)}"
            ).fetchone()[0]
            strata_pop.append((label, lo, hi, n))

        # Quotas: base per_stratum each; give leftovers to the strata with the
        # smallest populations (better century coverage)
        quotas = {label: per_stratum for label, _, _, _ in strata_pop}
        for label, *_ in sorted(strata_pop, key=lambda x: x[3])[:leftover]:
            quotas[label] += 1
        # Cap by population
        for label, _, _, n in strata_pop:
            quotas[label] = min(quotas[label], n)

        sample: list[dict] = []
        for offset, (label, lo, hi, pop) in enumerate(strata_pop):
            need = quotas[label]
            if need == 0:
                continue
            rows = fetch_stratum(conn, lo, hi, need, offset)
            ids = [r[0] for r in rows]
            placeholders = ",".join("?" for _ in ids) or "''"
            link_map: dict[str, list[tuple[str, str]]] = {}
            if ids:
                for wid, site, url in conn.execute(
                    f"SELECT wikidata_id, site, url FROM wikimedia_links "
                    f"WHERE wikidata_id IN ({placeholders}) "
                    f"AND site LIKE '%.wikipedia.org'",
                    ids,
                ).fetchall():
                    link_map.setdefault(wid, []).append((site, url))

            taken = 0
            for r in rows:
                wid = r[0]
                site, url = pick_wiki_url(link_map.get(wid, []))
                if not url:
                    continue
                sample.append({
                    "wid": wid,
                    "name": r[1] or "",
                    "polity": r[2] or "",
                    "polity_id": r[3] or "",
                    "origin": r[4] or "",
                    "matched": r[5] or "",
                    "method": r[6] or "",
                    "fp_start": r[7],
                    "fp_end": r[8],
                    "floruit_year": r[9],
                    "descr": r[10] or "",
                    "occupations": r[11] or "",
                    "coc": r[12] or "",
                    "birthcity": r[13] or "",
                    "deathcity": r[14] or "",
                    "birthdate": clean_date(r[15]),
                    "deathdate": clean_date(r[16]),
                    "floruit_date": clean_date(r[17]),
                    "wiki_site": site,
                    "wiki_url": url,
                    "stratum": label,
                })
                taken += 1
                if taken == need:
                    break
            print(f"  {label:30s}  pop={pop:>9}  quota={need:>3}  kept={taken}")

    rng.shuffle(sample)
    print(f"\nSampled {len(sample)} individuals → {OUT}")

    # Build HTML
    rows_html = []
    for i, s in enumerate(sample, 1):
        fp = (
            f"{s['fp_start']} … {s['fp_end']}"
            if s['fp_start'] is not None
            else "—"
        )
        wiki_lang = s['wiki_site'].split('.')[0].upper()
        # Compose Wikidata-date line: birth / death / floruit (only what's present)
    date_bits = []
    if s['birthdate']:
        date_bits.append(f"b. {escape(s['birthdate'])}")
    if s['deathdate']:
        date_bits.append(f"d. {escape(s['deathdate'])}")
    if s['floruit_date']:
        date_bits.append(f"fl. {escape(s['floruit_date'])}")
    wikidata_dates = " · ".join(date_bits) if date_bits else "<span class='muted'>none</span>"

    rows_html.append(f"""
<div class="card" id="card-{i}" data-wid="{escape(s['wid'])}" data-idx="{i}" data-stratum="{escape(s['stratum'])}">
  <div class="card-head">
    <span class="num">{i:03d} / {len(sample)}</span>
    <a class="name" href="{escape(s['wiki_url'])}" target="_blank" rel="noopener">{escape(s['name'])}</a>
    <span class="lang">{wiki_lang}</span>
    <span class="stratum">{escape(s['stratum'])}</span>
    <a class="qid" href="https://www.wikidata.org/wiki/{escape(s['wid'])}" target="_blank" rel="noopener">{escape(s['wid'])}</a>
  </div>
  <div class="descr">{escape(s['descr'])}</div>
  <div class="grid">
    <div><b>Assigned polity:</b> {escape(s['polity'])}</div>
    <div><b>Floruit (computed):</b> {fp}</div>
    <div><b>Polity (matched via):</b> {escape(s['matched'])}</div>
    <div><b>Method:</b> {escape(s['method'])} <span class="muted">({escape(s['origin'])})</span></div>
    <div class="full"><b>Wikidata dates:</b> {wikidata_dates}</div>
    <div><b>Citizenship:</b> {escape(s['coc'])}</div>
    <div><b>Birth / Death city:</b> {escape(s['birthcity'])} / {escape(s['deathcity'])}</div>
    <div class="full"><b>Occupations:</b> {escape(s['occupations'])}</div>
  </div>
  <div class="answer">
    <label class="opt"><input type="radio" name="ok-{i}" value="yes"> ✓ Correct</label>
    <label class="opt"><input type="radio" name="ok-{i}" value="no">  ✗ Incorrect</label>
    <select class="reason" name="reason-{i}" disabled>
      <option value="">— if Incorrect, pick the main reason —</option>
      <option value="wikidata">1. Reliability of Wikidata information</option>
      <option value="cliopatria">2. Reliability of Cliopatria boundaries</option>
      <option value="polity_rules">3. Robustness of the rules to assign a polity</option>
      <option value="floruit_rules">4. Robustness of the rules to assign a floruit period</option>
      <option value="matching">5. Reliability of the matching procedure</option>
    </select>
    <input type="text" class="note" name="note-{i}" placeholder="optional note">
  </div>
</div>""")

    head = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cliopatria — Annotation Sample (n=100)</title>
<link rel="icon" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%232b3a55'/><text x='8' y='12' font-family='monospace' font-size='10' fill='white' text-anchor='middle'>C</text></svg>">
<style>
  body { font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         margin: 0; background: #f6f7f9; color: #1d2330; }
  header { position: sticky; top: 0; background: #2b3a55; color: white;
           padding: 12px 24px; display: flex; align-items: center; gap: 16px;
           box-shadow: 0 2px 4px rgba(0,0,0,.15); z-index: 10; }
  header h1 { font-size: 16px; font-weight: 600; margin: 0; }
  header .progress { font-variant-numeric: tabular-nums; opacity: .85; }
  header button { margin-left: auto; padding: 6px 14px; border: 0; border-radius: 4px;
                  background: #f1c40f; color: #1d2330; font-weight: 600; cursor: pointer; }
  main { max-width: 880px; margin: 16px auto; padding: 0 16px 80px; }
  .card { background: white; border-radius: 8px; padding: 16px 20px; margin-bottom: 14px;
          border: 1px solid #e1e4ea; }
  .card.done-yes { border-left: 4px solid #27ae60; }
  .card.done-no  { border-left: 4px solid #c0392b; }
  .card-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 6px; }
  .num { color: #888; font-variant-numeric: tabular-nums; font-size: 12px; }
  .name { font-weight: 600; font-size: 16px; color: #2b3a55; text-decoration: none; }
  .name:hover { text-decoration: underline; }
  .lang { font-size: 10px; background: #eef0f4; color: #555; padding: 1px 6px; border-radius: 3px; }
  .stratum { font-size: 10px; background: #2b3a55; color: white; padding: 1px 6px; border-radius: 3px; }
  .qid  { margin-left: auto; font-size: 11px; color: #888; text-decoration: none; }
  .qid:hover { color: #2b3a55; }
  .descr { color: #555; font-style: italic; margin-bottom: 8px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 18px;
          font-size: 13px; padding: 8px 0 12px; border-top: 1px dashed #e1e4ea; border-bottom: 1px dashed #e1e4ea; }
  .grid .full { grid-column: 1 / -1; }
  .muted { color: #888; }
  .answer { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; padding-top: 10px; }
  .opt { cursor: pointer; user-select: none; }
  .reason { padding: 5px 8px; border: 1px solid #ccd0d8; border-radius: 4px; font: inherit; max-width: 360px; }
  .reason:disabled { opacity: .5; }
  .note   { padding: 5px 8px; border: 1px solid #ccd0d8; border-radius: 4px; font: inherit; flex: 1; min-width: 200px; }
</style>
</head>
<body>
<header>
  <h1>Cliopatria — Annotation sample</h1>
  <span class="progress" id="progress">0 / 100 annotated</span>
  <button id="export">⇩  Download annotations.json</button>
</header>
<main>
"""
    foot = """
</main>
<script>
const N = document.querySelectorAll('.card').length;
const progressEl = document.getElementById('progress');

function refresh() {
  let done = 0;
  document.querySelectorAll('.card').forEach(card => {
    const idx = card.dataset.idx;
    const ok = card.querySelector(`input[name="ok-${idx}"]:checked`);
    const reason = card.querySelector(`select[name="reason-${idx}"]`);
    card.classList.remove('done-yes', 'done-no');
    if (ok) {
      card.classList.add(ok.value === 'yes' ? 'done-yes' : 'done-no');
      reason.disabled = (ok.value !== 'no');
      if (ok.value === 'yes') reason.value = '';
      done += 1;
    } else {
      reason.disabled = true;
    }
  });
  progressEl.textContent = `${done} / ${N} annotated`;
}

document.querySelectorAll('input[type="radio"]').forEach(r => r.addEventListener('change', refresh));

document.getElementById('export').addEventListener('click', () => {
  const out = [];
  document.querySelectorAll('.card').forEach(card => {
    const idx = card.dataset.idx;
    const ok = card.querySelector(`input[name="ok-${idx}"]:checked`);
    const reason = card.querySelector(`select[name="reason-${idx}"]`).value;
    const note = card.querySelector(`input[name="note-${idx}"]`).value;
    out.push({
      idx: parseInt(idx, 10),
      wikidata_id: card.dataset.wid,
      stratum: card.dataset.stratum,
      verdict: ok ? ok.value : null,
      reason: reason || null,
      note: note || null
    });
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'cliopatria_annotations.json';
  a.click();
});

refresh();
</script>
</body>
</html>
"""
    OUT.write_text(head + "\n".join(rows_html) + foot, encoding="utf-8")
    print(f"Open: file://{OUT}")


if __name__ == "__main__":
    main()
