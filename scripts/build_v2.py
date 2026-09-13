"""Build humans_clean_v2.duckdb: the thirteen tables of datamodel_in_duckdb.py.

Runs on a sample of individuals by default (SAMPLE=500), so the shape can be
read and argued with before the full thirteen million are written.
"""

import json
import os
import re
import sys
from pathlib import Path

import duckdb
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datamodel_in_duckdb as M

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "humans_clean.duckdb"
TARGET = ROOT / "data" / "humans_clean_v2.duckdb"
SAMPLE = int(os.environ.get("SAMPLE", "500"))
SCRATCH = Path(os.environ.get("SCRATCH", "/tmp")) / "v2"

PRECISION = {11: "day", 10: "month", 9: "year", 8: "decade", 7: "century", 6: "millennium"}

WESTERN = {
    "en","de","fr","es","it","pt","nl","pl","sv","no","nb","nn","fi","da","is","fo","ga","gd","cy","kw","gv","br","co",
    "oc","ca","eu","gl","ast","an","ext","lad","mwl","rm","fur","lij","lmo","nap","pms","scn","vec","sc","lb","wa","fy",
    "li","nds","vls","frr","stq","dsb","hsb","ksh","bar","pdc","pfl","gsw","frp","csb","szl","cs","sk","sl","hr","bs",
    "sr","sh","mk","bg","ro","mo","hu","et","lv","lt","el","grc","la","simple","eo",
}
NON_WESTERN = {
    "ar","arz","ru","uk","be","be-tarask","kk","ky","uz","tg","tk","mn","ja","zh","zh-yue","yue","wuu","hak","lzh","ko",
    "id","ms","jv","su","min","ace","vi","th","lo","km","my","tr","az","azb","ckb","fa","he","ur","pnb","ps","sd","hi",
    "bn","as","or","ta","te","ml","kn","mr","gu","pa","ne","si","dv","ka","hy","yi","tl","ceb","war","ig","yo","ha","sw",
    "zu","xh","st","sn","ny","rw","lg","tn","ts","ve","nso","ss","om","so","ti","am","tw","ee","fon","kg","lua","sg",
    "ln","mg","kab","sat","bho","mai","new","anp","doi","ks","sa","pi","dty","awa","shn","tcy","kok",
}


def rows(con, sql, params=None):
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def split(value, sep):
    return tuple(v for v in (value or "").split(sep) if v) if value else ()


STAMP = re.compile(r"^-?\d{1,6}(-\d{2}(-\d{2})?)?$")


def iso(stamp):
    """A date, or None for the RDF blank nodes ('_:bn1772233') the source carries."""
    head = str(stamp or "").split("T")[0]
    return head if STAMP.match(head) else None


def year(stamp):
    head = iso(stamp)
    if head is None:
        return None
    sign, digits = ("-", head[1:]) if head.startswith("-") else ("", head)
    return int(sign + digits.split("-")[0])


