"""Build annotations/interfaces/polity_window_review.html.

100 individuals from humans_clean_v2.duckdb (15 per productive-window rule, 10 with no
window), each shown as a field/value table: the dates and places that were used, the
productive window and the polity it produced, and why.

Usage: .venv/bin/python annotations/building_scripts/build_polity_window_review.py
"""

import html
import importlib.util
import sys
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "cultura" / "humans_clean_v2.duckdb"
OUT = ROOT / "annotations" / "interfaces" / "polity_window_review.html"
ENRICHMENT = ROOT / "scripts" / "database_enrichment"

PER_METHOD = 15
NO_WINDOW = 10
SEED = 42

sys.path.insert(0, str(ENRICHMENT))
spec = importlib.util.spec_from_file_location("peak", ENRICHMENT / "06_peak_productivity.py")
peak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(peak)
LOW, HIGH, MEASURED_ON = peak.productive_age()

LOCATION_ORDER = {
    "polygon": ("deathplace", "birthplace", "country_of_citizenship"),
    "url": ("country_of_citizenship", "deathplace", "birthplace"),
}


def sample_qids(con):
    methods = [m for (m,) in con.sql(
        "SELECT DISTINCT peak_productivity.assignation_method FROM individual_enriched "
        "WHERE peak_productivity IS NOT NULL ORDER BY 1").fetchall()]
    qids = []
    for method in tqdm(methods + [None], desc="sampling"):
        where = "peak_productivity IS NULL" if method is None else f"peak_productivity.assignation_method = '{method}'"
        n = NO_WINDOW if method is None else PER_METHOD
        qids += [q for (q,) in con.sql(
            f"SELECT qid FROM (SELECT entity.qid AS qid FROM individual_enriched WHERE {where}) "
            f"USING SAMPLE reservoir({n} ROWS) REPEATABLE ({SEED})").fetchall()]
    return qids


def load_people(con, qids):
    con.execute("CREATE TEMP TABLE picked AS SELECT unnest(?) AS qid", [qids])
    return con.sql("""
        SELECT i.entity, i.birth_date, i.death_date, i.floruit_date, i.works_period,
               len(i.work) AS n_works,
               list_transform(i.occupation, o -> o.entity.label_en) AS occupations,
               i.place_of_birth.entity.qid AS birthplace,
               i.place_of_death.entity.qid AS deathplace,
               list_transform(i.country_of_citizenship, c -> c.entity.qid) AS citizenship,
               list_filter(i.sitelink, s -> s.site_url = 'https://en.wikipedia.org')[1].url AS wiki_en,
               list_filter(i.sitelink, s -> s.site_url LIKE '%wikipedia.org')[1].url AS wiki_any,
               e.peak_productivity, e.polity, e.polity_count
        FROM individual i JOIN picked p ON i.entity.qid = p.qid
        JOIN individual_enriched e ON e.entity.qid = i.entity.qid
    """).pl().to_dicts()


def load_places(con, people):
    qids = set()
    for p in people:
        qids.update(q for q in [p["birthplace"], p["deathplace"], *(p["citizenship"] or [])] if q)
    rows = con.execute(
        "SELECT entity.qid, entity.label_en, coordinates.latitude, coordinates.longitude, sitelink.url "
        "FROM place WHERE entity.qid IN (SELECT unnest(?))", [list(qids)]).fetchall()
    return {q: {"label": fix_encoding(l), "lat": lat, "lon": lon, "url": u} for q, l, lat, lon, u in rows}


def fix_encoding(text):
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError, AttributeError):
        return text


def link(url, text=None):
    return f'<a href="{html.escape(url)}" target="_blank">{html.escape(text or url)}</a>' if url else "—"


def wd(qid):
    return link(f"https://www.wikidata.org/wiki/{qid}", qid) if qid else "—"


def date_list(entries):
    if not entries:
        return "—"
    return "<br>".join(f"{e['year']} <span class=m>({e['precision']}, {peak.source_of(e)})</span>" for e in entries)


