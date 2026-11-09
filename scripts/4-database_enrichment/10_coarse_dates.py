"""Last enrichment step: individuals with a birth or death date known only to the century or the millennium.

1. A century- or millennium-level date is always a label, never a year: the 127 births and deaths that kept Wikidata's
   year (1950 for "20th century") get the year emptied and their coarse_label ('20th AC').
2. Their estimated start and end of active life become century-level too: the year emptied, the century of the estimate
   as coarse_label. An active life read from dated works and positions keeps its year. With no active life at all, the
   start is the century of the birth and the end the century of the death ('19th AC' to '20th AC'), source
   'estimated from the century dates'; the start stays empty without a birth, the end without a death.
3. Their polities: the life-stage matching of 02_notebooks_polity needs a birth year, so these individuals had none.
   active_life_polity (and main_polity) gets the polities over a window: the years of the active life when known,
   else the birth and death years or centuries, clipped to the coarse centuries. When the active life is dated (from works
   and positions), the pre-active stage runs from the birth year, else the first year of the birth century, to its start,
   and the post-active stage from its end to the death year, else the last year of the death century. Without a dated
   active life the life cannot be split: the pre- and post-active stages stay empty. Each stage uses its own location
   rules (01_life_stage_polities_export.py), and the Seshat polities of the territories overlapping the stage (as step 08)."""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import polars as pl
from tqdm import tqdm

from common import D, ROOT, SCRATCH, Enrichment, as_json, open_database, provenance_column, rewrite_individual_enriched
from pydantic_to_duckdb_schema import columns_of

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "02_notebooks_polity"))
from ingest_life_stage_polities import FIELD_NAMES, MATCH_LIST_TYPE, METHOD_NAMES, NAME_FIXES

spec = importlib.util.spec_from_file_location("life_stage_polities_export", HERE / "02_notebooks_polity" / "01_life_stage_polities_export.py")
export = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export)

SESHAT_POLITIES = ROOT / "data" / "seshat" / "seshat_polities.json"
COARSE = "('century', 'millennium')"
UNIT = {"century": 100, "millennium": 1000}
STAGES = ("pre_active_life_polity", "active_life_polity", "post_active_life_polity")

DATES = Enrichment(
    reads=("IndividualEnriched.birth_date", "IndividualEnriched.death_date", "IndividualEnriched.start_of_active_life", "IndividualEnriched.end_of_active_life"),
    writes=("IndividualEnriched.birth_date", "IndividualEnriched.death_date", "IndividualEnriched.start_of_active_life", "IndividualEnriched.end_of_active_life"),
    rule="A date known only to the century or millennium is a label without a year ('20th AC'); an estimated active life of an individual with such a date is kept at the century of the estimate; "
         "with no active life, it runs from the century of the birth to the century of the death, source 'estimated from the century dates'.",
    answers=Path(__file__),
)
POLITIES = Enrichment(
    reads=(*DATES.writes, "IndividualWikidata.place_of_birth", "IndividualWikidata.place_of_death", "IndividualWikidata.country_of_citizenship",
           "IndividualWikidata.work_location", "IndividualWikidata.residence", "IndividualWikidata.employer", "IndividualWikidata.educated_at",
           "IndividualWikidata.position_held", "Polity.territories", "Seshat API long_name"),
    writes=tuple(f"IndividualEnriched.{column}" for column in (*STAGES, "main_polity")),
    rule="Individuals with a century- or millennium-level birth or death: active_life_polity matched over the years of the active life when known, "
         "else the birth and death years or centuries, clipped to the coarse centuries; with a dated active life, pre-active from the birth year or the start of the birth century "
         "to the start of the active life and post-active from its end to the death year or the end of the death century, else both left empty; each stage with its own location rules.",
    answers=Path(__file__),
)

