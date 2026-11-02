"""Life-stage polities of every individual with a birth and a death year, written as
parquets of 1,000,000 individuals for ingestion into the enriched database.

Same method as 01_life_stage_polities.ipynb (stage limits at the first and last work,
dated or estimated, else ages 30 and 60; field priorities; URL then coordinates; smallest
Cliopatria polity); the notebook explores it on a sample."""
import json
import sys
import time
from pathlib import Path
from urllib.parse import unquote

import duckdb
import polars as pl
from shapely import STRtree, make_valid, points
from shapely.geometry import shape
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / 'data' / 'cultura' / 'cultura_enriched_v3.2.duckdb'  # read only
LIFE_LOCATIONS = ROOT / 'data' / 'raw_data_from_wikidata' / 'wikidata_extraction_scripts_v2' / 'life_locations'
CLIOPATRIA = ROOT / 'data' / 'cliopatria_data' / 'cliopatria_V2' / 'cliopatria_polities_only_v3.geojson'
OUT_DIR = ROOT / 'data' / 'enriched_parquets' / 'individual_life_stage_polities'
BATCH_SIZE = 1_000_000

PROPERTIES = {'P937': 'work_location', 'P551': 'residence', 'P108': 'employer', 'P69': 'educated_at', 'P39': 'position_held'}
SOURCES = {
    'place_of_birth': 'birthplace', 'educated_at': 'educated at', 'residence': 'residence', 'country_of_citizenship': 'citizenship',
    'work_location': 'work location', 'employer': 'employer', 'position_held': 'position held', 'place_of_death': 'deathplace',
}
STAGES = ['early', 'active', 'late']
ACTIVE_AGE, LATE_AGE = 30, 60
MIN_STAGE = 5
RULES = {
    'early': [('place_of_birth', 'certain'), ('educated_at', 'certain'), ('residence', 'unsure'), ('country_of_citizenship', 'unsure'), ('work_location', 'unsure'), ('employer', 'unsure'), ('position_held', 'unsure'), ('place_of_death', 'unsure')],
    'active': [('work_location', 'certain'), ('employer', 'certain'), ('position_held', 'certain'), ('residence', 'certain'), ('country_of_citizenship', 'unsure'), ('place_of_death', 'unsure'), ('educated_at', 'unsure'), ('place_of_birth', 'unsure')],
    'late': [('place_of_death', 'certain'), ('residence', 'unsure'), ('work_location', 'unsure'), ('position_held', 'unsure'), ('employer', 'unsure'), ('country_of_citizenship', 'unsure'), ('educated_at', 'unsure'), ('place_of_birth', 'unsure')],
}
METHODS = ['URL', 'coordinates']

DATED = '''
    SELECT entity.qid AS qid, entity.label_en AS name, birth_date.year AS birth, death_date.year AS death,
           coalesce(first_work_date.year < last_work_date.year, false) AS dated_works,
           CASE WHEN dated_works THEN first_work_date.year END AS first_work,
           CASE WHEN dated_works THEN last_work_date.year END AS last_work
    FROM individual_enriched
    WHERE birth_date.year IS NOT NULL AND death_date.year IS NOT NULL
'''


def log(message):
    print(f'{time.strftime("%H:%M:%S")}  {message}', flush=True)


def load_people(connection, qids):
    connection.register('batch_qids', pl.DataFrame({'qid': qids}))
    return connection.sql(f'''
        WITH dated AS ({DATED})
        SELECT dated.*,
               [individual.place_of_birth.entity.qid] AS place_of_birth,
               [individual.place_of_death.entity.qid] AS place_of_death,
               list_transform(individual.country_of_citizenship, country -> country.entity.qid) AS country_of_citizenship,
               list_transform(individual.work_location, place -> place.entity.qid) AS work_location,
               list_transform(individual.residence, place -> place.entity.qid) AS residence,
               list_transform(individual.employer, institution -> institution.entity.qid) AS employer,
               list_transform(individual.educated_at, institution -> institution.entity.qid) AS educated_at,
               list_distinct(list_transform(individual.position_held, held -> held.position.qid)) AS position_held
        FROM dated JOIN individual ON individual.entity.qid = dated.qid
        WHERE dated.qid IN (SELECT qid FROM batch_qids)
    ''').pl().with_columns(pl.col('place_of_birth', 'place_of_death').list.drop_nulls())


