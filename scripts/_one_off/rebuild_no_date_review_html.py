"""Rebuild the no-date review HTML from a saved extraction CSV (no LLM calls)."""
import csv
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Pull the HTML template + extract-fetcher straight from the live script
from test_extract_dates_from_wikipedia_no_date import HTML, fetch_wikipedia_extract  # noqa: E402

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
csv_candidates = sorted(SCRIPTS_DIR.glob("no_date_extraction_test_*.csv"))
if not csv_candidates:
    raise SystemExit("no no_date_extraction_test_*.csv found under scripts/")
CSV_PATH  = csv_candidates[-1]  # most recent run
HTML_PATH = PROJECT_ROOT / "annotations" / "no_date_extraction_review.html"

# Lift lead extracts from any existing review HTML so we don't re-fetch them.
# Prefer the fixed-name file, otherwise fall back to the most recent timestamped one.
ANNOTATION_DIR = PROJECT_ROOT / "annotations"
candidates = ([HTML_PATH] if HTML_PATH.exists() else []) + sorted(
    ANNOTATION_DIR.glob("no_date_extraction_review_*.html")
)
lead_by_qid: dict[str, str] = {}
for p in reversed(candidates):
    m = re.search(r"const DATA = (\[.*?\]);", p.read_text(encoding="utf-8"), re.DOTALL)
    if not m:
        continue
    for c in json.loads(m.group(1)):
        lead_by_qid.setdefault(c["wikidata_id"], c.get("lead_extract", ""))
    if lead_by_qid:
        break

cards = []
with CSV_PATH.open() as f:
    for r in csv.DictReader(f):
        def parse_int(v):
            try: return int(v) if v not in ("", "None", "null") else None
            except (ValueError, TypeError): return None

        try:
            other = json.loads(r.get("other_dates_json") or "[]")
        except json.JSONDecodeError:
            other = []
        cards.append({
            "wikidata_id": r["wikidata_id"],
            "name":        r.get("name") or "",
            "description": r.get("description") or "",
            "country":     r.get("country") or "",
            "occupations": r.get("occupations") or "",
            "wp_lang":     r.get("wp_lang") or "",
            "wp_url":      r.get("wp_url") or "",
            "lead_extract": lead_by_qid.get(r["wikidata_id"], ""),
            "birthdate":            parse_int(r.get("birthdate")) if (r.get("birthdate") or "").lstrip("-").isdigit() else (r.get("birthdate") or None),
            "birthdate_precision":  r.get("birthdate_precision") or None,
            "deathdate":            parse_int(r.get("deathdate")) if (r.get("deathdate") or "").lstrip("-").isdigit() else (r.get("deathdate") or None),
            "deathdate_precision":  r.get("deathdate_precision") or None,
            "floruit_period_start": parse_int(r.get("floruit_period_start")),
            "floruit_period_end":   parse_int(r.get("floruit_period_end")),
            "floruit_precision":    r.get("floruit_precision") or None,
            "other_dates":          other if isinstance(other, list) else [],
            "reasoning":            r.get("reasoning") or "",
        })

html = HTML.format(
    N=len(cards),
    MODEL="google/gemini-2.5-flash-lite",
    SEED=42,
    DATA_JSON=json.dumps(cards, ensure_ascii=False),
)
HTML_PATH.write_text(html, encoding="utf-8")
print(f"Rebuilt {HTML_PATH} with {len(cards)} cards "
      f"({sum(1 for c in cards if c['reasoning'])} with reasoning).")
