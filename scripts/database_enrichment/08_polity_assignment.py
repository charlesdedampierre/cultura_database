from dataclasses import dataclass

from shapely import STRtree, points
from shapely.geometry import shape

import json

from tqdm import tqdm

from common import D, Enrichment, ROOT, as_json, open_database, provenance_column, stage
from pydantic_to_duckdb_schema import columns_of

TESTS = (
    ("country_of_citizenship", "wikipedia_article_shared_with_the_polity"),
    ("birthplace", "polygon_containing_the_place"),
    ("birthplace", "wikipedia_article_shared_with_the_polity"),
    ("deathplace", "polygon_containing_the_place"),
    ("deathplace", "wikipedia_article_shared_with_the_polity"),
    ("country_of_citizenship", "polygon_containing_the_place"),
)

METHOD = {
    "polygon_containing_the_place": "polygon",
    "wikipedia_article_shared_with_the_polity": "url",
}

COUNT_YEARS_ONCE = True

BATCH = 200_000

ENRICHMENT = Enrichment(
    reads=("Polity.world", "Polity.child_polities", "Polity.meta_polities", "Individual.place_of_birth", "Individual.place_of_death", "Individual.country_of_citizenship", "Place.coordinates", "Place.sitelink", "Polity.territories", "Polity.sitelink", "IndividualEnriched.peak_productivity"),
    writes=("IndividualEnriched.polity", "IndividualEnriched.polity_count"),
    rule="Every polity whose ground the individual stood on while they were at work. A place is tested against the territories a polity held during the peak activity window, by the tests in the order of TESTS: the citizenship's Wikipedia article shared with the polity, then the birthplace and the deathplace each by the polygon containing it and then by article, and last the polygon containing the citizenship — last because a state's coordinates are one point near its middle, which puts anyone with Italian citizenship in the Papal States. The first test that matches anything ends the search. Within each test the sub-polities, those without child_polities, are tried first, and a meta polity is matched only when no sub-polity is. years_spent_in_polity counts each calendar year of the window once, however many territories of that polity cover it. Each match carries the polity's meta_polities, so the meta polity is read off the match.",
    inputs=("IndividualEnriched.peak_productivity",),
    answers=ROOT / "data" / "cultura" / "cultura_v2.duckdb",
)


@dataclass(frozen=True)
class Territory:
    polity_id: int
    polity_name: str
    start_year: int
    end_year: int
    is_meta: bool


@dataclass(frozen=True)
class Match:
    polity_id: int
    polity_name: str
    years: int
    method: str


def years_covered(territories, window_start, window_end):
    """The calendar years of the window a polity held, each counted once when COUNT_YEARS_ONCE and once per territory otherwise."""
    covered, summed = set(), 0
    for territory in territories:
        low = max(territory.start_year, window_start)
        high = min(territory.end_year, window_end)
        if low > high:
            continue
        covered.update(range(low, high + 1))
        summed += high - low + 1
    if not covered:
        return 0
    return len(covered) if COUNT_YEARS_ONCE else summed


def grouped_by_polity(territories, window_start, window_end, method):
    """One match per polity, whatever number of its territories the window touched."""
    by_polity = {}
    for territory in territories:
        by_polity.setdefault((territory.polity_id, territory.polity_name), []).append(territory)
    matches = []
    for (polity_id, name), found in by_polity.items():
        years = years_covered(found, window_start, window_end)
        if years:
            matches.append(Match(polity_id, name, years, method))
    return matches


def load_polities(connection):
    rows = connection.execute(
        """
        SELECT cliopatria_id, name, sitelink.url AS url, len(child_polities) > 0 AS is_meta,
               territory.start_year AS start_year, territory.end_year AS end_year,
               territory.geometry AS geometry
        FROM polity, unnest(territories) AS t(territory)
        WHERE territory.start_year IS NOT NULL AND territory.end_year IS NOT NULL
        """
    ).fetchall()
    geometries, territories, by_url = [], [], {}
    for polity_id, name, url, is_meta, start_year, end_year, geometry in rows:
        territory = Territory(polity_id, name, start_year, end_year, is_meta)
        geometries.append(shape(json.loads(geometry)))
        territories.append(territory)
        if url:
            by_url.setdefault(url, []).append(territory)
    return STRtree(geometries), territories, by_url


