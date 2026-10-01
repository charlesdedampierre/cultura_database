"""
Fetch property descriptions from Wikidata for a list of property IDs.
Can be used to add descriptions to any table with property_id column.
"""

import sqlite3
import sys
from tqdm import tqdm

sys.path.insert(0, '..')
from wikidata_api import sparql_query, set_endpoint


def fetch_property_descriptions(property_ids: list) -> dict:
    """
    Fetch labels and descriptions for a list of Wikidata property IDs.

    Args:
        property_ids: List of property IDs (e.g., ['P214', 'P213', ...])

    Returns:
        dict: {property_id: {'label': str, 'description': str}}
    """
    set_endpoint('https://query.wikidata.org/sparql')

    results = {}
    BATCH = 50

    for i in tqdm(range(0, len(property_ids), BATCH), desc='Fetching'):
        batch = property_ids[i:i+BATCH]
        values = ' '.join(f'wd:{p}' for p in batch)
        query = f'''
        SELECT ?prop ?label ?desc WHERE {{
          VALUES ?prop {{ {values} }}
          OPTIONAL {{ ?prop rdfs:label ?label. FILTER(LANG(?label) = "en") }}
          OPTIONAL {{ ?prop schema:description ?desc. FILTER(LANG(?desc) = "en") }}
        }}
        '''
        try:
            rows = sparql_query(query)
            for row in rows:
                pid = row.get('prop', '').split('/')[-1]
                if pid:
                    results[pid] = {
                        'label': row.get('label', ''),
                        'description': row.get('desc', '')
                    }
        except Exception as e:
            print(f'Error fetching batch {i}: {e}')

    return results


def add_descriptions_to_table(
    db_path: str,
    table_name: str,
    property_id_column: str = 'property_id',
    description_column: str = 'description'
):
    """
    Add descriptions to a table that has a property_id column.

    Args:
        db_path: Path to SQLite database
        table_name: Name of the table to update
        property_id_column: Name of the column containing property IDs
        description_column: Name of the column to store descriptions
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Check if description column exists, add if not
    c.execute(f'PRAGMA table_info({table_name})')
    cols = [col[1] for col in c.fetchall()]
    if description_column not in cols:
        c.execute(f'ALTER TABLE {table_name} ADD COLUMN {description_column} TEXT')

    # Get all property IDs
    c.execute(f'SELECT DISTINCT {property_id_column} FROM {table_name}')
    prop_ids = [row[0] for row in c.fetchall()]
    print(f'Fetching descriptions for {len(prop_ids)} properties...')

    # Fetch descriptions
    descriptions = fetch_property_descriptions(prop_ids)

    # Update table
    for pid, data in descriptions.items():
        c.execute(f'UPDATE {table_name} SET {description_column} = ? WHERE {property_id_column} = ?',
                  (data['description'], pid))

    conn.commit()
    conn.close()
    print(f'Added descriptions to {len(descriptions)} properties in {table_name}')


if __name__ == "__main__":
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base_dir, 'data/sample/individuals_qlever_sample.db')

    add_descriptions_to_table(
        db_path=db_path,
        table_name='SAMPLE_identifiers',
        property_id_column='property_id',
        description_column='description'
    )
