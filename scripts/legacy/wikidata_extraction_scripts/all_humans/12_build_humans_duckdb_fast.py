"""
Build DuckDB database using Polars (Rust-based, 10-100x faster).
"""

import json
import os
import time
import polars as pl
import duckdb

DATA_DIR = "data/all_humans"
DB_PATH = "data/all_humans/humans.duckdb"


def step(n, msg):
    print(f"\n[{n}] {msg}")
    return time.time()


def done(start):
    elapsed = time.time() - start
    print(f"    ✓ Done in {elapsed:.1f}s")


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    total_start = time.time()
    print("=" * 60)
    print("FAST BUILD WITH POLARS (RUST)")
    print("=" * 60)

    # =========================================
    # Step 1: Load JSON files into Polars DataFrames
    # =========================================
    t = step(1, "Loading JSON files → Polars DataFrames")

    # Load simple key-value JSONs
    with open(f"{DATA_DIR}/all_human_ids.json") as f:
        ids_list = json.load(f)
    df_ids = pl.DataFrame({"id": ids_list})
    print(f"    ids: {len(ids_list):,}")

    with open(f"{DATA_DIR}/all_human_names.json") as f:
        names_dict = json.load(f)
    df_names = pl.DataFrame({"id": list(names_dict.keys()), "name": list(names_dict.values())})
    print(f"    names: {len(names_dict):,}")

    with open(f"{DATA_DIR}/all_human_descriptions.json") as f:
        desc_dict = json.load(f)
    df_desc = pl.DataFrame({"id": list(desc_dict.keys()), "description": list(desc_dict.values())})
    print(f"    descriptions: {len(desc_dict):,}")

    with open(f"{DATA_DIR}/all_human_birthdates.json") as f:
        bd_dict = json.load(f)
    df_bd = pl.DataFrame({"id": list(bd_dict.keys()), "birthdate": list(bd_dict.values())})
    print(f"    birthdates: {len(bd_dict):,}")

    with open(f"{DATA_DIR}/all_human_deathdates.json") as f:
        dd_dict = json.load(f)
    df_dd = pl.DataFrame({"id": list(dd_dict.keys()), "deathdate": list(dd_dict.values())})
    print(f"    deathdates: {len(dd_dict):,}")

    done(t)

    # =========================================
    # Step 2: Load birthplaces/deathplaces
    # =========================================
    t = step(2, "Loading places")

    with open(f"{DATA_DIR}/all_human_birthplaces.json") as f:
        bp_dict = json.load(f)
    bp_rows = [(k, v["id"], v["name"]) for k, v in bp_dict.items() if isinstance(v, dict)]
    df_bp = pl.DataFrame({"id": [r[0] for r in bp_rows], "birthcity_id": [r[1] for r in bp_rows], "birthcity": [r[2] for r in bp_rows]})
    print(f"    birthplaces: {len(bp_rows):,}")

    with open(f"{DATA_DIR}/all_human_deathplaces.json") as f:
        dp_dict = json.load(f)
    dp_rows = [(k, v["id"], v["name"]) for k, v in dp_dict.items() if isinstance(v, dict)]
    df_dp = pl.DataFrame({"id": [r[0] for r in dp_rows], "deathcity_id": [r[1] for r in dp_rows], "deathcity": [r[2] for r in dp_rows]})
    print(f"    deathplaces: {len(dp_rows):,}")

    done(t)

    # =========================================
    # Step 3: Load and aggregate occupations
    # =========================================
    t = step(3, "Loading occupations → semicolon-separated")

    with open(f"{DATA_DIR}/occupation_labels.json") as f:
        occ_labels = json.load(f)
    # Clean labels
    occ_labels = {k: v.strip('"').replace('"@en', '').replace('@en', '') for k, v in occ_labels.items()}

    with open(f"{DATA_DIR}/all_human_occupations.json") as f:
        occ_dict = json.load(f)

    # Build aggregated occupation strings
    occ_rows = []
    for human_id, occ_ids in occ_dict.items():
        names = [occ_labels.get(oid, "") for oid in occ_ids]
        names = [n for n in names if n]
        occ_rows.append((human_id, "; ".join(names) if names else None))

    df_occ = pl.DataFrame({"id": [r[0] for r in occ_rows], "occupation": [r[1] for r in occ_rows]})
    print(f"    occupation links: {len(occ_rows):,}")

    done(t)

    # =========================================
    # Step 4: Load and aggregate nationalities
    # =========================================
    t = step(4, "Loading nationalities → semicolon-separated")

    with open(f"{DATA_DIR}/all_human_nationalities.json") as f:
        nat_dict = json.load(f)

    nat_rows = []
    for human_id, nat_list in nat_dict.items():
        names = [n.get("name", "") for n in nat_list if isinstance(n, dict)]
        names = [n for n in names if n]
        nat_rows.append((human_id, "; ".join(names) if names else None))

    df_nat = pl.DataFrame({"id": [r[0] for r in nat_rows], "nationality": [r[1] for r in nat_rows]})
    print(f"    nationality links: {len(nat_rows):,}")

    done(t)

    # =========================================
    # Step 5: Join all DataFrames (Rust speed)
    # =========================================
    t = step(5, "Joining all DataFrames (Polars/Rust)")

    df = (
        df_ids
        .join(df_names, on="id", how="left")
        .join(df_desc, on="id", how="left")
        .join(df_bd, on="id", how="left")
        .join(df_dd, on="id", how="left")
        .join(df_bp.select(["id", "birthcity"]), on="id", how="left")
        .join(df_dp.select(["id", "deathcity"]), on="id", how="left")
        .join(df_nat, on="id", how="left")
        .join(df_occ, on="id", how="left")
    )

    print(f"    Final shape: {df.shape}")
    done(t)

    # =========================================
    # Step 6: Write to DuckDB
    # =========================================
    t = step(6, "Writing to DuckDB")

    conn = duckdb.connect(DB_PATH)

    # Main humans table
    conn.execute("CREATE TABLE humans AS SELECT * FROM df")
    print(f"    humans table created")

    # Occupations lookup
    df_occ_lookup = pl.DataFrame({"id": list(occ_labels.keys()), "name": list(occ_labels.values())})
    conn.execute("CREATE TABLE occupations AS SELECT * FROM df_occ_lookup")
    print(f"    occupations lookup: {len(occ_labels):,}")

    # Cities lookup
    cities = {}
    for _, cid, cname in bp_rows:
        cities[cid] = cname
    for _, cid, cname in dp_rows:
        cities[cid] = cname
    df_cities = pl.DataFrame({"id": list(cities.keys()), "name": list(cities.values())})
    conn.execute("CREATE TABLE cities AS SELECT * FROM df_cities")
    print(f"    cities lookup: {len(cities):,}")

    done(t)

    # =========================================
    # Step 7: Create indexes
    # =========================================
    t = step(7, "Creating indexes")

    conn.execute("CREATE INDEX idx_humans_id ON humans(id)")
    conn.execute("CREATE INDEX idx_humans_name ON humans(name)")
    conn.execute("CREATE INDEX idx_humans_birthdate ON humans(birthdate)")
    conn.execute("CREATE INDEX idx_humans_birthcity ON humans(birthcity)")

    done(t)

    # =========================================
    # Summary
    # =========================================
    print("\n" + "=" * 60)
    print("DATABASE COMPLETE")
    print("=" * 60)

    for table in ["humans", "occupations", "cities"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count:,} rows")

    # Sample
    print("\nSample:")
    conn.execute("""
        SELECT id, name, birthdate, birthcity, nationality, occupation
        FROM humans
        WHERE occupation IS NOT NULL
        LIMIT 3
    """).show()

    conn.close()

    size_mb = os.path.getsize(DB_PATH) / (1024 * 1024)
    total_time = time.time() - total_start

    print(f"\nDatabase size: {size_mb:.1f} MB")
    print(f"Total time: {total_time:.1f}s")
    print(f"Saved to: {DB_PATH}")


if __name__ == "__main__":
    build_database()
