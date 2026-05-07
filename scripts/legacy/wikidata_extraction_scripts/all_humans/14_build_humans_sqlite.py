"""
Build SQLite3 database from all human JSON files.
Schema based on individuals_qlever_sample.db structure.
"""

import json
import os
import sqlite3
import time
from tqdm import tqdm

DATA_DIR = "data/all_humans"
DB_PATH = "data/all_humans/humans.sqlite3"


def load_json(filename: str) -> dict:
    path = os.path.join(DATA_DIR, filename)
    print(f"  Loading {filename}...")
    with open(path, "r") as f:
        return json.load(f)


def clean_text(text):
    """Remove @en language tags and quotes."""
    if text is None:
        return None
    return text.replace('"', '').replace('@en', '').strip()


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    total_start = time.time()
    print("=" * 60)
    print("BUILDING SQLITE3 DATABASE")
    print("=" * 60)

    # =========================================
    # Step 1: Create schema
    # =========================================
    print("\n[1/6] Creating schema...")

    cursor.executescript("""
        -- Main individuals table
        CREATE TABLE individuals (
            wikidata_id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT,
            birthdate TEXT,
            deathdate TEXT,
            nationalities TEXT,
            birthcity TEXT,
            deathcity TEXT,
            occupations TEXT,
            n_sitelinks INTEGER DEFAULT 0
        );

        -- Sitelinks table
        CREATE TABLE sitelinks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wikidata_id TEXT NOT NULL,
            url TEXT,
            FOREIGN KEY (wikidata_id) REFERENCES individuals(wikidata_id)
        );

        -- Occupations lookup
        CREATE TABLE occupations (
            wikidata_id TEXT PRIMARY KEY,
            name TEXT,
            count INTEGER DEFAULT 0
        );

        -- Cities lookup
        CREATE TABLE cities (
            wikidata_id TEXT PRIMARY KEY,
            name TEXT,
            birth_count INTEGER DEFAULT 0,
            death_count INTEGER DEFAULT 0
        );

        -- Nationalities lookup
        CREATE TABLE nationalities (
            wikidata_id TEXT PRIMARY KEY,
            name TEXT,
            count INTEGER DEFAULT 0
        );

        -- Indexes
        CREATE INDEX idx_individuals_name ON individuals(name);
        CREATE INDEX idx_individuals_birthdate ON individuals(birthdate);
        CREATE INDEX idx_individuals_birthcity ON individuals(birthcity);
        CREATE INDEX idx_sitelinks_wikidata ON sitelinks(wikidata_id);
    """)
    conn.commit()
    print("  ✓ Schema created")

    # =========================================
    # Step 2: Load JSON files
    # =========================================
    print("\n[2/6] Loading JSON files...")
    t = time.time()

    human_ids = load_json("all_human_ids.json")
    names = load_json("all_human_names.json")
    descriptions = load_json("all_human_descriptions.json")
    birthdates = load_json("all_human_birthdates.json")
    deathdates = load_json("all_human_deathdates.json")
    birthplaces = load_json("all_human_birthplaces.json")
    deathplaces = load_json("all_human_deathplaces.json")
    nationalities_data = load_json("all_human_nationalities.json")
    occupations_data = load_json("all_human_occupations.json")
    occupation_labels = load_json("occupation_labels.json")
    sitelinks_data = load_json("all_human_sitelinks.json")

    # Clean occupation labels
    occupation_labels = {
        k: clean_text(v) for k, v in occupation_labels.items()
    }

    print(f"  ✓ Loaded in {time.time() - t:.1f}s")

    # =========================================
    # Step 3: Insert occupations lookup
    # =========================================
    print("\n[3/6] Inserting lookup tables...")
    t = time.time()

    # Count occupations
    occ_counts = {}
    for occ_list in occupations_data.values():
        for occ_id in occ_list:
            occ_counts[occ_id] = occ_counts.get(occ_id, 0) + 1

    occ_rows = [(oid, occupation_labels.get(oid, ""), occ_counts.get(oid, 0))
                for oid in occupation_labels.keys()]
    cursor.executemany("INSERT INTO occupations VALUES (?, ?, ?)", occ_rows)
    print(f"  occupations: {len(occ_rows):,}")

    # Cities lookup with counts
    cities = {}
    birth_counts = {}
    death_counts = {}

    for place in birthplaces.values():
        if isinstance(place, dict):
            cid = place["id"]
            cities[cid] = clean_text(place["name"])
            birth_counts[cid] = birth_counts.get(cid, 0) + 1

    for place in deathplaces.values():
        if isinstance(place, dict):
            cid = place["id"]
            cities[cid] = clean_text(place["name"])
            death_counts[cid] = death_counts.get(cid, 0) + 1

    city_rows = [(cid, cname, birth_counts.get(cid, 0), death_counts.get(cid, 0))
                 for cid, cname in cities.items()]
    cursor.executemany("INSERT INTO cities VALUES (?, ?, ?, ?)", city_rows)
    print(f"  cities: {len(city_rows):,}")

    # Nationalities lookup with counts
    nat_lookup = {}
    nat_counts = {}
    for nat_list in nationalities_data.values():
        for nat in nat_list:
            if isinstance(nat, dict):
                nid = nat["id"]
                nat_lookup[nid] = clean_text(nat["name"])
                nat_counts[nid] = nat_counts.get(nid, 0) + 1

    nat_rows = [(nid, nname, nat_counts.get(nid, 0))
                for nid, nname in nat_lookup.items()]
    cursor.executemany("INSERT INTO nationalities VALUES (?, ?, ?)", nat_rows)
    print(f"  nationalities: {len(nat_rows):,}")

    conn.commit()
    print(f"  ✓ Lookup tables in {time.time() - t:.1f}s")

    # =========================================
    # Step 4: Insert individuals
    # =========================================
    print("\n[4/6] Inserting individuals...")
    t = time.time()

    batch = []
    batch_size = 50000

    for i, qid in enumerate(tqdm(human_ids, desc="  Preparing")):
        # Get occupation names
        occ_ids = occupations_data.get(qid, [])
        occ_names = [occupation_labels.get(oid, "") for oid in occ_ids]
        occ_names = [n for n in occ_names if n]
        occ_str = "; ".join(occ_names) if occ_names else None

        # Get nationality names
        nat_list = nationalities_data.get(qid, [])
        nat_names = [clean_text(n.get("name", "")) for n in nat_list if isinstance(n, dict)]
        nat_names = [n for n in nat_names if n]
        nat_str = "; ".join(nat_names) if nat_names else None

        # Get places
        bp = birthplaces.get(qid)
        birthcity = clean_text(bp.get("name")) if isinstance(bp, dict) else None

        dp = deathplaces.get(qid)
        deathcity = clean_text(dp.get("name")) if isinstance(dp, dict) else None

        # Count sitelinks
        n_sitelinks = len(sitelinks_data.get(qid, []))

        row = (
            qid,
            clean_text(names.get(qid)),
            clean_text(descriptions.get(qid)),
            birthdates.get(qid),
            deathdates.get(qid),
            nat_str,
            birthcity,
            deathcity,
            occ_str,
            n_sitelinks
        )
        batch.append(row)

        if len(batch) >= batch_size:
            cursor.executemany(
                "INSERT INTO individuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch
            )
            conn.commit()
            batch = []

    # Insert remaining
    if batch:
        cursor.executemany(
            "INSERT INTO individuals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch
        )
        conn.commit()

    print(f"  ✓ Individuals inserted in {time.time() - t:.1f}s")

    # =========================================
    # Step 5: Insert sitelinks
    # =========================================
    print("\n[5/6] Inserting sitelinks...")
    t = time.time()

    batch = []
    total_links = 0

    for qid, links in tqdm(sitelinks_data.items(), desc="  Preparing"):
        for url in links:
            batch.append((qid, url))
            total_links += 1

        if len(batch) >= batch_size:
            cursor.executemany(
                "INSERT INTO sitelinks (wikidata_id, url) VALUES (?, ?)",
                batch
            )
            conn.commit()
            batch = []

    if batch:
        cursor.executemany(
            "INSERT INTO sitelinks (wikidata_id, url) VALUES (?, ?)",
            batch
        )
        conn.commit()

    print(f"  ✓ {total_links:,} sitelinks in {time.time() - t:.1f}s")

    # =========================================
    # Step 6: Summary
    # =========================================
    print("\n" + "=" * 60)
    print("DATABASE COMPLETE")
    print("=" * 60)

    for table in ["individuals", "sitelinks", "occupations", "cities", "nationalities"]:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")

    conn.close()

    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    total_time = time.time() - total_start

    print(f"\nDatabase size: {size_mb:.1f} MB")
    print(f"Total time: {total_time:.1f}s")
    print(f"Saved to: {DB_PATH}")


if __name__ == "__main__":
    build_database()
