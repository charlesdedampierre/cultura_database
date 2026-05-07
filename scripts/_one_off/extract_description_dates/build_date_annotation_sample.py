"""Build a self-contained HTML annotation page for the description-date extractor.

Samples up to 100 individuals stratified by extracted-token KIND and ERA so the
reviewer sees ancient, medieval, early-modern, and modern figures across every
token type (range / birth / death / floruit / century / BC-AD marker).

Each row shows the description and the extracted token, with a Wikidata link.
The annotator marks Correct / Wrong / Partial; results persist to localStorage
and can be downloaded as JSON.

Output: scripts/_one_off/extract_description_dates/date_annotation.html
"""
from __future__ import annotations

import json
import random
import re
import sqlite3
from pathlib import Path

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")
OUT = Path(__file__).parent / "date_annotation.html"

TARGET_TOTAL = 100

# Token-classification regexes (apply to the FIRST '|'-separated token).
TOK_MARKER = re.compile(r"^\d+\s+(BC|BCE|AC|AD|CE)$")
TOK_RANGE = re.compile(r"^(\d{2,4})-(\d{2,4})$")
TOK_B = re.compile(r"^b\s+(\d{3,4})$")
TOK_D = re.compile(r"^d\s+(\d{3,4})$")
TOK_FL = re.compile(r"^fl\s+(\d{3,4})$")
TOK_CENT = re.compile(r"^c(\d{1,2})(?:\s+(BC|BCE|AC))?$")


def first_token(value: str) -> str:
    return value.split("|", 1)[0].strip()


