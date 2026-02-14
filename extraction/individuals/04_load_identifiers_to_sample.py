"""
Load identifiers from extracted batches into the sample database.
Also creates SAMPLE_identifiers table with property counts and descriptions.
"""

import sqlite3
import json
import sys
from glob import glob
from tqdm import tqdm

sys.path.insert(0, '..')
from wikidata_api import sparql_query, set_endpoint


def load_identifiers_to_sample(
    sample_db_path: str,
    identifiers_batches_dir: str,
    fetch_descriptions: bool = True
):
    """
    Load identifiers for sample individuals from extracted batch files.

    Args:
        sample_db_path: Path to the sample SQLite database
        identifiers_batches_dir: Path to directory containing batch JSON files
        fetch_descriptions: Whether to fetch property descriptions from Wikidata
    """
    conn = sqlite3.connect(sample_db_path)
    c = conn.cursor()

    # Get sample individual IDs
    c.execute('SELECT wikidata_id, name FROM SAMPLE_individuals_information')
    sample_ids = {row[0]: row[1] for row in c.fetchall()}
    print(f'Sample individuals: {len(sample_ids):,}')

    # Load all identifiers from batches
    batch_files = sorted(glob(f'{identifiers_batches_dir}/batch_*.json'))
    print(f'Batch files: {len(batch_files)}')

    all_identifiers = []
    properties = {}

    for bf in tqdm(batch_files, desc='Loading batches'):
        with open(bf) as f:
            for rec in json.load(f):
                wiki_id = rec['wikidata_id']
                if wiki_id in sample_ids:
                    name = sample_ids[wiki_id] or rec.get('name', '')
                    for ident in rec.get('identifiers', []):
                        all_identifiers.append((
                            wiki_id, name,
                            ident['property_id'],
                            ident['property_name'],
                            ident['value']
                        ))
                        properties[ident['property_id']] = ident['property_name']

    print(f'Found {len(all_identifiers):,} identifiers, {len(properties)} properties')

    # Create/clear tables
    c.execute('DROP TABLE IF EXISTS SAMPLE_individuals_identifiers')
    c.execute('''CREATE TABLE SAMPLE_individuals_identifiers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wikidata_id TEXT,
        name TEXT,
        property_id TEXT,
        property_name TEXT,
        value TEXT
    )''')

    c.executemany('''INSERT INTO SAMPLE_individuals_identifiers
                     (wikidata_id, name, property_id, property_name, value)
                     VALUES (?,?,?,?,?)''', all_identifiers)

    # Create SAMPLE_identifiers with counts
    c.execute('DROP TABLE IF EXISTS SAMPLE_identifiers')
    c.execute('''CREATE TABLE SAMPLE_identifiers (
        property_id TEXT PRIMARY KEY,
        property_name TEXT,
        count INTEGER,
        description TEXT
    )''')

    c.execute('''INSERT INTO SAMPLE_identifiers (property_id, property_name, count)
                 SELECT property_id, property_name, COUNT(*) as cnt
                 FROM SAMPLE_individuals_identifiers
                 GROUP BY property_id
                 ORDER BY cnt DESC''')

    # Add n_identifiers to individuals
    c.execute('PRAGMA table_info(SAMPLE_individuals_information)')
    cols = [col[1] for col in c.fetchall()]
    if 'n_identifiers' not in cols:
        c.execute('ALTER TABLE SAMPLE_individuals_information ADD COLUMN n_identifiers INTEGER DEFAULT 0')

    c.execute('SELECT wikidata_id, COUNT(*) FROM SAMPLE_individuals_identifiers GROUP BY wikidata_id')
    for wiki_id, count in c.fetchall():
        c.execute('UPDATE SAMPLE_individuals_information SET n_identifiers = ? WHERE wikidata_id = ?',
                  (count, wiki_id))

    conn.commit()
    print(f'Inserted {len(all_identifiers):,} identifiers')

    # Fetch descriptions from Wikidata
    if fetch_descriptions:
        print('Fetching property descriptions from Wikidata...')
        set_endpoint('https://query.wikidata.org/sparql')

        prop_ids = list(properties.keys())
        BATCH = 50

        for i in tqdm(range(0, len(prop_ids), BATCH), desc='Fetching descriptions'):
            batch = prop_ids[i:i+BATCH]
            values = ' '.join(f'wd:{p}' for p in batch)
            query = f'''
            SELECT ?prop ?desc WHERE {{
              VALUES ?prop {{ {values} }}
              OPTIONAL {{ ?prop schema:description ?desc. FILTER(LANG(?desc) = "en") }}
            }}
            '''
            try:
                rows = sparql_query(query)
                for row in rows:
                    pid = row.get('prop', '').split('/')[-1]
                    desc = row.get('desc', '')
                    if pid and desc:
                        c.execute('UPDATE SAMPLE_identifiers SET description = ? WHERE property_id = ?',
                                  (desc, pid))
            except Exception as e:
                print(f'Error: {e}')

        conn.commit()
        print('Descriptions added')

    conn.close()
    print('Done!')


if __name__ == "__main__":
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    load_identifiers_to_sample(
        sample_db_path=os.path.join(base_dir, 'data/sample/individuals_qlever_sample.db'),
        identifiers_batches_dir=os.path.join(base_dir, 'data/extracted/individuals_qlever/identifiers/json_batches'),
        fetch_descriptions=True
    )