def place_cell(qid, places):
    if not qid:
        return "—"
    p = places.get(qid, {})
    coords = f" <span class=m>({p['lat']:.2f}, {p['lon']:.2f})</span>" if p.get("lat") is not None else " <span class=m>(no coordinates)</span>"
    wiki = f" · {link(p['url'], 'article')}" if p.get("url") else ""
    return f"{html.escape(p.get('label') or '?')} {wd(qid)}{coords}{wiki}"


def used_dates(person):
    for label, precisions in peak.PRECISION_PRIORITY:
        birth = peak.preferred(person["birth_date"], precisions)
        death = peak.preferred(person["death_date"], precisions)
        floruit = peak.preferred(person["floruit_date"], precisions)
        for name in peak.RULES:
            if peak.IMPLEMENTATIONS[name](birth, death, floruit, person["works_period"], LOW, HIGH):
                return name, label, birth, death, floruit
    return None, None, None, None, None


def explain_window(person):
    w = person["peak_productivity"]
    if not w:
        return "No rule applied: no usable birth, death, floruit or dated work."
    rule, precision, birth, death, floruit = used_dates(person)
    works = person["works_period"] or {}
    span = HIGH - LOW
    text = {
        "floruit": f"Floruit {floruit and floruit.year} ({floruit and floruit.source}) placed within the age window {LOW}–{HIGH}"
                   + (f" from birth {birth.year}" if birth else f", extended forward by {span} years (no birth year)")
                   + (f", cut at death {death.year}" if death and death.year < w["end_year"] + 1 else ""),
        "works_span": f"First to last dated work: {works.get('first_year')}–{works.get('last_year')}.",
        "works_single": f"Single dated work year {works.get('first_year')}, extended forward by {span} years.",
        "birth_and_death": f"Birth {birth and birth.year} + {LOW} to birth + {HIGH}, cut at death {death and death.year} if earlier.",
        "birth_only": f"Birth {birth and birth.year} + {LOW} to birth + {HIGH} (no death year).",
        "death_only": f"Death {death and death.year} minus {span} years to death.",
    }.get(rule, "")
    order = " → ".join(peak.RULES)
    return (f"{text}<br><span class=m>Rule “{rule}” was the first to apply, using dates {precision}. "
            f"Rules tried in order: {order}. Age window {LOW}–{HIGH} = quartiles of age at Wikidata floruit "
            f"over {MEASURED_ON:,} individuals.</span>")


def explain_polity(person, places):
    matches = person["polity"] or []
    if not person["peak_productivity"]:
        return "No polity: without a productive window there is no period to test the places against."
    if not matches:
        return ("No polity: none of deathplace, birthplace or citizenship fell inside a Cliopatria polity "
                "during the window, and no Wikipedia article was shared with one.")
    method = matches[0]["assignation_method"]
    kind, location = method.split("_of_", 1)
    order = LOCATION_ORDER[kind]
    skipped = order[:order.index(location)]
    how = ("its coordinates fall inside the polity's territory" if kind == "polygon"
           else "its Wikipedia article is the polity's article")
    tried = f" Tried before without a match: {', '.join(skipped)}." if skipped else ""
    main = matches[0]["polity"]["name"]
    return (f"Settled by the <b>{location.replace('_', ' ')}</b>: {how} during the window.{tried} "
            f"Main polity = the one covering the most years of the window ({html.escape(main)}).<br>"
            "<span class=m>Order: polygons (deathplace → birthplace → citizenship), then Wikipedia article "
            "(citizenship → deathplace → birthplace); first location matching anything ends the search. "
            "All polities overlapping the window at that location are kept.</span>")


def polity_list(matches):
    if not matches:
        return "—"
    return "<br>".join(
        f"{html.escape(m['polity']['name'])} <span class=m>({m['years_spent_in_polity']} yrs in window, "
        f"{m['assignation_method']}{', ' + ', '.join(m['polity']['world']) if m['polity']['world'] else ''})</span>"
        for m in matches)


