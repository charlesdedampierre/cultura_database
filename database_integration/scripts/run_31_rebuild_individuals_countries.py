#!/usr/bin/env python3
"""
Step 31: Rebuild individuals_countries from scratch.
Associates each individual with a modern country based on:
1. nationality (first priority)
2. deathplace (second priority)
3. birthplace (third priority)
Then applies region/macro_region from the regions table using impact_date.
"""
import sqlite3
import os
import time

DB_PATH = "data/humans_clean.sqlite3"
TASK_LOG = "task.log"
BATCH_SIZE = 50_000

def log(msg):
    print(msg, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")

def parse_year(date_str):
    if not date_str:
        return None
    try:
        if date_str.startswith('-'):
            rest = date_str[1:]
            year_str = rest.split('-')[0]
            return -int(year_str)
        else:
            year_str = date_str.split('-')[0]
            return int(year_str)
    except (ValueError, IndexError):
        return None

def main():
    # Reset task.log
    if os.path.exists(TASK_LOG):
        os.remove(TASK_LOG)

    log("=== Step 31: Rebuild individuals_countries ===")

    # Single connection, keep existing WAL mode
    conn = sqlite3.connect(DB_PATH, timeout=60)
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    read_conn = conn  # Use same connection for reads

    # PHASE 1: Build lookups
    log("[31] Building nationality lookup...")
    nat_lookup = {}
    for name, country, iso in read_conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM nationalities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        nat_lookup[name] = (country, iso)
    log(f"[31] Nationality lookup: {len(nat_lookup)} entries")

    log("[31] Building city lookup...")
    city_lookup = {}
    for name, country, iso in read_conn.execute(
        "SELECT name_en, iso_country_name, iso_a3_code FROM cities WHERE iso_country_name IS NOT NULL AND iso_a3_code IS NOT NULL"
    ):
        if name not in city_lookup:
            city_lookup[name] = (country, iso)
    log(f"[31] City lookup: {len(city_lookup)} entries")

    log("[31] Building region lookup...")
    region_lookup = {}
    for macro_region, region, iso_a3, start_year, end_year in read_conn.execute(
        "SELECT macro_region, region, iso_a3, start_year, end_year FROM regions"
    ):
        if iso_a3 not in region_lookup:
            region_lookup[iso_a3] = []
        region_lookup[iso_a3].append({
            'macro_region': macro_region,
            'region': region,
            'start_year': start_year,
            'end_year': end_year,
        })
    log(f"[31] Region lookup: {len(region_lookup)} ISO codes")

    log("[31] Building impact_date lookup...")
    impact_lookup = {}
    for wid, date_str in read_conn.execute(
        "SELECT wikidata_id, impact_date FROM individuals_impact_date"
    ):
        year = parse_year(date_str)
        if year is not None:
            impact_lookup[wid] = year
    log(f"[31] Impact date lookup: {len(impact_lookup)} entries")

    # PHASE 2: Drop and recreate table
    log("[31] Creating fresh individuals_countries table...")
    conn.execute("DROP TABLE IF EXISTS individuals_countries")
    conn.execute("""
        CREATE TABLE individuals_countries (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            iso_country_name TEXT,
            iso_a3_code TEXT,
            origins TEXT,
            region TEXT,
            macro_region TEXT
        )
    """)
    conn.commit()
    log("[31] Created fresh individuals_countries table")

    # PHASE 3: Rebuild using rowid-based pagination (avoids OFFSET scan issues)
    total = read_conn.execute("SELECT COUNT(*) FROM individuals").fetchone()[0]
    log(f"[31] Total individuals to process: {total}")

    last_rowid = 0
    processed = 0
    matched_nationality = 0
    matched_death = 0
    matched_birth = 0
    unmatched = 0
    total_inserted = 0
    with_region = 0
    start_time = time.time()

    while True:
        batch = read_conn.execute(
            "SELECT rowid, wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en FROM individuals WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (last_rowid, BATCH_SIZE)
        ).fetchall()

        if not batch:
            break

        last_rowid = batch[-1][0]
        # Strip the rowid from the batch for processing
        batch = [(r[1], r[2], r[3], r[4], r[5]) for r in batch]

        inserts = []
        for wikidata_id, name_en, nationalities_en, deathcity_en, birthcity_en in batch:
            found_country = None

            # Priority 1: nationality
            if nationalities_en:
                for nat_name in nationalities_en.split("; "):
                    nat_name = nat_name.strip()
                    if nat_name in nat_lookup:
                        country, iso = nat_lookup[nat_name]
                        found_country = (country, iso, "nationality")
                        break

            # Priority 2: deathplace
            if found_country is None and deathcity_en:
                city = deathcity_en.strip()
                if city in city_lookup:
                    country, iso = city_lookup[city]
                    found_country = (country, iso, "deathplace")

            # Priority 3: birthplace
            if found_country is None and birthcity_en:
                city = birthcity_en.strip()
                if city in city_lookup:
                    country, iso = city_lookup[city]
                    found_country = (country, iso, "birthplace")

            if found_country:
                country, iso, origin = found_country
                region_str = None
                macro_str = None

                year = impact_lookup.get(wikidata_id)
                if year is not None and iso in region_lookup:
                    regions = []
                    macro_regions = []
                    for entry in region_lookup[iso]:
                        in_range = year >= entry['start_year'] and (
                            entry['end_year'] is None or year <= entry['end_year']
                        )
                        if in_range:
                            if entry['region'] not in regions:
                                regions.append(entry['region'])
                            if entry['macro_region'] not in macro_regions:
                                macro_regions.append(entry['macro_region'])
                    if regions:
                        region_str = "; ".join(regions)
                        macro_str = "; ".join(macro_regions)
                        with_region += 1

                inserts.append((wikidata_id, name_en, country, iso, origin, region_str, macro_str))

                if origin == "nationality":
                    matched_nationality += 1
                elif origin == "deathplace":
                    matched_death += 1
                elif origin == "birthplace":
                    matched_birth += 1
                total_inserted += 1
            else:
                unmatched += 1

        conn.executemany(
            "INSERT OR IGNORE INTO individuals_countries (wikidata_id, name_en, iso_country_name, iso_a3_code, origins, region, macro_region) VALUES (?, ?, ?, ?, ?, ?, ?)",
            inserts
        )
        conn.commit()

        processed += len(batch)

        if processed % 500_000 < BATCH_SIZE:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            eta = (total - processed) / rate if rate > 0 else 0
            log(f"[31] Progress: {processed}/{total} ({processed*100//total}%), {total_inserted} inserted (nat:{matched_nationality}, death:{matched_death}, birth:{matched_birth}), {with_region} with region, {unmatched} unmatched [{elapsed:.0f}s elapsed, ETA {eta:.0f}s]")

    # PHASE 4: Create indexes
    log("[31] Creating indexes...")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_country ON individuals_countries(iso_country_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_iso ON individuals_countries(iso_a3_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_origins ON individuals_countries(origins)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_region ON individuals_countries(region)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indcountries_macro_region ON individuals_countries(macro_region)")
    conn.commit()

    # PHASE 5: Final stats
    final_count = conn.execute("SELECT COUNT(*) FROM individuals_countries").fetchone()[0]
    with_region_final = conn.execute("SELECT COUNT(*) FROM individuals_countries WHERE region IS NOT NULL").fetchone()[0]

    log("[31] === Final Statistics ===")
    log(f"[31] Total individuals: {total}")
    log(f"[31] Total in individuals_countries: {final_count}")
    log(f"[31]   via nationality: {matched_nationality}")
    log(f"[31]   via deathplace: {matched_death}")
    log(f"[31]   via birthplace: {matched_birth}")
    log(f"[31] With region: {with_region_final}")
    log(f"[31] Without region: {final_count - with_region_final}")
    log(f"[31] Unmatched (no country): {unmatched}")

    # Top 15 countries
    rows = conn.execute(
        "SELECT iso_country_name, iso_a3_code, COUNT(*) as cnt FROM individuals_countries GROUP BY iso_country_name ORDER BY cnt DESC LIMIT 15"
    ).fetchall()
    log("[31] Top 15 countries:")
    for name, iso, cnt in rows:
        log(f"[31]   {name} ({iso}) -> {cnt}")

    # Top macro_regions
    rows = conn.execute(
        "SELECT macro_region, COUNT(*) as cnt FROM individuals_countries WHERE macro_region IS NOT NULL GROUP BY macro_region ORDER BY cnt DESC"
    ).fetchall()
    log("[31] Macro regions:")
    for mr, cnt in rows:
        log(f"[31]   {mr} -> {cnt}")

    elapsed = time.time() - start_time
    log(f"[31] Total time: {elapsed:.0f}s")
    log("=== Step 31 complete ===")

    conn.close()

if __name__ == "__main__":
    main()
