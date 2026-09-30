"""Build annotations/interfaces/polity_window_review.html.

100 individuals from humans_clean_v2.duckdb, the only input. 92 have a productive window and
are spread over period x region cells (round-robin, so rare cells come first); 8 have none.
Each is shown as a field/value table: the dates and places used, the productive window and
the polity it produced, and why.

Usage: .venv/bin/python annotations/building_scripts/build_polity_window_review.py
"""

import html
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "cultura" / "humans_clean_v2.duckdb"
OUT = ROOT / "annotations" / "interfaces" / "polity_window_review.html"

WITH_WINDOW = 92
NO_WINDOW = 8
SEED = 42

RULES = ("floruit", "works_span", "works_single", "birth_death", "birth_only", "death_only")

LOCATION_ORDER = {
    "polygon": ("deathplace", "birthplace", "country_of_citizenship"),
    "url": ("country_of_citizenship", "deathplace", "birthplace"),
}

PERIOD = """CASE WHEN s < 500 THEN 'before 500' WHEN s < 1000 THEN '500-1000' WHEN s < 1500 THEN '1000-1500'
    WHEN s < 1800 THEN '1500-1800' WHEN s < 1900 THEN '1800-1900' ELSE 'after 1900' END"""

REGION = """CASE WHEN lon IS NULL THEN 'unknown location'
    WHEN lon < -30 THEN 'Americas'
    WHEN lat < -10 AND lon > 110 THEN 'Oceania'
    WHEN lat < 12 AND lon < 55 THEN 'Sub-Saharan Africa'
    WHEN lat >= 35 AND lon < 45 THEN 'Europe'
    WHEN lon < 65 THEN 'Middle East & North Africa'
    WHEN lon < 95 THEN 'South & Central Asia'
    ELSE 'East & Southeast Asia' END"""


def sample_qids(con):
    rows = con.sql(f"""
        WITH base AS (
            SELECT individual_enriched.entity.qid AS qid, individual_enriched.peak_productivity.start_year AS s,
                   coalesce(death_place.coordinates, birth_place.coordinates, citizenship_place.coordinates).latitude AS lat,
                   coalesce(death_place.coordinates, birth_place.coordinates, citizenship_place.coordinates).longitude AS lon
            FROM individual_enriched JOIN individual ON individual.entity.qid = individual_enriched.entity.qid
            LEFT JOIN place AS death_place ON death_place.entity.qid = individual.place_of_death.entity.qid
            LEFT JOIN place AS birth_place ON birth_place.entity.qid = individual.place_of_birth.entity.qid
            LEFT JOIN place AS citizenship_place ON citizenship_place.entity.qid = individual.country_of_citizenship[1].entity.qid
            WHERE individual_enriched.peak_productivity IS NOT NULL),
        cells AS (SELECT qid, {PERIOD} AS period, {REGION} AS region FROM base),
        ranked AS (SELECT *, row_number() OVER (PARTITION BY period, region ORDER BY hash(qid || '{SEED}')) AS rn FROM cells)
        SELECT qid, period, region FROM ranked ORDER BY rn, hash(qid || '{SEED}') LIMIT {WITH_WINDOW}
    """).fetchall()
    cell = {q: (period, region) for q, period, region in rows}
    for (q,) in con.sql(f"""
            SELECT entity.qid FROM individual_enriched WHERE peak_productivity IS NULL
            ORDER BY hash(entity.qid || '{SEED}') LIMIT {NO_WINDOW}""").fetchall():
        cell[q] = ("no window", "-")
    return cell


def as_dict(value):
    if isinstance(value, list):
        return {pair["key"]: pair["value"] for pair in value}
    return value or {}


def source_of(entry):
    provenance = as_dict(entry.get("field_provenance")).get("year") or {}
    rule_text = (provenance.get("rule") or "").lower()
    if (provenance.get("ai_answer") or {}).get("prompt_id") == "wikipedia_dates":
        return "wikipedia_article"
    if "CrossVerified" in " ".join(provenance.get("raw") or ()):
        return "cross_verified_database"
    if "life expectancy" in rule_text:
        return "life_expectancy_estimate"
    if "description" in rule_text:
        return "wikidata_entity_description"
    return "wikidata_property"


def used_year(entries, source):
    found = [e for e in entries or () if e.get("year") is not None and source_of(e) == source]
    found.sort(key=lambda e: e["precision"] not in ("day", "month", "year"))
    return found[0]["year"] if found else None