MACROS = f"""
CREATE OR REPLACE TEMP MACRO ordinal(n) AS n || CASE WHEN n % 100 IN (11, 12, 13) THEN 'th' WHEN n % 10 = 1 THEN 'st' WHEN n % 10 = 2 THEN 'nd' WHEN n % 10 = 3 THEN 'rd' ELSE 'th' END;
CREATE OR REPLACE TEMP MACRO year_label(year, unit) AS
    ordinal(CAST(ceil(abs(year) / CASE unit WHEN 'millennium' THEN 1000 ELSE 100 END) AS BIGINT))
    || CASE unit WHEN 'millennium' THEN ' millennium' ELSE '' END || CASE WHEN year < 0 THEN ' BC' ELSE ' AC' END;
CREATE OR REPLACE TEMP MACRO is_coarse(d) AS d.precision IN {COARSE};
CREATE OR REPLACE TEMP MACRO has_coarse_date(birth, death) AS coalesce(is_coarse(birth) OR is_coarse(death), false);
CREATE OR REPLACE TEMP MACRO coarse_date(d, provenance) AS CASE WHEN is_coarse(d) AND d.year IS NOT NULL THEN struct_update(d,
    iso := NULL::VARCHAR, year := NULL::BIGINT, coarse_label := year_label(d.year, d.precision),
    field_provenance := map_concat(coalesce(d.field_provenance, MAP {{}}), MAP {{'year': provenance, 'coarse_label': provenance}})) ELSE d END;
CREATE OR REPLACE TEMP MACRO life_century(d) AS CASE
    WHEN is_coarse(d) THEN coalesce(d.coarse_label, year_label(d.year, d.precision))
    WHEN d.year IS NOT NULL THEN year_label(d.year, 'century') END;
CREATE OR REPLACE TEMP MACRO century_active(d, life, provenance) AS CASE WHEN d.year IS NULL AND d.coarse_label IS NULL AND life_century(life) IS NOT NULL THEN {{
    'iso': NULL, 'year': NULL, 'precision': CASE WHEN life.precision = 'millennium' THEN 'millennium' ELSE 'century' END,
    'field_provenance': MAP {{'precision': provenance, 'coarse_label': provenance, 'source': provenance}},
    'source': 'estimated from the century dates', 'cohort': NULL, 'coarse_label': life_century(life)
}} ELSE d END;
CREATE OR REPLACE TEMP MACRO coarse_active(d, provenance) AS CASE WHEN d.source = 'estimated' AND d.year IS NOT NULL THEN struct_update(d,
    iso := NULL::VARCHAR, year := NULL::BIGINT, "precision" := 'century', coarse_label := year_label(d.year, 'century'),
    field_provenance := map_concat(coalesce(d.field_provenance, MAP {{}}), MAP {{'year': provenance, 'precision': provenance, 'coarse_label': provenance}})) ELSE d END;
"""

PEOPLE = """
WITH fixed AS (
    SELECT entity.qid AS qid,
           CASE WHEN is_coarse(birth_date) THEN NULL ELSE birth_date.year END AS birth_year,
           CASE WHEN is_coarse(birth_date) THEN coalesce(birth_date.coarse_label, year_label(birth_date.year, birth_date.precision)) END AS birth_label,
           CASE WHEN is_coarse(death_date) THEN NULL ELSE death_date.year END AS death_year,
           CASE WHEN is_coarse(death_date) THEN coalesce(death_date.coarse_label, year_label(death_date.year, death_date.precision)) END AS death_label,
           CASE WHEN start_of_active_life.source = 'estimated' THEN NULL ELSE start_of_active_life.year END AS start_active,
           CASE WHEN end_of_active_life.source = 'estimated' THEN NULL ELSE end_of_active_life.year END AS end_active
    FROM individual_enriched
    WHERE has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date)
)
SELECT fixed.*,
       [individual.place_of_birth.entity.qid] AS place_of_birth,
       [individual.place_of_death.entity.qid] AS place_of_death,
       list_transform(individual.country_of_citizenship, country -> country.entity.qid) AS country_of_citizenship,
       list_transform(individual.work_location, place -> place.entity.qid) AS work_location,
       list_transform(individual.residence, place -> place.entity.qid) AS residence,
       list_transform(individual.employer, institution -> institution.entity.qid) AS employer,
       list_transform(individual.educated_at, institution -> institution.entity.qid) AS educated_at,
       list_distinct(list_transform(individual.position_held, held -> held.position.qid)) AS position_held
FROM fixed JOIN individual ON individual.entity.qid = fixed.qid
"""


def label_span(label):
    """First and last year of a coarse label: '20th AC' -> (1901, 2000), '4th BC' -> (-400, -301), '2nd millennium AC' -> (1001, 2000)."""
    if not label:
        return None
    number, *rest = label.split()
    n = int("".join(filter(str.isdigit, number)))
    unit = UNIT["millennium" if "millennium" in rest else "century"]
    if rest[-1] == "BC":
        return -n * unit, -(n - 1) * unit - 1
    return (n - 1) * unit + 1, n * unit


def window(person):
    """Years over which the polities are matched: the active life when known, else the life dates, clipped to the coarse centuries."""
    birth = label_span(person["birth_label"]) or (person["birth_year"],) * 2
    death = label_span(person["death_label"]) or (person["death_year"],) * 2
    low = next((year for year in (person["start_active"], birth[0], death[0]) if year is not None), None)
    high = next((year for year in (person["end_active"], death[1], birth[1]) if year is not None), None)
    if person["birth_label"]:
        low = max(low, birth[0])
    if person["death_label"]:
        high = min(high, death[1])
    if low > high:
        low = birth[0] if birth[0] is not None else death[0]
        high = death[1] if death[1] is not None else birth[1]
    return low, high


