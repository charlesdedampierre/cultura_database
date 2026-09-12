"""Build Individuals from the legacy database, through the data model.

Reads the flat sample (data/sample/sample.duckdb) and returns real `Individual`
objects, so the model is exercised against real data rather than a hand-written
example. Every value it produces carries the source it came from, which is the
whole point: the same birth date read from Wikidata, from CVDB and from a
Wikipedia article become three candidates, not three columns.

    python scripts/build_individuals.py 200 > individuals.jsonl
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import duckdb
from datamodel import (AIAnswer, Date, Derived, Floruit, Identifier, Individual,
                       Information, Location, Notability, Occupation, PROPERTIES, SOURCES,
                       Wikidata, WikipediaLink)

DB = Path(__file__).resolve().parent.parent.parent.parent / "data/sample/sample.duckdb"
READ = date(2026, 2, 13)


def wikidata(value, prop, qid=None, label=None, description=None, on=READ):
    """A value read from a Wikidata property."""
    if value is None:
        return None
    return Information(value=value, source=Wikidata(
        property=prop, property_definition=PROPERTIES.get(prop, {}).get("definition"),
        qid=qid, label_en=label, description_en=description, date_of_extraction=on))


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

    ids_by = group("SELECT * FROM identifiers WHERE wikidata_id IN ?")
    links_by = group("SELECT * FROM wikimedia_links WHERE wikidata_id IN ?")
    jobs_by = group("SELECT wikidata_id, occupations_ids FROM individuals_keys WHERE wikidata_id IN ?")

    def a_place(place_id):
        p = places.get(place_id)
        if p is None:
            return None
        return Location(
            id=wikidata(p["id"], "P19", qid=p["id"], label=p["name_en"]),
            lat=wikidata(p["lat"], "P625"), lon=wikidata(p["lon"], "P625"),
            entity_types=wikidata(p["entity_type"], "P31"),
            modern_country=derived(p["iso_country_name"], "reverse geocode on today's borders", "Location.lat", "Location.lon"),
            modern_country_iso_a3=derived(p["iso_a3_code"], "ISO 3166-1 lookup", "Location.modern_country"))

    out = []
    for r in rows:
        qid = r["wikidata_id"]
        occupation_ids = (jobs_by.get(qid, [{}])[0].get("occupations_ids") or "").split(",")
        out.append(Individual(
            id=wikidata(qid, "rdfs:label", qid=qid, label=r["name_en"], description=r["description_en"]),
            birthdates=birth_and_death(r, "birthdate"),
            deathdates=birth_and_death(r, "deathdate"),
            floruits=tuple(f for f in [
                Floruit(mid=a_date(wikidata(r["floruit_date"], "P1317"), precision=wikidata(r["floruit_precision"], "P1317"))) if r["floruit_date"] else None,
                Floruit(mid=Date(year=derived(r["floruit_year"], "midpoint of the activity window", "Individual.birthdates", "Individual.deathdates"))) if r["floruit_year"] else None,
            ] if f is not None),
            birthplace=a_place(r["birthcity_id"]), deathplace=a_place(r["deathcity_id"]),
            gender=wikidata(r["gender"], "P21", qid=r["gender_id"], label=r["gender"]),
            occupations=tuple(Occupation(
                id=wikidata(j, "P106", qid=j, label=jobs[j]["name_en"]),
                meta_occupation=derived(jobs[j]["meta_occupation"], "reachable from Q901 or Q483501 through P279", "Occupation.id") if jobs[j]["meta_occupation"] in ("scientist", "artist") else None,
            ) for j in occupation_ids if j in jobs),
            identifiers=tuple(Identifier(
                value=wikidata(i["value"], i["property_id"]),
                url=wikidata(i["url"], i["property_id"])) for i in ids_by.get(qid, [])[:40]),
            wikipedia_links=tuple(WikipediaLink(
                language=wikidata(w["site"], "schema:about"),
                title=wikidata(w["title"], "schema:about"),
                url=wikidata(w["url"], "schema:about")) for w in links_by.get(qid, [])[:40]),
            notability=Notability(
                total=derived(r["wikimedia_links_count"], "one per language edition", "Individual.wikipedia_links"),
                western=derived(r["notability_western"], "Western-language editions", "Individual.wikipedia_links"),
                non_western=derived(r["notability_non_western"], "non-Western-language editions", "Individual.wikipedia_links"),
                general=derived(r["notability_general"], "geometric mean of western and non_western", "Individual.notability")),
            non_human=derived(bool(r["non_human"]), "set from the Wikidata classes that are not human", "Individual.id") if r["non_human"] else None,
            number_of_works=derived(int(r["number_of_works"]), "counted over Work", "Work.creator") if r["number_of_works"] else None,
            number_of_identifiers=derived(int(r["identifiers_count"]), "counted over identifiers", "Individual.identifiers") if r["identifiers_count"] else None,
        ))
    return out


def demo() -> None:
    people = build(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
    einstein = next((p for p in people if p.id and p.id.value == "Q937"), people[0])
    assert einstein.id.source.label_en, "an individual carries its label in its source"
    assert einstein.birthdates, "and at least one birth date candidate"
    assert {type(d.iso.source).__name__ for d in einstein.birthdates if d.iso} >= {"Wikidata"}, "one of them read from Wikidata"
    for p in people:
        json.dumps(p.model_dump(mode="json"))  # every one of them survives the round trip
    for p in people:
        print(json.dumps(p.model_dump(mode="json", exclude_none=True), ensure_ascii=False))
    print(f"-- {len(people)} individuals, {sum(len(p.birthdates) for p in people)} birth date candidates", file=sys.stderr)


if __name__ == "__main__":
    demo()