def stage_limits(person):
    birth, death = person['birth'], person['death']
    if person['dated_works']:
        first, last = person['first_work'], person['last_work']
    else:
        first, last = birth + ACTIVE_AGE, birth + LATE_AGE
    limits = {'early': [birth, min(first, death)], 'active': [first, min(last, death)], 'late': [last, death]}
    limits = {stage: bounds for stage, bounds in limits.items() if bounds[0] <= bounds[1]}
    early, active, late = (limits.get(stage) for stage in STAGES)
    if late and active and late[1] - late[0] < MIN_STAGE:
        active[1] = limits.pop('late')[1]
    if early and active and early[1] - early[0] < MIN_STAGE:
        active[0] = limits.pop('early')[0]
    if active and early and 'late' not in limits and active[1] - active[0] < MIN_STAGE:
        early[1] = limits.pop('active')[1]
    if 'late' not in limits:
        limits['late'] = [death, death]  # no late stage: the death year alone
    return limits


def article(url):
    return unquote(url.rsplit('/wiki/', 1)[-1]).replace('_', ' ')


class Locations:
    """Wikipedia articles, coordinates and labels of every spot, and the Cliopatria territories holding them."""

    def __init__(self, connection):
        self.targets = json.loads((LIFE_LOCATIONS / 'targets.json').read_text())
        place_rows = connection.sql('SELECT entity.qid, entity.label_en, sitelink.url, coordinates.longitude, coordinates.latitude FROM place').fetchall()
        self.label = {qid: target['label_en'] for qid, target in self.targets.items() if target['label_en']}
        self.link = {qid: article(url) for qid, _, url, _, _ in place_rows if url}
        self.point = {qid: (longitude, latitude) for qid, _, _, longitude, latitude in place_rows if latitude is not None}
        for qid, name, _, _, _ in place_rows:
            if name:
                self.label.setdefault(qid, name)
        for target in self.targets.values():
            for spot, coordinates in target['jurisdiction'].items():
                if coordinates:
                    self.point.setdefault(spot, (coordinates['longitude'], coordinates['latitude']))
        self.institution_location = dict(connection.sql('SELECT entity.qid, location.entity.qid FROM institution WHERE location IS NOT NULL').fetchall())

        features = json.loads(CLIOPATRIA.read_text())['features']
        territories = pl.DataFrame([{key: feature['properties'][key] for key in ['Name', 'FromYear', 'ToYear', 'Wikipedia']} for feature in features])
        self.tree = STRtree(make_valid([shape(feature['geometry']) for feature in features]))
        self.name_of, self.start_of, self.end_of = territories['Name'].to_list(), territories['FromYear'].to_list(), territories['ToYear'].to_list()
        self.by_link = {}
        for index, title in enumerate(territories['Wikipedia']):
            if title:
                self.by_link.setdefault(title.replace('_', ' '), []).append(index)
        self.parents = {}
        for feature in features:
            properties = feature['properties']
            for parent in filter(None, properties['MemberOf'].split(';')):
                self.parents.setdefault(properties['Name'], set()).add(parent)
            for child in filter(None, properties['Components'].split(';')):
                self.parents.setdefault(child, set()).add(properties['Name'])
        self.ancestors_of = {}
        self.containing = {}
        self.tested = set()

    def spots(self, source, qid):
        if source in ('employer', 'educated_at'):
            return [self.institution_location[qid]] if qid in self.institution_location else []
        if source == 'position_held':
            return list(self.targets.get(qid, {}).get('jurisdiction', {}))
        return [qid]

    def add_spots(self, people):
        """Test against the polygons the spots of these people not tested in an earlier batch."""
        new = sorted({spot for source in SOURCES for qids in people[source] for qid in qids for spot in self.spots(source, qid) if spot in self.point} - self.tested)
        if new:
            spot_index, territory_index = self.tree.query(points([self.point[spot] for spot in new]), predicate='within')
            for spot, territory in zip(spot_index, territory_index):
                self.containing.setdefault(new[spot], []).append(int(territory))
        self.tested.update(new)
        return len(new)

    def ancestors(self, name):
        if name not in self.ancestors_of:
            found, todo = set(), [name]
            while todo:
                for parent in self.parents.get(todo.pop(), ()):
                    if parent not in found:
                        found.add(parent)
                        todo.append(parent)
            self.ancestors_of[name] = found
        return self.ancestors_of[name]

    def smallest_polities(self, indices, start, end):
        years = {}
        for index in indices:
            low, high = max(self.start_of[index], start), min(self.end_of[index], end)
            if low <= high:
                years.setdefault(self.name_of[index], set()).update(range(low, high + 1))
        above = {parent for name in years for parent in self.ancestors(name)}
        return {name: len(covered) for name, covered in years.items() if name not in above}

    def locate(self, source, qid, start, end):
        for method in METHODS:
            for spot in self.spots(source, qid):
                indices = self.by_link.get(self.link.get(spot), []) if method == 'URL' else self.containing.get(spot, [])
                found = self.smallest_polities(indices, start, end)
                if found:
                    return method, spot, found
        return None

    def assign(self, person, stage, start, end):
        for source, certainty in RULES[stage]:
            located = [hit for qid in person[source] if (hit := self.locate(source, qid, start, end))]
            if located:
                polities = {}
                for _, _, found in located:
                    polity = max(found, key=found.get)
                    polities[polity] = max(found[polity], polities.get(polity, 0))
                ranked = sorted(polities, key=polities.get, reverse=True)
                return {
                    'polities': [polity.strip('()') for polity in ranked], 'polity_years': [polities[polity] for polity in ranked],
                    'wikidata_field': SOURCES[source], 'certainty': certainty,
                    'method': 'URL' if any(method == 'URL' for method, _, _ in located) else 'coordinates',
                    'location': '; '.join(dict.fromkeys(self.label.get(spot, spot) for _, spot, _ in located)),
                }
        return {'polities': [], 'polity_years': [], 'wikidata_field': None, 'certainty': 'none', 'method': None, 'location': None}


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    qids = [qid for (qid,) in connection.sql(f'SELECT qid FROM ({DATED}) ORDER BY qid').fetchall()]
    batches = [qids[start:start + BATCH_SIZE] for start in range(0, len(qids), BATCH_SIZE)]
    log(f'{len(qids):,} individuals with a birth and a death year, {len(batches)} batches of {BATCH_SIZE:,}')
    locations = Locations(connection)
    log('places and Cliopatria loaded')

    for number, batch in enumerate(batches):
        path = OUT_DIR / f'batch_{number:02d}.parquet'
        if path.exists():
            log(f'batch {number}: already written, skipped')
            continue
        people = load_people(connection, batch)
        log(f'batch {number}: {people.height:,} individuals, {locations.add_spots(people):,} new spots tested against the polygons')
        rows = []
        for person in tqdm(people.iter_rows(named=True), total=people.height, desc=f'batch {number}', mininterval=10):
            for stage, (start, end) in stage_limits(person).items():
                rows.append({'qid': person['qid'], 'stage': stage, 'start_year': start, 'end_year': end, **locations.assign(person, stage, start, end)})
        export = pl.DataFrame(rows, schema_overrides={'polities': pl.List(pl.String), 'polity_years': pl.List(pl.Int64), 'wikidata_field': pl.String, 'method': pl.String, 'location': pl.String})
        export.sort('qid', pl.col('stage').cast(pl.Enum(STAGES))).write_parquet(path)
        log(f'batch {number}: {export.height:,} stages written to {path.relative_to(ROOT)}')
    log('done')


if __name__ == '__main__':
    sys.exit(main())
