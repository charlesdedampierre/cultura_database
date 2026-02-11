"""
Step 2: Create SQLite database from parsed JSON.

Input: data/cliopatria_parsed.json
Output: data/cliopatria.db
"""

import json
import sqlite3
from pathlib import Path
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).parent
INPUT_JSON = SCRIPT_DIR / "data" / "cliopatria_parsed.json"
OUTPUT_DB = SCRIPT_DIR / "data" / "cliopatria.db"


def create_database():
    """Create SQLite database with schema."""

    # Remove existing database
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()

    # Create polities table
    cursor.execute("""
        CREATE TABLE polities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT,
            wikipedia TEXT,
            wikipedia_url TEXT,
            wikidata_id TEXT,
            seshat_id TEXT,
            member_of TEXT,
            components TEXT
        )
    """)

    # Create polity_periods table
    cursor.execute("""
        CREATE TABLE polity_periods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            polity_id INTEGER NOT NULL,
            polity_name TEXT,
            from_year INTEGER,
            to_year INTEGER,
            area REAL,
            geometry TEXT,
            FOREIGN KEY (polity_id) REFERENCES polities(id)
        )
    """)

    # Create indexes
    cursor.execute("CREATE INDEX idx_polities_name ON polities(name)")
    cursor.execute("CREATE INDEX idx_polities_wikidata ON polities(wikidata_id)")
    cursor.execute("CREATE INDEX idx_periods_polity ON polity_periods(polity_id)")
    cursor.execute("CREATE INDEX idx_periods_polity_name ON polity_periods(polity_name)")
    cursor.execute("CREATE INDEX idx_periods_years ON polity_periods(from_year, to_year)")

    conn.commit()
    print("Database schema created")
    return conn


def load_data(conn):
    """Load data from JSON into database."""

    cursor = conn.cursor()

    with open(INPUT_JSON) as f:
        polities = json.load(f)

    print(f"Loading {len(polities)} polities...")

    polity_id_map = {}
    total_periods = 0

    # Insert polities
    for name, data in tqdm(polities.items(), desc="Inserting polities"):
        cursor.execute("""
            INSERT INTO polities (name, type, wikipedia, seshat_id, member_of, components)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            data.get('type'),
            data.get('wikipedia'),
            data.get('seshat_id'),
            data.get('member_of'),
            data.get('components')
        ))
        polity_id_map[name] = cursor.lastrowid
        total_periods += len(data.get('periods', []))

    conn.commit()

    # Insert periods
    print(f"Inserting {total_periods} periods...")

    for name, data in tqdm(polities.items(), desc="Inserting periods"):
        polity_id = polity_id_map[name]

        for period in data.get('periods', []):
            geometry_json = json.dumps(period.get('geometry')) if period.get('geometry') else None

            cursor.execute("""
                INSERT INTO polity_periods (polity_id, polity_name, from_year, to_year, area, geometry)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                polity_id,
                name,
                period.get('from_year'),
                period.get('to_year'),
                period.get('area'),
                geometry_json
            ))

    conn.commit()
    return len(polities), total_periods


def print_summary(conn, polity_count, period_count):
    """Print database summary."""

    cursor = conn.cursor()

    cursor.execute("SELECT MIN(from_year), MAX(to_year) FROM polity_periods")
    min_year, max_year = cursor.fetchone()

    print(f"\n{'='*60}")
    print("DATABASE CREATED")
    print(f"{'='*60}")
    print(f"Location: {OUTPUT_DB}")
    print(f"Polities: {polity_count:,}")
    print(f"Periods: {period_count:,}")
    print(f"Time span: {min_year} to {max_year}")


if __name__ == "__main__":
    conn = create_database()
    polity_count, period_count = load_data(conn)
    print_summary(conn, polity_count, period_count)
    conn.close()