def windows(person):
    """Years of each stage: the active window, plus the pre- and post-active stages around a dated active life, bounded by the life dates or their centuries."""
    low, high = window(person)
    stages = {"active": (low, high)}
    if person["start_active"] is None or person["end_active"] is None:
        return stages
    birth = label_span(person["birth_label"]) or (person["birth_year"],) * 2
    death = label_span(person["death_label"]) or (person["death_year"],) * 2
    if birth[0] is not None and birth[0] < low:
        stages["pre_active"] = (birth[0], low)
    if death[1] is not None and high < death[1]:
        stages["post_active"] = (high, death[1])
    return stages


class Polities:
    """Polity rows by name, and the Seshat long names, to turn a located polity name into a PolityMatch."""

    def __init__(self, connection):
        self.by_name = {}
        rows = connection.execute("""
            SELECT name, cliopatria_id, world, meta_polities,
                   list_transform(territories, territory -> {'start_year': territory.start_year, 'end_year': territory.end_year, 'seshat_id': territory.seshat_id})
            FROM polity ORDER BY cliopatria_id
        """).fetchall()
        for name, cliopatria_id, world, meta_polities, territories in rows:
            self.by_name.setdefault(name, []).append({"cliopatria_id": cliopatria_id, "world": world, "meta_polities": meta_polities, "territories": territories})
        self.long_name = {polity["name"]: polity["long_name"] for polity in json.loads(SESHAT_POLITIES.read_text())}

    def match(self, name, years, located, low, high):
        name = NAME_FIXES.get(name, name)
        overlapping = lambda polity: [t for t in polity["territories"] if t["start_year"] <= high and t["end_year"] >= low]
        polity = next((polity for polity in self.by_name[name] if overlapping(polity)), self.by_name[name][0])
        seshat = []
        for territory in sorted(overlapping(polity), key=lambda t: t["start_year"]):
            if territory["seshat_id"] and territory["seshat_id"] not in [one["id"] for one in seshat]:
                seshat.append({"id": territory["seshat_id"], "long_name": self.long_name.get(territory["seshat_id"])})
        return D.PolityMatch(
            polity={"cliopatria_id": polity["cliopatria_id"], "name": name, "world": polity["world"], "meta_polities": polity["meta_polities"]},
            years_spent_in_polity=years,
            assignation_method=f"{METHOD_NAMES[located['method']]}_of_{FIELD_NAMES[located['wikidata_field']]}",
            certainty=located["certainty"],
            location=located["location"],
            seshat=seshat,
        )


def match_people(connection, sample):
    connection.execute(MACROS)
    people = connection.execute(PEOPLE + (f" ORDER BY hash(fixed.qid) LIMIT {sample}" if sample else "")).pl()
    print(f"{people.height:,} individuals with a century- or millennium-level date")
    people = people.with_columns(pl.col("place_of_birth", "place_of_death").list.drop_nulls())
    locations = export.Locations(connection)
    locations.add_spots(people)
    polities = Polities(connection)
    rows = []
    for person in tqdm(people.iter_rows(named=True), total=people.height, desc="coarse-date polities"):
        row = {"qid": person["qid"]}
        for stage, (low, high) in windows(person).items():
            located = locations.assign(person, stage, low, high)
            row[f"{stage}_life_polity"] = [as_json(polities.match(name, years, located, low, high)) for name, years in zip(located["polities"], located["polity_years"])]
        rows.append(row)
    path = SCRATCH / ("coarse_date_polities_sample.json" if sample else "coarse_date_polities.json")
    path.write_text(json.dumps(rows))
    columns = {"qid": "VARCHAR", **{column: MATCH_LIST_TYPE for column in STAGES}}
    connection.execute(f"CREATE OR REPLACE TEMP TABLE coarse_polity AS SELECT * FROM read_json(?, columns := {columns!r})", [str(path)])
    for column in STAGES:
        matched = sum(1 for row in rows if row.get(column))
        print(f"{column}: {matched:,} of {len(rows):,} matched to a polity")