def classify(value: str) -> tuple[str, int | None]:
    """Return (kind, signed-year-for-bucketing). None = un-classifiable."""
    tok = first_token(value)
    if (m := TOK_MARKER.match(tok)):
        y = int(tok.split()[0])
        return ("marker", -y if m.group(1) in {"BC", "BCE", "AC"} else y)
    if (m := TOK_RANGE.match(tok)):
        a, b = int(m.group(1)), int(m.group(2))
        return ("range", (a + b) // 2)
    if (m := TOK_B.match(tok)):
        return ("b", int(m.group(1)))
    if (m := TOK_D.match(tok)):
        return ("d", int(m.group(1)))
    if (m := TOK_FL.match(tok)):
        return ("fl", int(m.group(1)))
    if (m := TOK_CENT.match(tok)):
        n = int(m.group(1))
        midpoint = (n - 1) * 100 + 50
        return ("century", -midpoint if m.group(2) in {"BC", "BCE", "AC"} else midpoint)
    return ("other", None)


def era_bucket(year: int | None) -> str:
    if year is None:
        return "unknown"
    if year < 500:
        return "ancient"        # < 500 CE (incl. BCE)
    if year < 1500:
        return "medieval"       # 500-1499
    if year < 1900:
        return "early_modern"   # 1500-1899
    return "modern"             # 1900+


KINDS = ["range", "b", "d", "fl", "century", "marker"]
ERAS = ["ancient", "medieval", "early_modern", "modern"]


def main() -> None:
    rng = random.Random(20260504)
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    # Pull a generous candidate pool — enough to fill all (kind × era) cells.
    # We over-sample with `ORDER BY RANDOM()` then stratify in Python.
    # Restrict to people who currently have NO floruit_period — those are the ones
    # the description-extracted date would actually populate.
    rows = conn.execute(
        """
        SELECT i.wikidata_id, i.name_en, i.description_en, i.dates_in_description
        FROM individuals i
        JOIN individuals_floruit_period fp USING (wikidata_id)
        WHERE i.dates_in_description IS NOT NULL
          AND i.dates_in_description != ''
          AND i.description_en IS NOT NULL
          AND i.description_en != ''
          AND (fp.floruit_period IS NULL OR fp.floruit_period = '')
        ORDER BY RANDOM()
        LIMIT 50000
        """
    ).fetchall()
    conn.close()

    # Bucket candidates: cells[kind][era] = list[row]
    cells: dict[str, dict[str, list[sqlite3.Row]]] = {
        k: {e: [] for e in ERAS} for k in KINDS
    }
    for r in rows:
        kind, year = classify(r["dates_in_description"])
        if kind == "other":
            continue
        era = era_bucket(year)
        if kind in cells and era in cells[kind]:
            cells[kind][era].append(r)

    # Print cell counts so we know the inventory.
    print("inventory of candidate pool (first 50k random rows, stratified):")
    for k in KINDS:
        line = "  " + k.ljust(8) + " | "
        line += " ".join(f"{e}={len(cells[k][e]):>4}" for e in ERAS)
        print(line)

    # Allocation: for each non-empty (kind × era) cell take ceil(TARGET / N_cells).
    # Then trim/pad to hit TARGET_TOTAL exactly.
    nonempty_cells = [(k, e) for k in KINDS for e in ERAS if cells[k][e]]
    if not nonempty_cells:
        raise SystemExit("no candidates — check dates_in_description column")

    per_cell = max(1, TARGET_TOTAL // len(nonempty_cells))
    selected: list[dict] = []
    for k, e in nonempty_cells:
        pool = cells[k][e]
        rng.shuffle(pool)
        for r in pool[:per_cell]:
            selected.append({
                "wikidata_id": r["wikidata_id"],
                "name": r["name_en"] or "",
                "description": r["description_en"],
                "extracted": r["dates_in_description"],
                "kind": k,
                "era": e,
            })

    # If we under-shot TARGET_TOTAL, top up from the largest cells.
    chosen_ids = {x["wikidata_id"] for x in selected}
    if len(selected) < TARGET_TOTAL:
        flat = [r for k in KINDS for e in ERAS for r in cells[k][e]
                if r["wikidata_id"] not in chosen_ids]
        rng.shuffle(flat)
        for r in flat[: TARGET_TOTAL - len(selected)]:
            kind, year = classify(r["dates_in_description"])
            era = era_bucket(year)
            selected.append({
                "wikidata_id": r["wikidata_id"],
                "name": r["name_en"] or "",
                "description": r["description_en"],
                "extracted": r["dates_in_description"],
                "kind": kind,
                "era": era,
            })

    # If we over-shot, trim while preserving stratification balance.
    if len(selected) > TARGET_TOTAL:
        rng.shuffle(selected)
        selected = selected[:TARGET_TOTAL]

    # Sort for a stable display order: kind, era, then random within.
    kind_order = {k: i for i, k in enumerate(KINDS)}
    era_order = {e: i for i, e in enumerate(ERAS)}
    selected.sort(key=lambda r: (kind_order[r["kind"]], era_order.get(r["era"], 99)))
    print(f"\nselected {len(selected)} rows for annotation")

    html = build_html(selected)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT}")


def build_html(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False)
    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Date Extraction — Annotation</title>
<link rel="icon" href='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect width="16" height="16" rx="3" fill="%231f2937"/><text x="8" y="12" font-size="11" font-family="ui-monospace,monospace" text-anchor="middle" fill="white">D</text></svg>'>
<style>
  :root {
    --fg: #111827;
    --muted: #6b7280;
    --line: #e5e7eb;
    --bg: #fafaf9;
    --pill: #f3f4f6;
    --good: #16a34a;
    --bad:  #dc2626;
    --partial: #d97706;
  }
  * { box-sizing: border-box; }
  body {
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Inter", system-ui, sans-serif;
    color: var(--fg);
    background: var(--bg);
    margin: 0; padding: 0;
  }
  header {
    position: sticky; top: 0;
    background: white; border-bottom: 1px solid var(--line);
    padding: 14px 24px;
    display: flex; align-items: center; gap: 16px;
    z-index: 10;
  }
  header h1 { font-size: 16px; margin: 0; font-weight: 600; }
  header .progress { color: var(--muted); font-variant-numeric: tabular-nums; }
  header .actions { margin-left: auto; display: flex; gap: 8px; }
  header button {
    font: inherit; padding: 6px 12px; border-radius: 6px;
    border: 1px solid var(--line); background: white; cursor: pointer;
  }
  header button:hover { background: var(--pill); }
  main { max-width: 980px; margin: 0 auto; padding: 16px 24px 80px; }
  .row {
    background: white; border: 1px solid var(--line);
    border-radius: 8px; padding: 14px 16px; margin-bottom: 10px;
  }
  .row.done { opacity: 0.55; }
  .row .meta {
    display: flex; gap: 8px; flex-wrap: wrap; align-items: center;
    color: var(--muted); font-size: 12px; margin-bottom: 6px;
  }
  .pill {
    display: inline-block;
    padding: 2px 8px; border-radius: 999px;
    background: var(--pill); color: var(--fg);
    font-size: 11px; font-weight: 500;
    font-variant-numeric: tabular-nums;
  }
  .pill.kind     { background: #ecfeff; color: #0e7490; }
  .pill.era      { background: #fef3c7; color: #92400e; }
  .pill.id       { background: #f3f4f6; color: #374151; font-family: ui-monospace, monospace; }
  .desc { font-size: 14px; }
  .name { font-weight: 600; margin-right: 6px; }
  .extracted {
    margin-top: 8px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 13px;
    color: #1e293b;
    background: #f8fafc;
    padding: 6px 10px;
    border-radius: 6px;
    border: 1px solid var(--line);
  }
  .extracted .label { color: var(--muted); margin-right: 6px; }
  .controls { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }
  .controls button {
    font: inherit; padding: 4px 12px; border-radius: 6px;
    border: 1px solid var(--line); background: white; cursor: pointer;
    font-size: 13px;
  }
  .controls button:hover { background: var(--pill); }
  .controls button.active.correct { background: var(--good); color: white; border-color: var(--good); }
  .controls button.active.wrong   { background: var(--bad);  color: white; border-color: var(--bad); }
  .controls button.active.partial { background: var(--partial); color: white; border-color: var(--partial); }
  .controls .note {
    flex: 1 1 220px; font: inherit; padding: 4px 8px;
    border: 1px solid var(--line); border-radius: 6px; background: white;
    font-size: 13px; min-width: 200px;
  }
  a { color: #2563eb; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .summary {
    margin-top: 24px; padding: 12px 16px;
    background: white; border: 1px solid var(--line); border-radius: 8px;
    font-size: 13px; color: var(--muted);
    display: flex; gap: 16px; flex-wrap: wrap;
  }
  .summary span { display: inline-flex; align-items: center; gap: 6px; font-variant-numeric: tabular-nums; }
  .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .dot.correct { background: var(--good); }
  .dot.wrong   { background: var(--bad); }
  .dot.partial { background: var(--partial); }
</style>
</head>
<body>
<header>
  <h1>Date extraction — quick annotation</h1>
  <span class="progress" id="progress">0 / 0</span>
  <div class="actions">
    <button id="export">Download JSON</button>
    <button id="reset">Reset</button>
  </div>
</header>
<main>
  <div id="rows"></div>
  <div class="summary">
    <span><span class="dot correct"></span><span id="ct-correct">0</span> correct</span>
    <span><span class="dot partial"></span><span id="ct-partial">0</span> partial</span>
    <span><span class="dot wrong"></span><span id="ct-wrong">0</span> wrong</span>
    <span style="color: var(--muted)" id="ct-pending"></span>
  </div>
</main>
<script>
const ROWS = __PAYLOAD__;
const STORE_KEY = "date_annotation_v1";

function load() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); }
  catch (e) { return {}; }
}
function save(state) {
  localStorage.setItem(STORE_KEY, JSON.stringify(state));
}

const state = load();

function render() {
  const root = document.getElementById("rows");
  root.innerHTML = "";
  ROWS.forEach((r, idx) => {
    const a = state[r.wikidata_id] || {};
    const div = document.createElement("div");
    div.className = "row" + (a.verdict ? " done" : "");

    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `
      <span class="pill id">${idx + 1} / ${ROWS.length}</span>
      <span class="pill kind">${r.kind}</span>
      <span class="pill era">${r.era}</span>
      <a href="https://www.wikidata.org/wiki/${r.wikidata_id}" target="_blank" rel="noopener">${r.wikidata_id}</a>
    `;
    div.appendChild(meta);

    const desc = document.createElement("div");
    desc.className = "desc";
    desc.innerHTML = `<span class="name">${escapeHtml(r.name)}</span><span>${escapeHtml(r.description)}</span>`;
    div.appendChild(desc);

    const ex = document.createElement("div");
    ex.className = "extracted";
    ex.innerHTML = `<span class="label">extracted →</span>${escapeHtml(r.extracted)}`;
    div.appendChild(ex);

    const ctrls = document.createElement("div");
    ctrls.className = "controls";
    for (const v of ["correct", "partial", "wrong"]) {
      const btn = document.createElement("button");
      btn.textContent = v.charAt(0).toUpperCase() + v.slice(1);
      btn.className = (a.verdict === v) ? `active ${v}` : "";
      btn.onclick = () => {
        state[r.wikidata_id] = { ...(state[r.wikidata_id] || {}), verdict: v, ...r };
        save(state);
        render();
      };
      ctrls.appendChild(btn);
    }
    const note = document.createElement("input");
    note.className = "note";
    note.placeholder = "Optional note…";
    note.value = a.note || "";
    note.oninput = () => {
      state[r.wikidata_id] = { ...(state[r.wikidata_id] || {}), note: note.value, ...r };
      save(state);
      updateProgress();
    };
    ctrls.appendChild(note);
    div.appendChild(ctrls);

    root.appendChild(div);
  });
  updateProgress();
}

function updateProgress() {
  const decided = ROWS.filter(r => state[r.wikidata_id] && state[r.wikidata_id].verdict).length;
  document.getElementById("progress").textContent = `${decided} / ${ROWS.length}`;
  const counts = { correct: 0, partial: 0, wrong: 0 };
  for (const r of ROWS) {
    const v = state[r.wikidata_id]?.verdict;
    if (v && counts[v] !== undefined) counts[v]++;
  }
  document.getElementById("ct-correct").textContent = counts.correct;
  document.getElementById("ct-partial").textContent = counts.partial;
  document.getElementById("ct-wrong").textContent = counts.wrong;
  const pending = ROWS.length - decided;
  document.getElementById("ct-pending").textContent = pending ? `${pending} pending` : "all done ✓";
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  })[c]);
}

document.getElementById("export").onclick = () => {
  const out = ROWS.map((r, idx) => {
    const a = state[r.wikidata_id] || {};
    return {
      idx, wikidata_id: r.wikidata_id, name: r.name,
      description: r.description, extracted: r.extracted,
      kind: r.kind, era: r.era,
      verdict: a.verdict || null, note: a.note || ""
    };
  });
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = "date_annotation.json"; a.click();
  URL.revokeObjectURL(url);
};

document.getElementById("reset").onclick = () => {
  if (!confirm("Clear all annotations on this page?")) return;
  localStorage.removeItem(STORE_KEY);
  for (const k of Object.keys(state)) delete state[k];
  render();
};

render();
</script>
</body>
</html>""".replace("__PAYLOAD__", payload)


if __name__ == "__main__":
    main()
