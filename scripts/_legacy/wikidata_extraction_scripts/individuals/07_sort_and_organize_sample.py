"""
Sort sample database tables by count and organize data.
- Sorts all count tables by count (descending)
- Sorts individuals by n_identifiers (descending)
- Creates properties definition table
"""

import sqlite3
import sys

sys.path.insert(0, '..')
from wikidata_api import sparql_query, set_endpoint


def sort_count_tables(db_path: str):
    """Sort all count tables by count descending."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    count_tables = [
        'SAMPLE_nationalities', 'SAMPLE_birthcities', 'SAMPLE_deathcities',
        'SAMPLE_writing_languages', 'SAMPLE_positions_held', 'SAMPLE_social_classifications',
        'SAMPLE_time_periods', 'SAMPLE_manners_of_death', 'SAMPLE_fields_of_work',
        'SAMPLE_occupations', 'SAMPLE_genders', 'SAMPLE_identifiers'
    ]

    print('Sorting tables by count...')
    for table in count_tables:
        try:
            c.execute(f'SELECT * FROM {table} ORDER BY count DESC')
            rows = cursor.fetchall()
            if not rows:
                continue

            c.execute(f'PRAGMA table_info({table})')
            cols = ','.join([col[1] for col in c.fetchall()])
            placeholders = ','.join(['?'] * len(rows[0]))

            c.execute(f'DELETE FROM {table}')
            for row in rows:
                c.execute(f'INSERT INTO {table} ({cols}) VALUES ({placeholders})', row)
            print(f'  {table}: {len(rows)} rows')
        except Exception as e:
            print(f'  {table}: skipped ({e})')

    conn.commit()
    conn.close()
    print('Done sorting!')


def sort_individuals_by_identifiers(db_path: str):
    """Sort individuals table by n_identifiers descending."""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    print('Sorting individuals by n_identifiers...')
    c.execute('SELECT * FROM SAMPLE_individuals_information ORDER BY COALESCE(n_identifiers, 0) DESC')
    rows = c.fetchall()

    c.execute('PRAGMA table_info(SAMPLE_individuals_information)')
    cols = [col[1] for col in c.fetchall()]
    col_names = ','.join(cols)
    placeholders = ','.join(['?'] * len(cols))

    c.execute('DELETE FROM SAMPLE_individuals_information')
    for row in rows:
        c.execute(f'INSERT INTO SAMPLE_individuals_information ({col_names}) VALUES ({placeholders})', row)

    conn.commit()
    conn.close()
    print(f'Sorted {len(rows)} individuals')


def create_properties_definition_table(db_path: str):
    """
    Create a table with definitions of all Wikidata properties used in the database.
    """
    # Properties used in extraction queries
    properties = {
        'P21': 'gender',
        'P569': 'birthdate',
        'P570': 'deathdate',
        'P1317': 'floruit',
        'P27': 'nationality',
        'P19': 'birthcity',
        'P20': 'deathcity',
        'P6886': 'writing language',
        'P39': 'position held',
        'P3716': 'social classification',
        'P2348': 'time period',
        'P1196': 'manner of death',
        'P101': 'field of work',
        'P106': 'occupation',
        'P31': 'instance of',
    }

    print(f'Fetching definitions for {len(properties)} properties from Wikidata...')
    set_endpoint('https://query.wikidata.org/sparql')

    # Query Wikidata for labels and descriptions
    values = ' '.join(f'wd:{p}' for p in properties.keys())
    query = f'''
    SELECT ?prop ?label ?desc WHERE {{
      VALUES ?prop {{ {values} }}
      OPTIONAL {{ ?prop rdfs:label ?label. FILTER(LANG(?label) = "en") }}
      OPTIONAL {{ ?prop schema:description ?desc. FILTER(LANG(?desc) = "en") }}
    }}
    '''

    rows = sparql_query(query)
    prop_data = {}
    for row in rows:
        pid = row.get('prop', '').split('/')[-1]
        if pid:
            prop_data[pid] = {
                'label': row.get('label', ''),
                'description': row.get('desc', '')
            }

    # Create table
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    c.execute('DROP TABLE IF EXISTS SAMPLE_properties_definition')
    c.execute('''CREATE TABLE SAMPLE_properties_definition (
        property_id TEXT PRIMARY KEY,
        property_name TEXT,
        used_for TEXT,
        description TEXT,
        wikidata_url TEXT
    )''')

    for pid, usage in properties.items():
        data = prop_data.get(pid, {})
        c.execute('''INSERT INTO SAMPLE_properties_definition
                     (property_id, property_name, used_for, description, wikidata_url)
                     VALUES (?, ?, ?, ?, ?)''',
                  (pid, data.get('label', ''), usage, data.get('description', ''),
                   f'https://www.wikidata.org/wiki/Property:{pid}'))

    conn.commit()

    print('\nSAMPLE_properties_definition:')
    c.execute('SELECT property_id, property_name, used_for FROM SAMPLE_properties_definition')
    for row in c.fetchall():
        print(f'  {row[0]}: {row[1]} ({row[2]})')

    conn.close()
    print('Done!')


if __name__ == "__main__":
    import os
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base_dir, 'data/sample/individuals_qlever_sample.db')

    sort_count_tables(db_path)
    sort_individuals_by_identifiers(db_path)
    create_properties_definition_table(db_path)