def rows_sql(connection):
    types = columns_of(D.IndividualEnriched)
    dates = as_json(DATES.provenance())
    polities = as_json(POLITIES.provenance())
    stages = ",\n            ".join(
        f"CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN coalesce(coarse_polity.{column}, []) "
        f"ELSE individual_enriched.{column} END::{types[column]} AS {column}"
        for column in STAGES
    )
    keys = ", ".join(f"'{column}': ?::{provenance_column()}" for column in (*STAGES, "main_polity"))
    return (
        f"""
        SELECT individual_enriched.* REPLACE (
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN coarse_date(individual_enriched.birth_date, ?::{provenance_column()}) ELSE individual_enriched.birth_date END::{types['birth_date']} AS birth_date,
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN coarse_date(individual_enriched.death_date, ?::{provenance_column()}) ELSE individual_enriched.death_date END::{types['death_date']} AS death_date,
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN century_active(coarse_active(individual_enriched.start_of_active_life, ?::{provenance_column()}), individual_enriched.birth_date, ?::{provenance_column()}) ELSE individual_enriched.start_of_active_life END::{types['start_of_active_life']} AS start_of_active_life,
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN century_active(coarse_active(individual_enriched.end_of_active_life, ?::{provenance_column()}), individual_enriched.death_date, ?::{provenance_column()}) ELSE individual_enriched.end_of_active_life END::{types['end_of_active_life']} AS end_of_active_life,
            {stages},
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN coarse_polity.active_life_polity[1] ELSE individual_enriched.main_polity END::{types['main_polity']} AS main_polity,
            CASE WHEN has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date) THEN map_concat(coalesce(individual_enriched.field_provenance, MAP {{}}), MAP {{{keys}}})
                 ELSE individual_enriched.field_provenance END AS field_provenance
        )
        FROM individual_enriched LEFT JOIN coarse_polity ON coarse_polity.qid = individual_enriched.entity.qid
        WHERE {{inside}}
        """,
        [dates] * 6 + [polities] * (len(STAGES) + 1),
    )


def write(connection):
    rewrite_individual_enriched(connection, *rows_sql(connection))


def show_sample(connection):
    """The rewritten rows of three sampled individuals with all three stages, nothing written."""
    rows, parameters = rows_sql(connection)
    inside = "individual_enriched.entity.qid IN (SELECT qid FROM coarse_polity WHERE len(active_life_polity) > 0 ORDER BY qid LIMIT 3)"
    query = f"SELECT entity.qid, birth_date.coarse_label, death_date.coarse_label, start_of_active_life.coarse_label, end_of_active_life.coarse_label, start_of_active_life.source, start_of_active_life.year, end_of_active_life.year, list_transform(pre_active_life_polity, m -> m.polity.name), list_transform(active_life_polity, m -> (m.polity.name, m.seshat)), list_transform(post_active_life_polity, m -> m.polity.name) FROM ({rows.replace('{inside}', inside)})"
    for row in connection.execute(query, parameters).fetchall():
        print(row)


def check(connection):
    kept_years, individuals, pre, with_polity, post, estimated_years, century_lives = connection.execute(f"""
        SELECT count(*) FILTER (WHERE (is_coarse(birth_date) AND birth_date.year IS NOT NULL) OR (is_coarse(death_date) AND death_date.year IS NOT NULL)),
               count(*), count(*) FILTER (WHERE len(pre_active_life_polity) > 0), count(*) FILTER (WHERE len(active_life_polity) > 0),
               count(*) FILTER (WHERE len(post_active_life_polity) > 0),
               count(*) FILTER (WHERE start_of_active_life.source = 'estimated' AND start_of_active_life.year IS NOT NULL),
               count(*) FILTER (WHERE start_of_active_life.source = 'estimated from the century dates')
        FROM individual_enriched WHERE has_coarse_date(individual_enriched.birth_date, individual_enriched.death_date)
    """).fetchone()
    assert kept_years == 0, f"{kept_years:,} coarse dates keep a year"
    assert estimated_years == 0, f"{estimated_years:,} estimated active lives keep a year"
    print(f"{individuals:,} individuals with a coarse date: {pre:,} with a pre-active, {with_polity:,} with an active, {post:,} with a post-active polity, {century_lives:,} with a century-level active life from their century dates")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=0, help="match this many individuals and show three, write nothing")
    sample = parser.parse_args().sample
    DATES.announce()
    POLITIES.announce()
    started = time.time()
    connection = open_database(read_only=bool(sample))
    connection.execute(f"SET memory_limit='8GB'; SET threads=4; SET preserve_insertion_order=false; SET temp_directory='{SCRATCH}'")
    match_people(connection, sample)
    if sample:
        show_sample(connection)
        return
    connection.begin()
    write(connection)
    check(connection)
    connection.commit()
    connection.execute("CHECKPOINT")
    connection.close()
    print(f"done in {(time.time() - started) / 60:.1f} min")


if __name__ == "__main__":
    main()
