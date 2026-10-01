#!/usr/bin/env python3
"""
Step 30: Create individuals_regions_cliopatria table.
For each individual, store a Wikipedia URL from (in priority order):
1. nationalities en_wikipedia_url
2. death city en_wikipedia_url_original_country_name
3. birth city en_wikipedia_url_original_country_name
With an "origin" column indicating which source was used.
"""
import sqlite3
import time

DB_PATH = "data/humans_clean.sqlite3"
TASK_LOG = "task.log"
BATCH_SIZE = 50_000

def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")

def main():
    log("=== Step 30: Create individuals_regions_cliopatria table ===")

    # Use separate connections for reading and writing to avoid corruption
    read_conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    read_conn.execute("PRAGMA cache_size=-2000000")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")

    # Build nationality URL lookup
    log("[30] Building nationality URL lookup...")
    nat_url_lookup = {}
    for name, url in read_conn.execute(
        "SELECT name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL"
    ):
        nat_url_lookup[name] = url
    log(f"[30] Nationality URL lookup: {len(nat_url_lookup)} entries")

    # Build city URL lookup
    log("[30] Building city URL lookup...")
    city_url_lookup = {}
    for name, url in read_conn.execute(
        "SELECT name_en, en_wikipedia_url_original_country_name FROM cities WHERE en_wikipedia_url_original_country_name IS NOT NULL"
    ):
        if name not in city_url_lookup:
            city_url_lookup[name] = url
    log(f"[30] City URL lookup: {len(city_url_lookup)} entries")

    # Drop and create table
    log("[30] Creating individuals_regions_cliopatria table...")
    conn.execute("DROP TABLE IF EXISTS individuals_regions_cliopatria")
    conn.execute("""
        CREATE TABLE individuals_regions_cliopatria (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            en_wikipedia_url TEXT,
            origin TEXT NOT NULL
        )
    """)
    conn.commit()

    total = read_conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[30] Total individuals: {total}")

    offset = 0
    from_nationality = 0
    from_deathcity = 0
    from_birthcity = 0
    no_url = 0
    total_inserted = 0
    start_time = time.time()

    while True:
        batch = read_conn.execute(
            "SELECT wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en FROM individuals ORDER BY rowid LIMIT ? OFFSET ?",
            (BATCH_SIZE, offset)
        ).fetchall()

        if not batch:
            break

        inserts = []
        for wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en in batch:
            found = False

            # Priority 1: nationality en_wikipedia_url
            if nationalities_en:
                for nat_name in nationalities_en.split("; "):
                    nat_name = nat_name.strip()
                    if nat_name in nat_url_lookup:
                        inserts.append((wikidata_id, name_en, nat_url_lookup[nat_name], "nationality"))
                        from_nationality += 1
                        total_inserted += 1
                        found = True
                        break

            if found:
                continue

            # Priority 2: death city
            if deathcity_en:
                city = deathcity_en.strip()
                if city in city_url_lookup:
                    inserts.append((wikidata_id, name_en, city_url_lookup[city], "deathcity"))
                    from_deathcity += 1
                    total_inserted += 1
                    found = True

            if found:
                continue

            # Priority 3: birth city
            if birthcity_en:
                city = birthcity_en.strip()
                if city in city_url_lookup:
                    inserts.append((wikidata_id, name_en, city_url_lookup[city], "birthcity"))
                    from_birthcity += 1
                    total_inserted += 1
                    found = True

            if not found:
                no_url += 1

        conn.executemany(
            "INSERT OR IGNORE INTO individuals_regions_cliopatria (wikidata_id, name_en, en_wikipedia_url, origin) VALUES (?, ?, ?, ?)",
            inserts
        )
        conn.commit()

        offset += len(batch)

        if offset % 500_000 < BATCH_SIZE:
            elapsed = time.time() - start_time
            rate = offset / elapsed if elapsed > 0 else 0
            eta = (total - offset) / rate if rate > 0 else 0
            log(f"[30] Progress: {offset}/{total} ({offset*100//total}%), {total_inserted} inserted (nat:{from_nationality}, death:{from_deathcity}, birth:{from_birthcity}), {no_url} no URL [{elapsed:.0f}s elapsed, ETA {eta:.0f}s]")

    # Create indexes
    log("[30] Creating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cliopatria_url ON individuals_regions_cliopatria(en_wikipedia_url)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cliopatria_origin ON individuals_regions_cliopatria(origin)")
    conn.commit()

    # Final stats
    final_count = conn.execute("SELECT COUNT(*) FROM individuals_regions_cliopatria").fetchone()[0]

    log("[30] === Final Statistics ===")
    log(f"[30] Total individuals: {total}")
    log(f"[30] Total inserted: {total_inserted}")
    log(f"[30]   via nationality: {from_nationality}")
    log(f"[30]   via deathcity: {from_deathcity}")
    log(f"[30]   via birthcity: {from_birthcity}")
    log(f"[30] No URL found: {no_url}")
    log(f"[30] Rows in individuals_regions_cliopatria: {final_count}")

    # Origin breakdown
    rows = conn.execute(
        "SELECT origin, COUNT(*) as cnt FROM individuals_regions_cliopatria GROUP BY origin ORDER BY cnt DESC"
    ).fetchall()
    log("[30] Origin breakdown:")
    for origin, cnt in rows:
        log(f"[30]   {origin} -> {cnt}")

    elapsed = time.time() - start_time
    log(f"[30] Total time: {elapsed:.0f}s")
    log("=== Step 30 complete ===")

    read_conn.close()
    conn.close()

if __name__ == "__main__":
    main()