def a_number(value):
    """An integer, or None for the blank nodes and free text the source carries."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def a_year(value):
    """A Date from a bare year, which is all Cliopatria states."""
    return None if value is None else M.Date(iso=None, year=int(value), precision="year")


def a_date(stamp, precision):
    head = iso(stamp)
    if head is None:
        return None
    return M.Date(iso=head, year=year(stamp), precision=PRECISION.get(precision))


def an_entity(qid, label=None, description=None):
    return M.WikidataEntity(qid=qid, label=label, description=description)


def origin(raw=(), rule=None, inputs=(), model=None, retrieved_on=None):
    return M.Origin(raw=raw, inputs=inputs, rule=rule, model=model, retrieved_on=retrieved_on)


# ── the DuckDB type of a pydantic model, cut at a finite depth ──────────────

SCALARS = {str: "VARCHAR", int: "BIGINT", float: "DOUBLE", bool: "BOOLEAN"}


def duck_type(annotation, seen=()):
    """The DuckDB type of a pydantic annotation. A model that reappears on the
    path — Polity inside its own Territory — is cut to its key, so the type is
    finite where the schema is not."""
    import types
    import typing
    from datetime import date as _date

    if isinstance(annotation, str):
        annotation = getattr(M, annotation)
    if annotation is _date:
        return "DATE"
    if annotation in SCALARS:
        return SCALARS[annotation]
    origin_of = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin_of in (types.UnionType, typing.Union):
        return duck_type([a for a in args if a is not type(None)][0], seen)
    if origin_of is tuple:
        return f"{duck_type(args[0], seen)}[]"
    if origin_of is dict:
        return f"MAP(VARCHAR, {duck_type(args[1], seen)})"
    if origin_of is typing.Literal:
        return "VARCHAR"
    if isinstance(annotation, type) and issubclass(annotation, M.BaseModel):
        if annotation in seen:
            return "STRUCT(cliopatria_id BIGINT, name VARCHAR)"
        inner = ", ".join(f'"{n}" {duck_type(f.annotation, seen + (annotation,))}' for n, f in annotation.model_fields.items())
        return f"STRUCT({inner})"
    raise TypeError(annotation)


def write(con, name, model, records):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / f"{name}.jsonl"
    with path.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record.model_dump(mode="json")) + "\n")
    columns = {n: duck_type(f.annotation) for n, f in model.model_fields.items()}
    con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM read_json(?, columns := {columns!r})', [str(path)])
    return con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]


# ── selection: individuals carrying as much as the sources hold ─────────────

SELECT = """
WITH rich AS (
    SELECT i.wikidata_id, i.wikimedia_links_count + i.identifiers_count + i.number_of_works AS richness,
           CAST(floor(f.floruit_period_start / 100.0) AS BIGINT) AS century
    FROM individuals i
    JOIN individuals_keys k USING (wikidata_id)
    JOIN individuals_floruit_period f USING (wikidata_id)
    WHERE i.birthdate IS NOT NULL AND i.deathdate IS NOT NULL
      AND i.wikimedia_links_count >= 15 AND i.number_of_works >= 3 AND i.identifiers_count >= 8
      AND k.occupations_ids IS NOT NULL AND k.birthcity_id IS NOT NULL
      AND f.floruit_period_start IS NOT NULL
      AND EXISTS (SELECT 1 FROM individuals_cliopatria c WHERE c.wikidata_id = i.wikidata_id)
), ranked AS (
    SELECT *, row_number() OVER (PARTITION BY century ORDER BY richness DESC) AS in_century,
              row_number() OVER (ORDER BY richness DESC) AS overall
    FROM rich
)
SELECT wikidata_id FROM ranked ORDER BY in_century, overall
"""


def main():
    src = duckdb.connect(str(SOURCE), read_only=True)
    if TARGET.exists():
        TARGET.unlink()
    out = duckdb.connect(str(TARGET))

    # the richest of each century first, then the richest of what is left, so
    # the sample is spread over time without the early centuries thinning it
    qids = [r["wikidata_id"] for r in rows(src, SELECT)][:SAMPLE]
    centuries = src.execute("SELECT count(DISTINCT CAST(floor(floruit_period_start / 100.0) AS BIGINT)) FROM individuals_floruit_period f JOIN (SELECT unnest(?::VARCHAR[]) AS wikidata_id) p USING (wikidata_id)", [qids]).fetchone()[0]
    print(f"{len(qids)} individuals, spread over {centuries} centuries", flush=True)
    src.execute("CREATE OR REPLACE TEMP TABLE pick AS SELECT unnest(?::VARCHAR[]) AS wikidata_id", [qids])

    counts = {}

    # ── the individuals and everything hanging off them ────────────────────
    people = {r["wikidata_id"]: r for r in rows(src, "SELECT i.*, k.birthcity_id, k.deathcity_id, k.country_of_citizenship_ids, k.occupations_ids, k.gender_id, k.writing_language_ids FROM individuals i JOIN individuals_keys k USING (wikidata_id) JOIN pick USING (wikidata_id)")}

    place_names = dict(src.execute("SELECT id, name_en FROM places").fetchall())
    occupation_names = dict(src.execute("SELECT id, name_en FROM occupations").fetchall())
    country_names = dict(src.execute("SELECT wikidata_id, name_en FROM country_of_citizenship").fetchall())

    by_qid = lambda table: {q: [] for q in people} | {}

    links, identifiers, credits = {q: [] for q in people}, {q: [] for q in people}, {q: [] for q in people}
    for r in tqdm(rows(src, "SELECT w.wikidata_id, w.site, w.title, w.url FROM wikimedia_links w JOIN pick USING (wikidata_id)"), desc="sitelinks"):
        links[r["wikidata_id"]].append(M.IndividualSitelink(qid=r["wikidata_id"], url=r["url"], site_url=f"https://{r['site']}", title=r["title"], origins={"url": origin(raw=("IndividualWikidata.sitelink",))}))
    for r in tqdm(rows(src, "SELECT i.wikidata_id, i.property_id, i.value, i.url FROM identifiers i JOIN pick USING (wikidata_id)"), desc="identifiers"):
        identifiers[r["wikidata_id"]].append(M.IndividualIdentifier(qid=r["wikidata_id"], pid=r["property_id"], value=r["value"], url=r["url"], origins={"value": origin(raw=("IndividualWikidata.external_id",))}))
    work_rows = rows(src, "SELECT w.* FROM works w JOIN pick ON w.individual_id = pick.wikidata_id")
    for r in tqdm(work_rows, desc="works"):
        credits[r["individual_id"]].append(M.IndividualWork(qid=r["individual_id"], work_qid=r["work_id"], credit_property=M.WikidataProperty(pid=r["relationship"], label=None, description=None) if r["relationship"] else None, origins={"credit_property": origin(raw=("IndividualWikidata.work",))}))

    RAW = {f: origin(raw=(f"IndividualWikidata.{f}",)) for f in ("entity", "place_of_birth", "place_of_death", "sex_or_gender", "occupation", "country_of_citizenship", "writing_language", "external_id", "sitelink", "work")}
    RAW |= {
        "birth_date": origin(raw=("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_birth_precision")),
        "death_date": origin(raw=("IndividualWikidata.date_of_death", "IndividualWikidata.date_of_death_precision")),
        "floruit_date": origin(raw=("IndividualWikidata.floruit", "IndividualWikidata.floruit_precision")),
        "works_period": origin(raw=("WorkWikidata.publication_date", "WorkWikidata.inception"), rule="Earliest and latest year over the individual's dated works, by publication date where there is one and inception otherwise."),
        "is_human": origin(raw=("IndividualWikidata.qid",), rule="False where the item is a fictional character, a deity or a legendary creature rather than a person."),
        "is_scientist": origin(raw=("IndividualWikidata.occupation", "OccupationWikidata.subclass_of"), rule="True when any occupation descends from scientist (Q901) through Wikidata's subclass tree."),
        "is_artist": origin(raw=("IndividualWikidata.occupation", "OccupationWikidata.subclass_of"), rule="True when any occupation descends from artist (Q483501)."),
    }

    individuals = []
    for q, r in people.items():
        span = (r["works_period"] or "").split("-") if r["works_period"] else []
        individuals.append(M.Individual(
            entity=an_entity(q, r["name_en"], r["description_en"]),
            birth_date=a_date(r["birthdate"], r["birthdate_precision"]),
            death_date=a_date(r["deathdate"], r["deathdate_precision"]),
            floruit_date=a_date(r["floruit_date"], r["floruit_precision"]),
            place_of_birth=M.Place(entity=an_entity(r["birthcity_id"], place_names.get(r["birthcity_id"]))) if r["birthcity_id"] else None,
            place_of_death=M.Place(entity=an_entity(r["deathcity_id"], place_names.get(r["deathcity_id"]))) if r["deathcity_id"] else None,
            sex_or_gender=r["gender_id"],
            occupation=tuple(M.Occupation(entity=an_entity(o, occupation_names.get(o))) for o in split(r["occupations_ids"], ";")),
            country_of_citizenship=tuple(M.CountryOfCitizenship(entity=an_entity(c, country_names.get(c))) for c in split(r["country_of_citizenship_ids"], ";")),
            writing_language=split(r["writing_language_ids"], ";"),
            external_id=tuple(identifiers[q]), sitelink=tuple(links[q]), work=tuple(credits[q]),
            works_period=M.WorksPeriod(first_year=int(span[0]), last_year=int(span[1])) if len(span) == 2 and all(s.lstrip("-").isdigit() for s in span) else None,
            is_human=None if r["non_human"] is None else not r["non_human"],
            is_scientist=None if r["is_scientist"] is None else bool(r["is_scientist"]),
            is_artist=None if r["is_artist"] is None else bool(r["is_artist"]),
            origins=RAW,
        ))
    counts["individual"] = write(out, "individual", M.Individual, individuals)

    # ── what the project computed ──────────────────────────────────────────
    floruit = {r["wikidata_id"]: r for r in rows(src, "SELECT f.* FROM individuals_floruit_period f JOIN pick USING (wikidata_id)")}
    best = {r["wikidata_id"]: r for r in rows(src, "SELECT c.* FROM individuals_cliopatria c JOIN pick USING (wikidata_id) QUALIFY row_number() OVER (PARTITION BY c.wikidata_id ORDER BY c.overlap_years DESC NULLS LAST) = 1")}
    overlaps = dict(src.execute("SELECT c.wikidata_id, count(DISTINCT c.polity_id) FROM individuals_cliopatria c JOIN pick USING (wikidata_id) GROUP BY 1").fetchall())

    ENRICHED = {
        "peak_productivity": origin(raw=("IndividualWikidata.date_of_birth", "IndividualWikidata.date_of_death", "IndividualWikidata.floruit", "WorkWikidata.publication_date"), rule="The years from age 30 to age 60, truncated by an early death; where no dates are attested, derived from the individual's works or from a life-expectancy model. assignation_method names which of the twenty-two routes was taken."),
        "polity": origin(raw=("PolityCliopatria.geometry", "PlaceWikidata.latitude", "PlaceWikidata.longitude"), inputs=("peak_productivity",), rule="Each place the individual is tied to is tested against the ground every polity held while they were active; the polity with the longest overlap wins. Where no polygon settles it, a shared Wikipedia article does."),
        "polity_count": origin(raw=("PolityCliopatria.geometry",), inputs=("peak_productivity",), rule="How many distinct polities the individual overlaps at all, not just the one published."),
        "notability": origin(raw=("IndividualWikidata.sitelink",), rule="The language editions covering the individual, split Western against non-Western on Sitelink.is_western, and the geometric mean of the two counts."),
    }

    enriched = []
    for q, r in people.items():
        f, c = floruit.get(q, {}), best.get(q)
        enriched.append(M.IndividualEnriched(
            qid=q,
            peak_productivity=M.PeakProductivity(start_year=f.get("floruit_period_start"), midpoint_year=f.get("floruit_year"), end_year=f.get("floruit_period_end"), is_estimated=None if f.get("estimated") is None else bool(f["estimated"]), assignation_method=f.get("method")) if f else None,
            polity=M.PolityMatch(polity=M.Polity(cliopatria_id=c["polity_id"], name=c["polity_name"]), years=c["overlap_years"], assignation_method=c["method"]) if c else None,
            polity_count=overlaps.get(q),
            notability=M.Notability(western_editions=r["notability_western"], non_western_editions=r["notability_non_western"], score=r["notability_general"]),
            origins=ENRICHED,
        ))
    counts["individual_enriched"] = write(out, "individual_enriched", M.IndividualEnriched, enriched)

    # ── the lookup tables, restricted to what the sample reaches ───────────
    continents = dict(src.execute("SELECT DISTINCT iso_a3_code, continent FROM polities_modern_countries_cliopatria WHERE iso_a3_code IS NOT NULL").fetchall())
    place_qids = {p for r in people.values() for p in (r["birthcity_id"], r["deathcity_id"]) if p}
    src.execute("CREATE OR REPLACE TEMP TABLE pick_place AS SELECT unnest(?::VARCHAR[]) AS id", [sorted(place_qids)])
    places = [M.Place(
        entity=an_entity(r["id"], r["name_en"]),
        coordinates=M.Coordinates(latitude=r["lat"], longitude=r["lon"]) if r["lat"] is not None else None,
        country=r["original_country_name_id"], instance_of=split(r["entity_type_ids"], "|"),
        existence=M.ExistencePeriod(inception=a_date(r["inception_date"], r["inception_precision"]), dissolution=a_date(r["dissolution_date"], r["dissolution_precision"])),
        present_day_state=M.PresentDayState(name=r["iso_country_name"], iso_3166_1_alpha_3_code=r["iso_a3_code"], continent=continents.get(r["iso_a3_code"])),
        is_settlement=None if r["is_urban_settlement"] is None else bool(r["is_urban_settlement"]),
        origins={k: origin(raw=(f"PlaceWikidata.{v}",)) for k, v in {"entity": "label", "coordinates": "latitude", "country": "country", "instance_of": "instance_of", "existence": "inception"}.items()}
        | {"present_day_state": origin(raw=("PlaceWikidata.latitude", "PlaceWikidata.longitude"), rule="Reverse-geocoded from the coordinates, so it is where the ground is today, not what Wikidata declares."),
           "is_settlement": origin(raw=("PlaceWikidata.instance_of",), rule="A language model read the P31 classes and judged whether any of them is a populated place.", model="claude")},
    ) for r in rows(src, "SELECT p.* FROM places p JOIN pick_place USING (id)")]
    counts["place"] = write(out, "place", M.Place, places)

    country_qids = {c for r in people.values() for c in split(r["country_of_citizenship_ids"], ";")}
    src.execute("CREATE OR REPLACE TEMP TABLE pick_country AS SELECT unnest(?::VARCHAR[]) AS wikidata_id", [sorted(country_qids)])
    countries = [M.CountryOfCitizenship(
        entity=an_entity(r["wikidata_id"], r["name_en"], r["description_en"]), instance_of=split(r["instance_qids"], "|"),
        coordinates=M.Coordinates(latitude=r["lat"], longitude=r["lon"]) if r["lat"] is not None else None,
        present_day_state=M.PresentDayState(name=r["iso_country_name"], iso_3166_1_alpha_3_code=r["iso_a3_code"], continent=continents.get(r["iso_a3_code"])),
        sitelink=M.Sitelink(url=r["en_wikipedia_url"]) if r["en_wikipedia_url"] else None,
        existence=M.ExistencePeriod(inception=a_date(r["inception"], None), dissolution=a_date(r["dissolved"], None)),
        origins={k: origin(raw=(f"CountryWikidata.{k}",)) for k in ("entity", "instance_of", "coordinates")}
        | {"present_day_state": origin(raw=("CountryWikidata.latitude", "CountryWikidata.longitude"), rule="Reverse-geocoded from the state's coordinates, so a historical state gives whichever state holds that ground today.")},
    ) for r in rows(src, "SELECT c.* FROM country_of_citizenship c JOIN pick_country USING (wikidata_id)")]
    counts["country_of_citizenship"] = write(out, "country_of_citizenship", M.CountryOfCitizenship, countries)

    occupation_qids = {o for r in people.values() for o in split(r["occupations_ids"], ";")}
    src.execute("CREATE OR REPLACE TEMP TABLE pick_occupation AS SELECT unnest(?::VARCHAR[]) AS id", [sorted(occupation_qids)])
    occupations = [M.Occupation(
        entity=an_entity(r["id"], r["name_en"], r["description_en"]), subclass_of=(),
        origins={"entity": origin(raw=("OccupationWikidata.label", "OccupationWikidata.description"))},
    ) for r in rows(src, "SELECT o.* FROM occupations o JOIN pick_occupation USING (id)")]
    counts["occupation"] = write(out, "occupation", M.Occupation, occupations)

    pids = sorted({i.pid for group in identifiers.values() for i in group})
    src.execute("CREATE OR REPLACE TEMP TABLE pick_pid AS SELECT unnest(?::VARCHAR[]) AS property_id", [pids])
    identifier_types = [M.Identifier(
        property=M.WikidataProperty(pid=r["property_id"], label=r["name_en"], description=r["description"]), formatter_url=None,
        issuer=r["issuer_id"], issuer_country=r["country_id"], official_website=r["website"],
        number_of_records=a_number(r["database_records"]), inception=a_date(r["inception"], None),
        origins={k: origin(raw=(f"ExternalIdPropertyWikidata.{k}",)) for k in ("property", "issuer", "issuer_country", "official_website", "number_of_records", "inception")},
    ) for r in rows(src, "SELECT t.* FROM identifier_types t JOIN pick_pid USING (property_id)")]
    counts["identifier"] = write(out, "identifier", M.Identifier, identifier_types)
    counts["individual_identifier"] = write(out, "individual_identifier", M.IndividualIdentifier, [i for g in identifiers.values() for i in g])

    # editions: counted over every article in the source, not just the sample's
    editions = []
    for site, n in tqdm(src.execute("SELECT site, count(*) FROM wikimedia_links GROUP BY 1 ORDER BY 2 DESC").fetchall(), desc="editions"):
        code = site.split(".")[0]
        editions.append(M.Sitelink(
            url=f"https://{site}", label=None, language=None,
            is_western=True if code in WESTERN else (False if code in NON_WESTERN else None),
            number_of_articles=n,
            origins={"number_of_articles": origin(raw=("IndividualWikidata.sitelink",), rule="Count of articles this edition carries across every individual in Cultura."),
                     "is_western": origin(raw=("IndividualWikidata.sitelink",), rule="The edition's language code read against a list of Western and non-Western languages this project drew up. Empty where the code is on neither list.")},
        ))
    counts["sitelink"] = write(out, "sitelink", M.Sitelink, editions)
    counts["individual_sitelink"] = write(out, "individual_sitelink", M.IndividualSitelink, [s for g in links.values() for s in g])

    work_qids = sorted({r["work_id"] for r in work_rows})
    seen, works = set(), []
    for r in work_rows:
        if r["work_id"] in seen:
            continue
        seen.add(r["work_id"])
        works.append(M.Work(
            entity=an_entity(r["work_id"], r["work_name"]), instance_of=split(r["instance_of"], "|"),
            inception=a_date(r["inception_date"], r["inception_precision"]),
            publication_date=a_date(r["publication_date"], r["publication_precision"]),
            origins={k: origin(raw=(f"WorkWikidata.{k}",)) for k in ("entity", "instance_of", "inception", "publication_date")},
        ))
    counts["work"] = write(out, "work", M.Work, works)
    counts["individual_work"] = write(out, "individual_work", M.IndividualWork, [w for g in credits.values() for w in g])

    # ── polities: one row each, territories nested ─────────────────────────
    modern = {}
    for r in rows(src, "SELECT polity_id, country_name, iso_a3_code, continent FROM polities_modern_countries_cliopatria"):
        modern.setdefault(r["polity_id"], []).append(M.PresentDayState(name=r["country_name"], iso_3166_1_alpha_3_code=r["iso_a3_code"], continent=r["continent"]))
    spans = {}
    for r in rows(src, "SELECT * FROM polities_periods_cliopatria ORDER BY polity_id, from_year"):
        spans.setdefault(r["polity_id"], []).append(M.Territory(
            start_year=r["from_year"], end_year=r["to_year"], area=r["area"], geometry=r["geometry"],
            present_day_states=tuple(modern.get(r["polity_id"], ())),
            origins={k: origin(raw=(f"PolityCliopatria.{v}",)) for k, v in {"start_year": "from_year", "end_year": "to_year", "area": "area", "geometry": "geometry"}.items()}
            | {"present_day_states": origin(raw=("PolityCliopatria.geometry",), rule="The present-day states whose ground this territory's polygon overlaps. Cliopatria resolves them per polity, not per territory, so every territory of one polity repeats the same list.")},
        ))
    polities = [M.Polity(
        cliopatria_id=r["id"], name=r["name"], type=r["type"],
        entity=an_entity(r["wikidata_id"], r["name"]) if r["wikidata_id"] else None,
        sitelink=M.Sitelink(url=r["wikipedia_url"]) if r["wikipedia_url"] else None,
        existence=M.ExistencePeriod(
            inception=a_year(min((t.start_year for t in spans.get(r["id"], []) if t.start_year is not None), default=None)),
            dissolution=a_year(max((t.end_year for t in spans.get(r["id"], []) if t.end_year is not None), default=None))),
        territories=tuple(spans.get(r["id"], ())),
        origins={k: origin(raw=(f"PolityCliopatria.{v}",)) for k, v in {"cliopatria_id": "id", "name": "name", "type": "type", "entity": "wikidata_id", "sitelink": "wikipedia_url"}.items()}
        | {"existence": origin(inputs=("territories",), rule="Earliest start and latest end over the polity's territories.")},
    ) for r in rows(src, "SELECT * FROM polities_cliopatria")]
    counts["polity"] = write(out, "polity", M.Polity, polities)

    properties = [M.WikidataProperty(pid=r["property_id"], label=r["property_name"], description=r["description"])
                  for r in rows(src, "SELECT DISTINCT property_id, property_name, description FROM wikidata_properties_definition")]
    counts["wikidata_property"] = write(out, "wikidata_property", M.WikidataProperty, properties)

    out.close()
    src.close()
    print()
    for name in M.TABLES:
        print(f"   {name:24} {counts.get(name, 0):>9,}")
    print(f"\n{TARGET}  {TARGET.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