def load_people(con, qids):
    con.execute("CREATE TEMP TABLE picked AS SELECT unnest(?) AS qid", [qids])
    return con.sql("""
        SELECT individual.entity, individual.birth_date, individual.death_date, individual.floruit_date,
               individual.works_period, len(individual.work) AS n_works,
               list_transform(individual.occupation, job -> job.entity.label_en) AS occupations,
               individual.place_of_birth.entity.qid AS birthplace,
               individual.place_of_death.entity.qid AS deathplace,
               list_transform(individual.country_of_citizenship, country -> country.entity.qid) AS citizenship,
               list_filter(individual.sitelink, link -> link.site_url = 'https://en.wikipedia.org')[1].url AS wiki_en,
               list_filter(individual.sitelink, link -> link.site_url LIKE '%wikipedia.org')[1].url AS wiki_any,
               individual_enriched.peak_productivity, individual_enriched.cohort_age_stats,
               individual_enriched.polity, individual_enriched.polity_count
        FROM individual JOIN picked ON individual.entity.qid = picked.qid
        JOIN individual_enriched ON individual_enriched.entity.qid = individual.entity.qid
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
    return "<br>".join(f"{e['year']} <span class=m>({e['precision']}, {source_of(e)})</span>" for e in entries)


def place_cell(qid, places):
    if not qid:
        return "—"
    p = places.get(qid, {})
    coords = f" <span class=m>({p['lat']:.2f}, {p['lon']:.2f})</span>" if p.get("lat") is not None else " <span class=m>(no coordinates)</span>"
    wiki = f" · {link(p['url'], 'article')}" if p.get("url") else ""
    return f"{html.escape(p.get('label') or '?')} {wd(qid)}{coords}{wiki}"


def explain_window(person):
    w = person["peak_productivity"]
    if not w:
        return "No rule applied: no usable birth, death or floruit date and no dated work."
    method, start, end = w["assignation_method"], w["start_year"], w["end_year"]
    rule = next(r for r in RULES if method.startswith(r))
    source = method[len(rule) + 1:]
    birth = used_year(person["birth_date"], source)
    death = used_year(person["death_date"], source)
    works = person["works_period"] or {}
    ages = f"age {start - birth} to {end - birth}" if birth is not None else ""
    if rule == "floruit":
        floruit = used_year(person["floruit_date"], source)
        text = (f"Floruit {floruit} ({source}), born {birth}: window placed at {ages} around it." if birth is not None
                else f"Floruit {floruit} ({source}), no birth year: window runs {end - start} years from it.")
    elif rule == "works_span":
        text = f"First to last dated work: {works.get('first_year')}–{works.get('last_year')}."
    elif rule == "works_single":
        text = f"Only one dated work year ({works.get('first_year')}), extended forward by {end - start} years."
    elif rule == "birth_death":
        cut = f", cut at death {death}" if death == end else ""
        text = f"Born {birth}, died {death} ({source}): window = {ages}{cut}."
    elif rule == "birth_only":
        text = f"Born {birth} ({source}), no death year: window = {ages}."
    else:
        text = f"Died {death} ({source}), no year-precise birth year: window runs back {end - start} years from death."
    return (f"{text}<br><span class=m>Rule “{rule}” was the first that applied. Rules are tried in order "
            f"{' → '.join(RULES)}, year-precise dates before coarser ones; the first that yields a window wins.</span>")


def quartiles(stats, unit):
    return f"{stats['low']:g} / {stats['median']:g} / {stats['high']:g} {unit} <span class=m>(low / median / high quartile)</span>"


def cohort_rows(person):
    cohort, w = person["cohort_age_stats"], person["peak_productivity"]
    if not cohort:
        return [("Cohort", "none — no birth year, and no floruit, work or death to estimate one from")]
    rule = next((r for r in RULES if w and w["assignation_method"].startswith(r)), None)
    dates = [e for key in ("birth_date", "death_date") for e in person[key] or ()]
    uses_life = any(source_of(e) == "life_expectancy_estimate" for e in dates)
    window = cohort["productivity_window_from_wikidata_floruit"]
    low, high = round(window["low"]), round(window["high"])
    how_window = {
        None: "no — no rule produced a window",
        "works_span": "no — the window is the actual span of dated works",
        "floruit": f"yes — floruit placed within ages {low}–{high}",
        "works_single": f"yes — single work year extended by {high - low} years ({high} − {low})",
        "birth_death": f"yes — birth + {low} to birth + {high}",
        "birth_only": f"yes — birth + {low} to birth + {high}",
        "death_only": f"yes — death minus {high - low} years ({high} − {low})",
    }[rule]
    occupation = cohort["cv_occupation"]
    why_occ = ("cross-verified occupation of the individual" if occupation != "All"
               else "individual's occupation is Other, missing or absent from the cross-verified database")
    date_range = cohort["date_range"]
    has_birth = any(date_range["start_year"] <= (e.get("year") or 0) <= date_range["end_year"] for e in person["birth_date"] or ())
    why_year = ("birth year" if has_birth
                else "estimated birth year = floruit, first work or death minus the typical age at floruit (no year-precise birth)")
    return [
        ("Cohort", f"{occupation} · born {date_range['start_year']}–{date_range['end_year']}"
                   f"<br><span class=m>Occupation: {why_occ}. 50-year cohort from the {why_year}.</span>"),
        ("Productivity window (cohort)", quartiles(window, "years of age") + "<br><span class=m>Age at Wikidata floruit in this cohort.</span>"),
        ("<b>Productivity cohort used?</b>", how_window),
        ("Life expectancy (cohort)", quartiles(cohort["life_expectancy_from_wikidata_birth_death"], "years") + "<br><span class=m>Age at death from Wikidata birth and death in this cohort.</span>"),
        ("<b>Life expectancy used?</b>", "yes — a birth or death date was estimated from it" if uses_life
         else "no — all birth and death dates are stated (Wikidata or Wikipedia), none estimated from life expectancy"),
    ]


def explain_polity(person, places):
    matches = person["polity"] or []
    if not person["peak_productivity"]:
        return "No polity: without a productive window there is no period to test the places against."
    present = {"deathplace": person["deathplace"], "birthplace": person["birthplace"],
               "country_of_citizenship": person["citizenship"]}
    if not matches and not any(present.values()):
        return "No polity: the individual has no birthplace, deathplace or country of citizenship."
    if not matches:
        return ("No polity: none of deathplace, birthplace or citizenship fell inside a Cliopatria polity "
                "during the window, and no Wikipedia article was shared with one.")
    method = matches[0]["assignation_method"]
    kind, location = method.split("_of_", 1)
    order = LOCATION_ORDER[kind]
    skipped = order[:order.index(location)]
    how = ("its coordinates fall inside the polity's territory" if kind == "polygon"
           else "its Wikipedia article is the polity's article")
    tried = "".join(f" {name.replace('_', ' ').capitalize()}: {'no match' if present[name] else 'absent'}." for name in skipped)
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


def card(i, p, places, cell):
    e, w, matches = p["entity"], p["peak_productivity"], p["polity"] or []
    wiki = p["wiki_en"] or p["wiki_any"]
    works = p["works_period"] or {}
    rows = [
        ("Sample cell", f"{cell[0]} · {cell[1]}"),
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
        *cohort_rows(p),
        ("<b>Polity of assignation</b>", f"<b>{html.escape(matches[0]['polity']['name'])}</b>" if matches else "<b>none</b>"),
        ("All polities matched", polity_list(matches)),
        ("How the polity was chosen", explain_polity(p, places)),
    ]
    body = "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows)
    return f"<section><h2>{i}. {html.escape(fix_encoding(e['label_en'] or e.get('label_non_en')) or e['qid'])}</h2><table>{body}</table></section>"


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
<p class="intro">Source: <code>humans_clean_v2.duckdb</code>. Only input. Sample: {per} individuals spread over period (window start) × region (coordinates of death-, birth- or citizenship place) + {none} with no window (seed {seed}).
Logic: <code>scripts/database_enrichment/06_peak_productivity.py</code> and <code>08_polity_assignment.py</code>.
Date sources in brackets: precision, source.</p>
{cards}
</body></html>"""


def main():
    con = duckdb.connect(str(DB), read_only=True)
    cells = sample_qids(con)
    order = ["before 500", "500-1000", "1000-1500", "1500-1800", "1800-1900", "after 1900", "no window"]
    people = load_people(con, list(cells))
    people.sort(key=lambda p: (order.index(cells[p["entity"]["qid"]][0]), cells[p["entity"]["qid"]][1], (p["peak_productivity"] or {}).get("start_year") or 0))
    places = load_places(con, people)
    cards = "\n".join(card(i, p, places, cells[p["entity"]["qid"]]) for i, p in enumerate(tqdm(people, desc="cards"), start=1))
    OUT.write_text(PAGE.format(per=WITH_WINDOW, none=NO_WINDOW, seed=SEED, cards=cards), encoding="utf-8")
    print(f"wrote {OUT} ({len(people)} individuals)")


if __name__ == "__main__":
    main()
