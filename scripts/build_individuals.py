"""Build Individuals from the legacy database, through the data model.

Reads the flat sample (data/sample/sample.duckdb) and returns real `Individual`
objects, so the model is exercised against real data rather than a hand-written
example. Every value it produces carries the source it came from, which is the
whole point: the same birth date read from Wikidata, from CVDB and from a
Wikipedia article become three candidates, not three columns.

    python scripts/build_individuals.py 200 > individuals.jsonl
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
from datamodel import (AIAnswer, Date, Derived, Floruit, Identifier, Individual,
                       Information, City, Notability, Occupation,
                       Polity, Territory, Wikidata, WikidataEntity, WikidataProperty,
                       WikipediaLink, Work)

HERE = Path(__file__).resolve().parent.parent
PROPERTIES = json.loads((HERE / "properties.json").read_text())
SOURCES = json.loads((HERE / "sources.json").read_text())
DB = HERE / "data/sample/sample.duckdb"
READ = date(2026, 2, 13)
CAP = 200  # per individual, for identifiers, Wikipedia links and a polity's periods
GEOMETRY = os.environ.get("WITH_GEOMETRY") == "1"  # the polygons are ~99% of the output; off unless asked


def wikidata(value, prop, qid=None, label=None, description=None, on=READ):
    """A value read from a Wikidata property."""
    if value is None:
        return None
    return Information(value=value, source=Wikidata(
        property=WikidataProperty(pid=prop, label_en=PROPERTIES.get(prop, {}).get("name"), definition=PROPERTIES.get(prop, {}).get("definition")),
        entity=WikidataEntity(qid=qid, label_en=label) if qid else None,
        date_of_extraction=on))


def entity(qid, label=None, description=None, on=READ):
    """A row saying which Wikidata item it is."""
    if qid is None:
        return None
    return Information(value=qid, source=Wikidata(
        entity=WikidataEntity(qid=qid, label_en=label, description_en=description), date_of_extraction=on))


def derived(value, rule, *inputs, on=READ):
    """A value this project computed."""
    if value is None:
        return None
    return Information(value=value, source=Derived(
        derived_from=inputs, rule=rule, date_of_extraction=on))


def answered(value, on=date(2026, 5, 6)):
    """A value a language model read out of a Wikipedia article."""
    if value is None:
        return None
    return Information(value=value, source=AIAnswer(
        model="google/gemini-2.5-flash-lite",
        prompt=(Path(__file__).resolve().parent.parent / "prompts/wikipedia_dates.txt").read_text().strip(),
        date_of_extraction=on))


def clio(value):
    """A value taken from the Cliopatria dataset."""
    if value is None:
        return None
    return Information(value=value, source=Derived(
        derived_from=("Cliopatria V3",), rule="read from the Cliopatria GeoJSON as published", date_of_extraction=date(2026, 4, 23)))


def year_of(iso):
    """The year in an ISO string, negative before the common era."""
    if not iso:
        return None
    text = str(iso)
    sign = -1 if text.startswith("-") else 1
    digits = text.lstrip("-").split("-")[0]
    return sign * int(digits) if digits.isdigit() else None


def a_date(information, precision=None, rule="the year parsed out of the ISO string"):
    """Wrap a value that is a date: the ISO string, its precision, its year."""
    if information is None:
        return None
    return Date(iso=information, precision=precision,
                year=derived(year_of(information.value), rule, "Date.iso"))


def birth_and_death(row, which):
    """Every candidate for a birth or a death date, one per source."""
    iso = row[which]
    out = [a_date(wikidata(iso, "P569" if which == "birthdate" else "P570"),
                  precision=wikidata(row[f"{which}_precision"], "P569" if which == "birthdate" else "P570"))]
    out.append(a_date(answered(row[f"{which}_from_wikipedia"])))
    estimated = row[f"{which}_from_life_expectancy"]
    out.append(a_date(derived(estimated, "estimated from the other date against a median life expectancy",
                              f"Individual.{'deathdates' if which == 'birthdate' else 'birthdates'}")))
    from_description = row[f"{which}_in_description"]
    if from_description is not None:
        out.append(Date(year=derived(from_description, "regex over the Wikidata description", "Individual.id")))
    return tuple(d for d in out if d is not None)


def build(limit: int) -> list[Individual]:
    con = duckdb.connect(str(DB), read_only=True)

    def fetch(sql, *params):
        """Rows as dicts. Not pandas: it turns every NULL into a NaN float."""
        cur = con.execute(sql, list(params))
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]

    rows = fetch(f"""
        SELECT i.*, k.birthcity_id, k.deathcity_id, k.gender_id
        FROM individuals i LEFT JOIN individuals_keys k USING (wikidata_id)
        ORDER BY i.notability_general DESC NULLS LAST LIMIT {limit}
    """)
    ids = [r["wikidata_id"] for r in rows]

    places = {p["id"]: p for p in fetch(
        "SELECT * FROM places WHERE id IN (SELECT birthcity_id FROM individuals_keys UNION SELECT deathcity_id FROM individuals_keys)")}
    jobs = {o["id"]: o for o in fetch("SELECT * FROM occupations")}

    def group(sql):
        out = {}
        for r in fetch(sql, ids):
            out.setdefault(r[[k for k in r if k in ("wikidata_id", "individual_id")][0]], []).append(r)
        return out

    countries = {c["wikidata_id"]: c for c in fetch("SELECT * FROM country_of_citizenship")}
    polities = {p["id"]: p for p in fetch("SELECT * FROM polities_cliopatria")}
    periods_by = {}
    for t in fetch("SELECT * FROM polities_periods_cliopatria"):
        periods_by.setdefault(t["polity_id"], []).append(t)
    countries_by_polity = {}
    for c in fetch("SELECT * FROM polities_modern_countries_cliopatria"):
        countries_by_polity.setdefault(c["polity_id"], []).append(c)

    ids_by = group("SELECT * FROM identifiers WHERE wikidata_id IN ?")
    links_by = group("SELECT * FROM wikimedia_links WHERE wikidata_id IN ?")
    jobs_by = group("SELECT wikidata_id, occupations_ids FROM individuals_keys WHERE wikidata_id IN ?")
    citizens_by = group("SELECT wikidata_id, country_of_citizenship_ids FROM individuals_keys WHERE wikidata_id IN ?")
    clio_by = group("SELECT * FROM individuals_cliopatria WHERE wikidata_id IN ?")
    works_by = group("SELECT * FROM works WHERE individual_id IN ?")
    floruit_by = {f["wikidata_id"]: f for f in fetch("SELECT * FROM individuals_floruit_period WHERE wikidata_id IN ?", ids)}

    def cvdb(value):
        """A value the cross-verified database supplies, read through no Wikidata property."""
        return derived(value, "modal CVDB label over the individuals sharing the occupation", "Occupation.id") if value else None

    seen_polities: dict = {}

    def a_polity(polity_id):
        """A polity as an individual sees it: which one it is, not the ground it held.
        The ground is heavy — the polygons are 96% of the output — so the full polity
        goes to its own table, and this keeps the name that joins to it."""
        p = polities.get(polity_id)
        if p is None:
            return None
        seen_polities.setdefault(polity_id, full_polity(polity_id))
        return Polity(id=clio(p["id"]), name=clio(p["name"]), type=clio(p["type"]))

    def full_polity(polity_id):
        """The whole polity, for the polity table: every period, its ground and its area."""
        p = polities[polity_id]
        years = [t for t in periods_by.get(polity_id, [])]
        today = tuple(Polity(id=clio(c["country_qid"]), name=clio(c["country_name"])) for c in countries_by_polity.get(polity_id, []))
        return Polity(
            id=clio(p["id"]), name=clio(p["name"]), type=clio(p["type"]),
            start=Date(year=clio(min((t["from_year"] for t in years), default=None))) if years else None,
            end=Date(year=clio(max((t["to_year"] for t in years), default=None))) if years else None,
            wikipedia_link=WikipediaLink(language="en.wikipedia.org", url=p["wikipedia_url"]) if p["wikipedia_url"] else None,
            territories=tuple(Territory(
                start=Date(year=clio(t["from_year"])), end=Date(year=clio(t["to_year"])),
                area=clio(t["area"]), geometry=clio(t["geometry"]) if GEOMETRY else None, modern_polities=today) for t in years[:CAP]))

    def a_citizenship(qid):
        """A country of citizenship is a polity, not a place."""
        c = countries.get(qid)
        if c is None:
            return None
        return Polity(id=wikidata(qid, "P27", qid=qid, label=c["name_en"]), name=wikidata(c["name_en"], "rdfs:label"),
                      wikipedia_link=WikipediaLink(language="en.wikipedia.org", url=c["en_wikipedia_url"]) if c["en_wikipedia_url"] else None,
                      start=Date(iso=wikidata(c["inception"], "P571")) if c["inception"] else None,
                      end=Date(iso=wikidata(c["dissolved"], "P576")) if c["dissolved"] else None)

    def a_place(place_id, matched_polities=()):
        p = places.get(place_id)
        if p is None:
            return None
        return City(
            id=entity(p["id"], label=p["name_en"]),
            lat=wikidata(p["lat"], "P625"), lon=wikidata(p["lon"], "P625"),
            modern_polity=Polity(
                name=derived(p["iso_country_name"], "reverse geocode on today's borders", "City.lat", "City.lon"),
                id=derived(p["iso_a3_code"], "ISO 3166-1 lookup", "Polity.name")) if p["iso_country_name"] else None,
            polities=matched_polities)

    def floruits_of(qid, r):
        """Every activity window: the one Wikidata states, and the one this project resolves."""
        f = floruit_by.get(qid, {})
        out = [Floruit(mid=a_date(wikidata(r["floruit_date"], "P1317"), precision=wikidata(r["floruit_precision"], "P1317"))) if r["floruit_date"] else None]
        if f.get("floruit_year") is not None:
            out.append(Floruit(
                mid=Date(year=derived(f["floruit_year"], "midpoint of the activity window", "Individual.birthdates", "Individual.deathdates")),
                start=Date(year=derived(f["floruit_period_start"], "birth + 30, truncated by death", "Individual.birthdates")) if f.get("floruit_period_start") is not None else None,
                end=Date(year=derived(f["floruit_period_end"], "birth + 60, truncated by death", "Individual.deathdates")) if f.get("floruit_period_end") is not None else None))
        return tuple(x for x in out if x is not None)

    def matched(qid, origin):
        """The polities this individual's place of `origin` fell inside."""
        return tuple(p for p in (a_polity(m["polity_id"]) for m in clio_by.get(qid, []) if m["origin"] == origin) if p)

    out = []
    for r in rows:
        qid = r["wikidata_id"]
        occupation_ids = (jobs_by.get(qid, [{}])[0].get("occupations_ids") or "").split(";")
        out.append(Individual(
            id=entity(qid, label=r["name_en"], description=r["description_en"]),
            birthdates=birth_and_death(r, "birthdate"),
            deathdates=birth_and_death(r, "deathdate"),
            floruits=floruits_of(qid, r),
            birthplaces=tuple(p for p in [a_place(r["birthcity_id"], matched(qid, "birthplace"))] if p),
            deathplaces=tuple(p for p in [a_place(r["deathcity_id"], matched(qid, "deathplace"))] if p),
            citizenships=tuple(c for c in (a_citizenship(q) for q in (citizens_by.get(qid, [{}])[0].get("country_of_citizenship_ids") or "").split(";")) if c),
            works=tuple(Work(
                id=entity(w["work_id"], label=w["work_name"]),
                creator=entity(qid, label=r["name_en"]),
                role=wikidata(w["relationship"], "P170"),
                instance_of=wikidata(w["instance_of_en"], "P31"),
                inception=a_date(wikidata(w["inception_date"], "P571"), precision=wikidata(w["inception_precision"], "P571")),
                publication=a_date(wikidata(w["publication_date"], "P577"), precision=wikidata(w["publication_precision"], "P577")),
            ) for w in works_by.get(qid, [])[:CAP]),
            polity_overlap_years=tuple((a_polity(m["polity_id"]), derived(m["overlap_years"], f"years of the floruit covered by the polity, matched by {m['method']} on the {m['origin']}", "Individual.floruits", f"Individual.{m['origin']}s"))
                                       for m in clio_by.get(qid, []) if a_polity(m["polity_id"]) and m["overlap_years"] is not None),
            gender=wikidata(r["gender_id"], "P21", qid=r["gender_id"], label=r["gender"]),
            occupations=tuple(Occupation(
                id=entity(j, label=jobs[j]["name_en"]),
                meta_occupation=derived(jobs[j]["meta_occupation"], "reachable from Q901 or Q483501 through P279", "Occupation.id") if jobs[j]["meta_occupation"] in ("scientist", "artist") else None,
                cvdb_level1=cvdb(jobs[j]["level1_main_occ"]), cvdb_level2=cvdb(jobs[j]["level2_main_occ"]), cvdb_level3=cvdb(jobs[j]["level3_main_occ"]),
                cvdb_n_votes=derived(jobs[j]["ontology_n_votes"], "CVDB individuals voting for the modal label", "Occupation.cvdb_level3") if jobs[j]["ontology_n_votes"] else None,
            ) for j in occupation_ids if j in jobs),
            identifiers=tuple(Identifier(
                value=wikidata(i["value"], i["property_id"]),
                url=wikidata(i["url"], i["property_id"])) for i in ids_by.get(qid, [])[:CAP]),
            wikipedia_links=tuple(WikipediaLink(language=w["site"], title=w["title"], url=w["url"])
                                  for w in links_by.get(qid, [])[:CAP]),
            notability=Notability(
                score=derived(r["notability_general"], "geometric mean of the two edition counts", "Notability.western_editions", "Notability.non_western_editions"),
                western_editions=derived(r["notability_western"], "Western-language editions carrying an article", "Individual.id"),
                non_western_editions=derived(r["notability_non_western"], "non-Western-language editions carrying an article", "Individual.id"),
                articles_fetched=derived(r["wikimedia_links_count"], "articles downloaded for this individual", "Individual.wikipedia_links")),
            non_human=derived(bool(r["non_human"]), "set from the Wikidata classes that are not human", "Individual.id") if r["non_human"] else None,
            number_of_works=derived(int(r["number_of_works"]), "counted over Work", "Work.creator") if r["number_of_works"] else None,
            number_of_identifiers=derived(int(r["identifiers_count"]), "counted over identifiers", "Individual.identifiers") if r["identifiers_count"] else None,
        ))
    return out, seen_polities


def demo() -> None:
    people, polities = build(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
    if os.environ.get("POLITIES_OUT"):
        with open(os.environ["POLITIES_OUT"], "w") as f:
            for p in polities.values():
                f.write(json.dumps(p.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n")
    einstein = next((p for p in people if p.id and p.id.value == "Q937"), people[0])
    assert einstein.id.source.entity.label_en, "an individual carries its label in the entity of its source"
    assert einstein.birthdates, "and at least one birth date candidate"
    assert {type(d.iso.source).__name__ for d in einstein.birthdates if d.iso} >= {"Wikidata"}, "one of them read from Wikidata"
    for p in people:
        json.dumps(p.model_dump(mode="json"))  # every one of them survives the round trip
    for p in people:
        print(json.dumps(p.model_dump(mode="json", exclude_none=True), ensure_ascii=False))
    print(f"-- {len(people)} individuals, {sum(len(p.birthdates) for p in people)} birth date candidates, {len(polities)} polities", file=sys.stderr)


if __name__ == "__main__":
    demo()
