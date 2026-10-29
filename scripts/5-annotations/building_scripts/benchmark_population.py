"""Cultura individuals covered by at least one scholarly biography dictionary, with their region and century.

Membership comes from the individual_identifier table of the Cultura database, or from the
Wikidata SPARQL endpoint for the properties missing there; for the Deutsche Biographie, only the
individuals Wikidata describes by the NDB or the ADB (P1343), as the other identifiers lead to an
index page without an article. Individuals need an English label, a birth year and a death year.
The region is read from the birthplace (else the first country of citizenship), located in a
Natural Earth country and grouped into world regions (present-day borders).
Saved to scripts/5-annotations/benchmark/benchmark_population.parquet, one row per individual and dictionary.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/benchmark_population.py
"""

import csv
import io
import json
import time
from pathlib import Path

import duckdb
import polars as pl
import requests
from shapely import STRtree, points
from shapely.geometry import shape
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
COUNTRIES = ROOT / "data" / "ne_110m_admin_0_countries.geojson"
OUT = ROOT / "scripts" / "5-annotations" / "benchmark" / "benchmark_population.parquet"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "cultura-database research (cdedampierre@bunka.ai)", "Accept": "text/tab-separated-values"}

IN_CULTURA = {"treccani": "P1986", "dwb": "P1648", "sbl": "P3217", "iranica": "P3021", "dcb": "P2753",
              "sep": "P3123", "mactutor": "P1563", "catholic_encyclopedia": "P3241"}
IN_WIKIDATA = {
    "oebl": "SELECT ?h ?id WHERE { ?h wdt:P6194 ?id }",
    "nbl": "SELECT ?h ?id WHERE { ?h wdt:P5080 ?id }",
    "dbl": "SELECT ?h ?id WHERE { ?h wdt:P8341 ?id }",
    "encykorea": "SELECT ?h ?id WHERE { ?h wdt:P9475 ?id }",
    "deutsche_biographie": "SELECT DISTINCT ?h ?id WHERE { VALUES ?source { wd:Q222784 wd:Q590208 } ?h wdt:P1343 ?source ; wdt:P7902 ?id }",
}
REGIONS = {
    "Western Europe": "Western Europe", "Northern Europe": "Northern Europe", "Southern Europe": "Southern Europe",
    "Eastern Europe": "Eastern Europe", "Western Asia": "Middle East & North Africa", "Northern Africa": "Middle East & North Africa",
    "Central Asia": "South & Central Asia", "Southern Asia": "South & Central Asia", "Eastern Asia": "East Asia",
    "South-Eastern Asia": "Southeast Asia", "Eastern Africa": "Sub-Saharan Africa", "Middle Africa": "Sub-Saharan Africa",
    "Southern Africa": "Sub-Saharan Africa", "Western Africa": "Sub-Saharan Africa", "Northern America": "North America",
    "Central America": "Latin America", "Caribbean": "Latin America", "South America": "Latin America",
    "Australia and New Zealand": "Oceania", "Melanesia": "Oceania", "Micronesia": "Oceania", "Polynesia": "Oceania",
}


def wikidata(sparql):
    for attempt in range(5):
        response = requests.post(WIKIDATA_SPARQL, data={"query": sparql}, headers=HEADERS, timeout=600)
        if response.status_code != 429:
            break
        time.sleep(int(response.headers.get("Retry-After", 60)))
    response.raise_for_status()
    rows = list(csv.reader(io.StringIO(response.text), delimiter="\t"))[1:]
    return [(row[0].rsplit("/", 1)[-1].rstrip(">"), row[1].strip('"')) for row in rows]


def memberships(connection):
    rows = []
    for key, pid in tqdm(IN_CULTURA.items(), desc="identifiers in Cultura"):
        rows += [(key, qid, value) for qid, value in connection.execute("SELECT qid, value FROM individual_identifier WHERE pid = ?", [pid]).fetchall()]
    for key, sparql in tqdm(IN_WIKIDATA.items(), desc="identifiers from Wikidata"):
        rows += [(key, qid, value) for qid, value in wikidata(sparql)]
    return pl.DataFrame(rows, schema=["dictionary", "qid", "dictionary_id"], orient="row").unique(["dictionary", "qid"])


def individuals(connection, qids):
    connection.execute("CREATE OR REPLACE TEMP TABLE members (qid VARCHAR)")
    connection.executemany("INSERT INTO members VALUES (?)", [(qid,) for qid in qids])
    return connection.execute("""
        SELECT individual.entity.qid AS qid, individual.entity.label_en AS label,
               individual.birth_date[1].year AS birth_year, individual.death_date[1].year AS death_year,
               coalesce(birthplace.coordinates.latitude, citizenship.coordinates.latitude) AS latitude,
               coalesce(birthplace.coordinates.longitude, citizenship.coordinates.longitude) AS longitude,
               CASE WHEN birthplace.coordinates.latitude IS NOT NULL THEN 'birthplace'
                    WHEN citizenship.coordinates.latitude IS NOT NULL THEN 'country of citizenship' END AS located_by
        FROM individual
        JOIN members ON members.qid = individual.entity.qid
        LEFT JOIN place AS birthplace ON birthplace.entity.qid = individual.place_of_birth.entity.qid
        LEFT JOIN place AS citizenship ON citizenship.entity.qid = individual.country_of_citizenship[1].entity.qid
        WHERE individual.entity.label_en IS NOT NULL
          AND individual.birth_date[1].year IS NOT NULL AND individual.death_date[1].year IS NOT NULL
    """).pl()


def regions(people):
    countries = json.loads(COUNTRIES.read_text(encoding="utf-8"))["features"]
    shapes = [shape(country["geometry"]) for country in countries]
    tree = STRtree(shapes)
    located = people.filter(pl.col("latitude").is_not_null())
    nearest = tree.nearest(points(located["longitude"].to_numpy(), located["latitude"].to_numpy()))
    found = pl.DataFrame({
        "qid": located["qid"],
        "country": [countries[i]["properties"]["NAME"] for i in nearest],
        "region": [REGIONS.get(countries[i]["properties"]["SUBREGION"], "Other") for i in nearest],
    })
    return people.join(found, on="qid", how="left").with_columns(pl.col("region").fill_null("Unknown"))


def main():
    connection = duckdb.connect(str(DB), read_only=True)
    members = memberships(connection)
    print(f"{len(members):,} dictionary entries, {members['qid'].n_unique():,} distinct individuals")
    people = regions(individuals(connection, members["qid"].unique().to_list()).unique("qid"))
    people = people.with_columns(century=(pl.col("birth_year") // 100 + 1))
    population = members.join(people, on="qid")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    population.write_parquet(OUT)
    print(f"{population['qid'].n_unique():,} individuals with an English label, a birth and a death year, saved to {OUT.relative_to(ROOT)}")
    print(population.unique("qid")["region"].value_counts(sort=True))


if __name__ == "__main__":
    main()
