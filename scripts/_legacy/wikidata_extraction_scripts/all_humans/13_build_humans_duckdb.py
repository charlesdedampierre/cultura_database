"""
Build a DuckDB database from all human JSON files.
Flat structure with semicolon-separated multi-values.
"""

import json
import os
import duckdb
from tqdm import tqdm
from collections import defaultdict

DATA_DIR = "data/all_humans"
DB_PATH = "data/all_humans/humans.duckdb"


def load_json(filename: str) -> dict:
    path = os.path.join(DATA_DIR, filename)
    print(f"  Loading {filename}...")
    with open(path, "r") as f:
        return json.load(f)


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = duckdb.connect(DB_PATH)

    print("=" * 60)
    print("BUILDING DUCKDB DATABASE")
    print("=" * 60)

    # =========================================
    # Load all JSON files
    # =========================================
    print("\n[1/4] Loading JSON files...")

    human_ids = load_json("all_human_ids.json")
    names = load_json("all_human_names.json")
    descriptions = load_json("all_human_descriptions.json")
    birthdates = load_json("all_human_birthdates.json")
    deathdates = load_json("all_human_deathdates.json")
    birthplaces = load_json("all_human_birthplaces.json")
    deathplaces = load_json("all_human_deathplaces.json")
    nationalities = load_json("all_human_nationalities.json")
    occupations = load_json("all_human_occupations.json")
    occupation_labels = load_json("occupation_labels.json")

    # Clean occupation labels (remove "@en suffix)
    occupation_labels = {
        k: v.strip('"').replace('"@en', '').replace('@en', '')
        for k, v in occupation_labels.items()
    }

    # =========================================
    # Build lookup tables
    # =========================================
    print("\n[2/4] Building lookup tables...")

    # Occupations lookup
    conn.execute("""
        CREATE TABLE occupations (
            id VARCHAR PRIMARY KEY,
            name VARCHAR
        )
    """)
    conn.executemany(
        "INSERT INTO occupations VALUES (?, ?)",
        list(occupation_labels.items())
    )
    print(f"  → occupations: {len(occupation_labels):,} rows")

    # Cities lookup (from birth + death places)
    cities = {}
    for place in birthplaces.values():
        if isinstance(place, dict):
            cities[place["id"]] = place["name"]
    for place in deathplaces.values():
        if isinstance(place, dict):
            cities[place["id"]] = place["name"]

    conn.execute("""
        CREATE TABLE cities (
            id VARCHAR PRIMARY KEY,
            name VARCHAR
        )
    """)
    conn.executemany(
        "INSERT INTO cities VALUES (?, ?)",
        list(cities.items())
    )
    print(f"  → cities: {len(cities):,} rows")

    # =========================================
    # Build main humans table
    # =========================================
    print("\n[3/4] Building humans table...")

    conn.execute("""
        CREATE TABLE humans (
            id VARCHAR PRIMARY KEY,
            name VARCHAR,
            description VARCHAR,
            birthdate VARCHAR,
            deathdate VARCHAR,
            birthcity VARCHAR,
            deathcity VARCHAR,
            nationality VARCHAR,
            occupation VARCHAR
        )
    """)

    # Prepare rows with semicolon-separated values
    rows = []
    for qid in tqdm(human_ids, desc="  Preparing"):
        # Get occupation names (semicolon-separated)
        occ_ids = occupations.get(qid, [])
        occ_names = [occupation_labels.get(oid, "") for oid in occ_ids]
        occ_names = [n for n in occ_names if n]  # Remove empty
        occ_str = "; ".join(occ_names) if occ_names else None

        # Get nationality names (semicolon-separated)
        nat_list = nationalities.get(qid, [])
        nat_names = [n.get("name", "") for n in nat_list if isinstance(n, dict)]
        nat_names = [n for n in nat_names if n]
        nat_str = "; ".join(nat_names) if nat_names else None

        # Get birthcity name
        bp = birthplaces.get(qid)
        birthcity = bp.get("name") if isinstance(bp, dict) else None

        # Get deathcity name
        dp = deathplaces.get(qid)
        deathcity = dp.get("name") if isinstance(dp, dict) else None

        row = (
            qid,
            names.get(qid),
            descriptions.get(qid),
            birthdates.get(qid),
            deathdates.get(qid),
            birthcity,
            deathcity,
            nat_str,
            occ_str
        )
        rows.append(row)

    print("  Inserting into database...")
    conn.executemany(
        "INSERT INTO humans VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows
    )

    # =========================================
    # Create indexes
    # =========================================
    print("\n[4/4] Creating indexes...")

    conn.execute("CREATE INDEX idx_humans_name ON humans(name)")
    conn.execute("CREATE INDEX idx_humans_birthdate ON humans(birthdate)")
    conn.execute("CREATE INDEX idx_humans_birthcity ON humans(birthcity)")
    conn.execute("CREATE INDEX idx_humans_nationality ON humans(nationality)")

    # =========================================
    # Summary
    # =========================================
    print("\n" + "=" * 60)
    print("DATABASE COMPLETE")
    print("=" * 60)

    for table in ["humans", "occupations", "cities"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")

    # Show sample
    print("\nSample row:")
    sample = conn.execute("""
        SELECT id, name, birthdate, birthcity, nationality, occupation
        FROM humans
        WHERE occupation IS NOT NULL AND nationality IS NOT NULL
        LIMIT 1
    """).fetchone()
    if sample:
        print(f"  id: {sample[0]}")
        print(f"  name: {sample[1]}")
        print(f"  birthdate: {sample[2]}")
        print(f"  birthcity: {sample[3]}")
        print(f"  nationality: {sample[4]}")
        print(f"  occupation: {sample[5]}")

    conn.close()

    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDatabase size: {size_mb:.1f} MB")
    print(f"Saved to: {DB_PATH}")


if __name__ == "__main__":
    build_database()