def card(i, p, places):
    e, w, matches = p["entity"], p["peak_productivity"], p["polity"] or []
    wiki = p["wiki_en"] or p["wiki_any"]
    works = p["works_period"] or {}
    rows = [
        ("Wikidata", wd(e["qid"])),
        ("Wikipedia", link(wiki)),
        ("Description", html.escape(fix_encoding(e["description"]) or "—")),
        ("Occupations", html.escape(", ".join(fix_encoding(o) for o in p["occupations"] or [] if o) or "—")),
        ("Birth date(s)", date_list(p["birth_date"])),
        ("Death date(s)", date_list(p["death_date"])),
        ("Floruit date(s)", date_list(p["floruit_date"])),
        ("Works period", f"{works.get('first_year')}–{works.get('last_year')} <span class=m>({p['n_works'] or 0} works)</span>" if works.get("first_year") is not None else f"— <span class=m>({p['n_works'] or 0} works)</span>"),
        ("Birthplace", place_cell(p["birthplace"], places)),
        ("Deathplace", place_cell(p["deathplace"], places)),
        ("Citizenship", "<br>".join(place_cell(q, places) for q in p["citizenship"] or []) or "—"),
        ("<b>Productive window</b>", f"<b>{w['start_year']}–{w['end_year']}</b> <span class=m>({w['assignation_method']})</span>" if w else "<b>none</b>"),
        ("How the window was found", explain_window(p)),
        ("<b>Polity of assignation</b>", f"<b>{html.escape(matches[0]['polity']['name'])}</b>" if matches else "<b>none</b>"),
        ("All polities matched", polity_list(matches)),
        ("How the polity was chosen", explain_polity(p, places)),
    ]
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<section><h2>{i}. {html.escape(fix_encoding(e['label_en']) or e['qid'])}</h2><table>{body}</table></section>"


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polity & Window Review</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><circle cx='8' cy='8' r='7' fill='%23333'/></svg>">
<style>
body{{font-family:-apple-system,system-ui,sans-serif;max-width:860px;margin:0 auto;padding:24px 16px;color:#222;background:#fff;line-height:1.45}}
h1{{font-size:22px;margin:0 0 4px}} p.intro{{color:#555;font-size:14px}}
section{{margin:28px 0;border-top:1px solid #ddd;padding-top:12px}} h2{{font-size:17px;margin:0 0 8px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;vertical-align:top;width:190px;padding:5px 10px 5px 0;color:#555;font-weight:500}}
td{{padding:5px 0;vertical-align:top;word-break:break-word}} tr{{border-bottom:1px solid #f0f0f0}}
.m{{color:#888;font-size:12.5px}} a{{color:#2a5db0;text-decoration:none}}
</style></head><body>
<h1>Polity of assignation & productive window — 100 individuals</h1>
<p class="intro">Source: <code>humans_clean_v2.duckdb</code>. Sample: {per} per productive-window rule + {none} with no window (seed {seed}).
Logic: <code>scripts/database_enrichment/06_peak_productivity.py</code> and <code>08_polity_assignment.py</code>.
Date sources in brackets: precision, source.</p>
{cards}
</body></html>"""


def main():
    con = duckdb.connect(str(DB), read_only=True)
    qids = sample_qids(con)
    print(f"loading {len(qids)} individuals (full scan of individual, ~1 min)")
    people = sorted(load_people(con, qids), key=lambda p: p["entity"]["label_en"] or "")
    places = load_places(con, people)
    cards = "\n".join(card(i, p, places) for i, p in enumerate(tqdm(people, desc="cards"), start=1))
    OUT.write_text(PAGE.format(per=PER_METHOD, none=NO_WINDOW, seed=SEED, cards=cards), encoding="utf-8")
    print(f"wrote {OUT} ({len(people)} individuals)")


if __name__ == "__main__":
    main()
