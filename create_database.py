"""Create cultura_database.db with occupations and individuals."""

import json
import os
import sqlite3
from tqdm import tqdm

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data", "extracted", "individuals")
OCCUPATION_DIR = os.path.join(DATA_DIR, "occupation")
DB_PATH = os.path.join(BASE_DIR, "cultura_database.db")


def main():
    # Load occupation metadata
    with open(os.path.join(DATA_DIR, "occupations.json")) as f:
        occupations_meta = json.load(f)

    # Create mapping: occupation_id -> category
    occ_to_category = {
        occ["occupation_wikidata_id"]: occ["occupation_category"]
        for occ in occupations_meta
    }
    occ_to_name = {
        occ["occupation_wikidata_id"]: occ["occupation_name"]
        for occ in occupations_meta
    }

    print(f"Loaded {len(occupations_meta)} occupation definitions")

    # Remove existing database
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed existing database")

    # Create database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Create tables
    cursor.execute("""
        CREATE TABLE occupations (
            occupation_id TEXT PRIMARY KEY,
            occupation_name TEXT NOT NULL,
            occupation_category TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE individuals (
            wikidata_id TEXT NOT NULL,
            occupation_id TEXT NOT NULL,
            PRIMARY KEY (wikidata_id, occupation_id),
            FOREIGN KEY (occupation_id) REFERENCES occupations(occupation_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE occupation_counts (
            occupation_id TEXT PRIMARY KEY,
            occupation_name TEXT NOT NULL,
            occupation_category TEXT NOT NULL,
            individual_count INTEGER NOT NULL,
            FOREIGN KEY (occupation_id) REFERENCES occupations(occupation_id)
        )
    """)

    print("Created tables: occupations, individuals, occupation_counts")

    # Get all occupation files
    occ_files = [f for f in os.listdir(OCCUPATION_DIR) if f.endswith(".json")]
    print(f"\nProcessing {len(occ_files)} occupation files...")

    total_individuals = 0
    occupation_counts = []

    for filename in tqdm(occ_files, desc="Loading occupations"):
        filepath = os.path.join(OCCUPATION_DIR, filename)

        try:
            with open(filepath) as f:
                data = json.load(f)
        except:
            continue

        occ_id = data.get("occupation_id")
        occ_name = data.get("occupation_name") or occ_to_name.get(occ_id, "unknown")
        occ_category = occ_to_category.get(occ_id, "unknown")
        results = data.get("results", [])

        if not occ_id or not results:
            continue

        # Skip if has error or partial
        if data.get("error") or data.get("partial"):
            continue

        # Insert occupation
        cursor.execute(
            "INSERT OR IGNORE INTO occupations VALUES (?, ?, ?)",
            (occ_id, occ_name, occ_category)
        )

        # Insert individuals
        individuals = [(r.get("wikidata_id"), occ_id) for r in results if r.get("wikidata_id")]
        cursor.executemany(
            "INSERT OR IGNORE INTO individuals VALUES (?, ?)",
            individuals
        )

        # Track count
        occupation_counts.append((occ_id, occ_name, occ_category, len(individuals)))
        total_individuals += len(individuals)

    # Insert occupation counts
    cursor.executemany(
        "INSERT INTO occupation_counts VALUES (?, ?, ?, ?)",
        occupation_counts
    )

    # Create indexes for faster queries
    print("\nCreating indexes...")
    cursor.execute("CREATE INDEX idx_individuals_occupation ON individuals(occupation_id)")
    cursor.execute("CREATE INDEX idx_individuals_wikidata ON individuals(wikidata_id)")
    cursor.execute("CREATE INDEX idx_occupation_counts_category ON occupation_counts(occupation_category)")

    conn.commit()

    # Print summary
    cursor.execute("SELECT COUNT(*) FROM occupations")
    occ_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM individuals")
    ind_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT wikidata_id) FROM individuals")
    unique_ind = cursor.fetchone()[0]

    cursor.execute("""
        SELECT occupation_category, COUNT(*), SUM(individual_count)
        FROM occupation_counts
        GROUP BY occupation_category
    """)
    category_stats = cursor.fetchall()

    print(f"\n{'='*60}")
    print("DATABASE SUMMARY")
    print(f"{'='*60}")
    print(f"Occupations: {occ_count:,}")
    print(f"Individual-occupation mappings: {ind_count:,}")
    print(f"Unique individuals: {unique_ind:,}")
    print(f"\nBy category:")
    for cat, occ_count, ind_count in category_stats:
        print(f"  {cat}: {occ_count:,} occupations, {ind_count:,} individuals")

    # Top 10 occupations
    cursor.execute("""
        SELECT occupation_name, individual_count
        FROM occupation_counts
        ORDER BY individual_count DESC
        LIMIT 10
    """)
    print(f"\nTop 10 occupations:")
    for name, count in cursor.fetchall():
        print(f"  {name}: {count:,}")

    conn.close()

    db_size = os.path.getsize(DB_PATH) / (1024 * 1024)
    print(f"\nDatabase saved: {DB_PATH}")
    print(f"Size: {db_size:.1f} MB")


if __name__ == "__main__":
    main()