def main():
    ENRICHMENT.announce()
    print("tests, in the order they are tried:")
    for position, (location, phase) in enumerate(TESTS, start=1):
        print(f"   {position}. {phase} — {location}")
    print(f"\neach calendar year counted once per polity: {COUNT_YEARS_ONCE}\n")

    connection = open_database()
    tree, territories, by_url = load_polities(connection)
    worlds = dict(connection.execute("SELECT cliopatria_id, world FROM polity").fetchall())
    meta_polities = {polity_id: links for polity_id, links in connection.execute("SELECT cliopatria_id, meta_polities FROM polity").fetchall()}
    print(f"{len(territories):,} territories indexed\n")

    people = connection.cursor().execute(
        """
        SELECT individual.entity.qid AS qid,
               enriched.peak_productivity.start_year AS window_start,
               enriched.peak_productivity.end_year AS window_end,
               individual.place_of_death.entity.qid AS deathplace,
               individual.place_of_birth.entity.qid AS birthplace,
               list_transform(individual.country_of_citizenship, c -> c.entity.qid) AS country_of_citizenship
        FROM individual JOIN individual_enriched enriched ON enriched.entity.qid = individual.entity.qid
        WHERE enriched.peak_productivity.start_year IS NOT NULL
        """
    ).fetch_record_batch(BATCH)

    place_rows = connection.execute(
        "SELECT entity.qid, coordinates.latitude, coordinates.longitude, sitelink.url FROM place"
    ).fetchall()
    coordinates = {qid: (lon, lat) for qid, lat, lon, _ in place_rows if lat is not None}
    article = {qid: url for qid, _, _, url in place_rows if url}

    def locations(person, name):
        if name == "deathplace":
            return [person["deathplace"]] if person["deathplace"] else []
        if name == "birthplace":
            return [person["birthplace"]] if person["birthplace"] else []
        return list(person["country_of_citizenship"] or [])

    polygons_at = {}

    def touching_polygons(qid):
        if qid not in polygons_at:
            point = points(*coordinates[qid])
            polygons_at[qid] = [territories[i] for i in tree.query(point) if tree.geometries[i].contains(point)]
        return polygons_at[qid]

    assigned, counts, unmatched, total = {}, {}, 0, 0
    for person in tqdm((row for batch in people for row in batch.to_pylist()), desc="polity", unit=" people", mininterval=5):
        total += 1
        window_start, window_end = person["window_start"], person["window_end"]
        found = []
        for location, phase in TESTS:
            for qid in locations(person, location):
                if phase == "polygon_containing_the_place":
                    if qid not in coordinates:
                        continue
                    touching = touching_polygons(qid)
                else:
                    touching = by_url.get(article.get(qid), [])
                method = f"{METHOD[phase]}_of_{location}"
                found = grouped_by_polity([t for t in touching if not t.is_meta], window_start, window_end, method)
                found = found or grouped_by_polity([t for t in touching if t.is_meta], window_start, window_end, method)
                if found:
                    break
            if found:
                break
        if not found:
            unmatched += 1
            continue
        found.sort(key=lambda match: -match.years)
        counts[found[0].method] = counts.get(found[0].method, 0) + 1
        assigned[person["qid"]] = found

    matches = (
        {
            "qid": qid,
            "polity": [
                as_json(D.PolityMatch(
                    polity=D.Polity(cliopatria_id=match.polity_id, name=match.polity_name, world=worlds.get(match.polity_id) or (), meta_polities=meta_polities.get(match.polity_id) or ()),
                    years_spent_in_polity=match.years,
                    assignation_method=match.method,
                ))
                for match in found
            ],
            "polity_count": len(found),
            "provenance": as_json(ENRICHMENT.provenance()),
        }
        for qid, found in assigned.items()
    )
    stage(connection, "assigned", {
        "qid": "VARCHAR",
        "polity": columns_of(D.IndividualEnriched)["polity"],
        "polity_count": "BIGINT",
        "provenance": provenance_column(),
    }, matches)

    connection.execute(
        """
        CREATE OR REPLACE TABLE individual_enriched AS
        SELECT enriched.* REPLACE (
            assigned.polity AS polity,
            assigned.polity_count AS polity_count,
            CASE WHEN assigned.qid IS NULL THEN enriched.field_provenance
                 ELSE map_concat(enriched.field_provenance, MAP {'polity': assigned.provenance, 'polity_count': assigned.provenance})
            END AS field_provenance
        )
        FROM individual_enriched enriched LEFT JOIN assigned ON enriched.entity.qid = assigned.qid
        """
    )

    print(f"{total:,} individuals had a peak activity window; {len(assigned):,} matched a polity, {unmatched:,} matched none")
    print("\nby the location that settled it:")
    for method, count in sorted(counts.items(), key=lambda pair: -pair[1]):
        print(f"   {method:36} {count:>6,}")
    connection.close()


if __name__ == "__main__":
    main()
