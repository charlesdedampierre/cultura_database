"""
Extract a light SQLite database for the visualizer from the main database.

Creates visualizer/data/visualizer.sqlite3 with:
- polities: Polity metadata with display_mode for hierarchy toggle
- polity_periods: Geometries (simplified)
- individuals_light: One row per (individual, polity) pair
- cities: City coordinates
- evolution_cache: Pre-computed counts per polity/year
- top_cities_cache: Pre-computed top 10 cities per polity

Also generates:
- visualizer/frontend/public/evolution.json
- visualizer/frontend/public/occupations.json
"""

import sqlite3
import json
import os
from pathlib import Path
from collections import defaultdict
from tqdm import tqdm


def round_to_50(year: int) -> int:
    """Round year to nearest 50 (used for polity period lookup)."""
    return round(year / 50) * 50


def floor_to_25(year: int) -> int:
    """Floor year to nearest 25-year bucket.

    Examples: 1249 -> 1225, 1214 -> 1200, -500 -> -500, -487 -> -500
    """
    if year >= 0:
        return (year // 25) * 25
    else:
        # For negative years, floor goes more negative
        return -(((-year - 1) // 25 + 1) * 25) if year % 25 != 0 else year


def simplify_geometry(geom_json: str, tolerance: float = 0.1) -> str:
    """Simplify geometry if shapely is available, otherwise return as-is."""
    try:
        from shapely.geometry import shape
        from shapely import simplify

        geom = shape(json.loads(geom_json))
        simplified = simplify(geom, tolerance=tolerance, preserve_topology=True)
        return json.dumps(simplified.__geo_interface__)
    except ImportError:
        return geom_json
    except Exception:
        return geom_json


def build_display_mode_mapping(source_conn, clio_conn):
    """Determine display_mode for each polity based on hierarchy.

    Returns dict: polity_id -> display_mode ('both', 'leaf', 'aggregate', 'skip')

    - 'both': Standalone polities shown in both modes
    - 'leaf': Shown only in leaf/default mode (children of real aggregates)
    - 'aggregate': Shown only in aggregate mode (parenthesized real aggregates)
    - 'skip': Never shown (parenthesized pure duplicates with same count as counterpart)
    """
    source_cur = source_conn.cursor()

    # Get all polities
    source_cur.execute("SELECT id, name, number_individuals FROM polities_cliopatria")
    all_polities = {}
    for row in source_cur:
        all_polities[row['id']] = {'name': row['name'], 'count': row['number_individuals']}

    # Find parenthesized/non-parenthesized pairs
    source_cur.execute("""
        SELECT p1.id as paren_id, p1.number_individuals as paren_count,
               p2.id as non_paren_id, p2.number_individuals as non_paren_count
        FROM polities_cliopatria p1
        JOIN polities_cliopatria p2 ON p2.name = TRIM(p1.name, '()')
        WHERE p1.name LIKE '(%'
    """)
    pairs = {row['paren_id']: dict(row) for row in source_cur}

    # Classify parenthesized polities
    skip_ids = set()
    aggregate_ids = set()

    for pid, info in all_polities.items():
        if not info['name'].startswith('('):
            continue
        if pid in pairs:
            if pairs[pid]['paren_count'] == pairs[pid]['non_paren_count']:
                skip_ids.add(pid)
            else:
                aggregate_ids.add(pid)
        else:
            # No counterpart - grouping-only aggregate
            aggregate_ids.add(pid)

    # Get hierarchy from cliopatria.db to find children of aggregates
    children_of_aggregates = set()
    if clio_conn:
        clio_cur = clio_conn.cursor()
        clio_cur.execute("""
            SELECT polity_id, level1_id
            FROM polity_hierarchy_levels
            WHERE depth > 0
        """)
        for row in clio_cur:
            if row['level1_id'] in aggregate_ids:
                children_of_aggregates.add(row['polity_id'])

    # Build display_mode mapping
    display_mode = {}
    for pid in all_polities:
        if pid in skip_ids:
            display_mode[pid] = 'skip'
        elif pid in aggregate_ids:
            display_mode[pid] = 'aggregate'
        elif pid in children_of_aggregates and pid not in aggregate_ids:
            display_mode[pid] = 'leaf'
        else:
            display_mode[pid] = 'both'

    # Log summary
    modes = defaultdict(int)
    for m in display_mode.values():
        modes[m] += 1
    print(f"  Display mode distribution: {dict(modes)}")

    return display_mode


def main():
    # Paths
    base_dir = Path(__file__).parent.parent.parent
    source_db = base_dir / "data" / "humans_clean.sqlite3"
    clio_db = base_dir / "cliopatria_data" / "processing" / "data" / "cliopatria.db"
    target_db = base_dir / "visualizer" / "data" / "visualizer.sqlite3"
    frontend_public = base_dir / "visualizer" / "frontend" / "public"

    print(f"Source database: {source_db}")
    print(f"Cliopatria database: {clio_db}")
    print(f"Target database: {target_db}")

    # Ensure target directory exists
    target_db.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing target database
    if target_db.exists():
        os.remove(target_db)

    # Connect to databases
    source_conn = sqlite3.connect(source_db)
    source_conn.text_factory = lambda b: b.decode('utf-8', errors='replace')
    source_conn.row_factory = sqlite3.Row

    clio_conn = None
    if clio_db.exists():
        clio_conn = sqlite3.connect(clio_db)
        clio_conn.row_factory = sqlite3.Row
    else:
        print(f"WARNING: Cliopatria DB not found at {clio_db}, hierarchy will be limited")

    target_conn = sqlite3.connect(target_db)

    source_cur = source_conn.cursor()
    target_cur = target_conn.cursor()

    # Enable WAL mode for better performance
    target_cur.execute("PRAGMA journal_mode=WAL")
    target_cur.execute("PRAGMA synchronous=NORMAL")

    # =========================================================================
    # 0. Build hierarchy / display_mode mapping
    # =========================================================================
    print("\n0. Building hierarchy mapping...")
    display_mode = build_display_mode_mapping(source_conn, clio_conn)

    # Build set of skip IDs for filtering individuals
    skip_ids = {pid for pid, mode in display_mode.items() if mode == 'skip'}

    # =========================================================================
    # 1. Extract polities with display_mode
    # =========================================================================
    print("\n1. Extracting polities...")
    target_cur.execute("""
        CREATE TABLE polities (
            id INTEGER PRIMARY KEY,
            name TEXT,
            type TEXT,
            wikipedia_url TEXT,
            wikidata_id TEXT,
            individuals_count INTEGER,
            display_mode TEXT DEFAULT 'both'
        )
    """)

    source_cur.execute("SELECT * FROM polities_cliopatria")
    rows = source_cur.fetchall()

    for row in tqdm(rows, desc="Polities"):
        pid = row['id']
        mode = display_mode.get(pid, 'both')
        target_cur.execute(
            "INSERT INTO polities VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, row['name'], row['type'], row['wikipedia_url'],
             row['wikidata_id'], row['number_individuals'], mode)
        )

    print(f"  Inserted {len(rows):,} polities")

    # =========================================================================
    # 2. Extract polity_periods with simplified geometries
    # =========================================================================
    print("\n2. Extracting polity_periods...")
    target_cur.execute("""
        CREATE TABLE polity_periods (
            id INTEGER PRIMARY KEY,
            polity_id INTEGER,
            polity_name TEXT,
            from_year INTEGER,
            to_year INTEGER,
            area REAL,
            geometry TEXT
        )
    """)

    source_cur.execute("SELECT COUNT(*) FROM cliopatria_polity_periods")
    total_periods = source_cur.fetchone()[0]

    source_cur.execute("SELECT * FROM cliopatria_polity_periods")

    batch_size = 1000
    batch = []

    for row in tqdm(source_cur, total=total_periods, desc="Polity periods"):
        geom = simplify_geometry(row['geometry']) if row['geometry'] else None
        batch.append((
            row['id'], row['polity_id'], row['polity_name'],
            row['from_year'], row['to_year'], row['area'], geom
        ))

        if len(batch) >= batch_size:
            target_cur.executemany(
                "INSERT INTO polity_periods VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch
            )
            batch = []

    if batch:
        target_cur.executemany(
            "INSERT INTO polity_periods VALUES (?, ?, ?, ?, ?, ?, ?)",
            batch
        )

    target_cur.execute("CREATE INDEX idx_pp_polity ON polity_periods(polity_id)")
    target_cur.execute("CREATE INDEX idx_pp_years ON polity_periods(from_year, to_year)")

    print(f"  Inserted {total_periods:,} polity periods")

    # =========================================================================
    # 3. Extract cities
    # =========================================================================
    print("\n3. Extracting cities...")
    target_cur.execute("""
        CREATE TABLE cities (
            id TEXT PRIMARY KEY,
            name_en TEXT,
            lat REAL,
            lon REAL,
            iso_country_name TEXT
        )
    """)

    source_cur.execute("SELECT COUNT(*) FROM cities")
    total_cities = source_cur.fetchone()[0]

    source_cur.execute("SELECT id, name_en, lat, lon, iso_country_name FROM cities")
    batch = []

    for row in tqdm(source_cur, total=total_cities, desc="Cities"):
        batch.append((row['id'], row['name_en'], row['lat'], row['lon'], row['iso_country_name']))

        if len(batch) >= 10000:
            target_cur.executemany(
                "INSERT INTO cities VALUES (?, ?, ?, ?, ?)",
                batch
            )
            batch = []

    if batch:
        target_cur.executemany(
            "INSERT INTO cities VALUES (?, ?, ?, ?, ?)",
            batch
        )

    print(f"  Inserted {total_cities:,} cities")

    # =========================================================================
    # 4. Extract individuals_light (one row per individual-polity pair)
    # =========================================================================
    print("\n4. Extracting individuals_light...")
    target_cur.execute("""
        CREATE TABLE individuals_light (
            wikidata_id TEXT,
            name_en TEXT,
            occupations_en TEXT,
            sitelinks_count INTEGER,
            impact_date INTEGER,
            impact_date_raw INTEGER,
            polity_id INTEGER,
            birthcity_id TEXT,
            deathcity_id TEXT,
            PRIMARY KEY (wikidata_id, polity_id)
        )
    """)

    # Query individuals with their semicolon-separated polity_ids
    query = """
        SELECT
            ic.wikidata_id,
            i.name_en,
            i.occupations_en,
            i.sitelinks_count,
            ic.impact_date,
            ic.polity_id,
            ik.birthcity_id,
            ik.deathcity_id
        FROM individuals_cliopatria ic
        JOIN individuals i ON ic.wikidata_id = i.wikidata_id
        LEFT JOIN individuals_keys ik ON ic.wikidata_id = ik.wikidata_id
        WHERE ic.impact_date IS NOT NULL
    """

    source_cur.execute("SELECT COUNT(*) FROM individuals_cliopatria WHERE impact_date IS NOT NULL")
    total_individuals = source_cur.fetchone()[0]

    source_cur.execute(query)
    batch = []
    inserted = 0
    rows_generated = 0

    for row in tqdm(source_cur, total=total_individuals, desc="Individuals"):
        impact_date_rounded = floor_to_25(row['impact_date']) if row['impact_date'] else None

        # Parse semicolon-separated polity_ids
        polity_id_str = row['polity_id']
        if polity_id_str is None:
            continue

        polity_ids_raw = str(polity_id_str).split(';')

        for pid_str in polity_ids_raw:
            pid_str = pid_str.strip()
            if not pid_str:
                continue
            try:
                pid = int(pid_str)
            except ValueError:
                continue

            # Skip pure duplicate parenthesized polities
            if pid in skip_ids:
                continue

            batch.append((
                row['wikidata_id'],
                row['name_en'],
                row['occupations_en'],
                row['sitelinks_count'],
                impact_date_rounded,
                row['impact_date'],  # raw impact date
                pid,
                row['birthcity_id'],
                row['deathcity_id']
            ))
            rows_generated += 1

        if len(batch) >= 50000:
            target_cur.executemany(
                "INSERT OR IGNORE INTO individuals_light VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch
            )
            inserted += len(batch)
            batch = []

    if batch:
        target_cur.executemany(
            "INSERT OR IGNORE INTO individuals_light VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch
        )
        inserted += len(batch)

    target_cur.execute("CREATE INDEX idx_il_polity ON individuals_light(polity_id)")
    target_cur.execute("CREATE INDEX idx_il_polity_sitelinks ON individuals_light(polity_id, sitelinks_count DESC)")
    target_cur.execute("CREATE INDEX idx_il_polity_impact ON individuals_light(polity_id, impact_date)")

    target_cur.execute("SELECT COUNT(*) FROM individuals_light")
    actual_count = target_cur.fetchone()[0]
    print(f"  Generated {rows_generated:,} rows, inserted {actual_count:,} (after dedup)")

    target_conn.commit()

    # =========================================================================
    # 5. Pre-compute evolution_cache
    # =========================================================================
    print("\n5. Computing evolution_cache...")
    target_cur.execute("""
        CREATE TABLE evolution_cache (
            polity_id INTEGER,
            year INTEGER,
            count INTEGER,
            PRIMARY KEY (polity_id, year)
        )
    """)

    # Get all polity IDs that have individuals
    target_cur.execute("SELECT DISTINCT polity_id FROM individuals_light ORDER BY polity_id")
    polity_ids = [row[0] for row in target_cur.fetchall()]

    for polity_id in tqdm(polity_ids, desc="Evolution cache"):
        target_cur.execute("""
            SELECT impact_date, COUNT(*) as cnt
            FROM individuals_light
            WHERE polity_id = ? AND impact_date IS NOT NULL
            GROUP BY impact_date
            ORDER BY impact_date
        """, (polity_id,))

        yearly_counts = target_cur.fetchall()

        if not yearly_counts:
            continue

        entries = [(polity_id, year, count) for year, count in yearly_counts]

        target_cur.executemany(
            "INSERT INTO evolution_cache VALUES (?, ?, ?)",
            entries
        )

    target_cur.execute("SELECT COUNT(*) FROM evolution_cache")
    print(f"  Created {target_cur.fetchone()[0]:,} evolution cache entries")

    target_conn.commit()

    # =========================================================================
    # 6. Pre-compute top_cities_cache
    # =========================================================================
    print("\n6. Computing top_cities_cache...")
    target_cur.execute("""
        CREATE TABLE top_cities_cache (
            polity_id INTEGER,
            city_id TEXT,
            city_name TEXT,
            lat REAL,
            lon REAL,
            individual_count INTEGER,
            PRIMARY KEY (polity_id, city_id)
        )
    """)

    for polity_id in tqdm(polity_ids, desc="Top cities cache"):
        target_cur.execute("""
            SELECT
                il.birthcity_id,
                c.name_en,
                c.lat,
                c.lon,
                COUNT(*) as cnt
            FROM individuals_light il
            JOIN cities c ON il.birthcity_id = c.id
            WHERE il.polity_id = ? AND il.birthcity_id IS NOT NULL
            GROUP BY il.birthcity_id
            ORDER BY cnt DESC
            LIMIT 10
        """, (polity_id,))

        cities = target_cur.fetchall()

        for city_id, city_name, lat, lon, count in cities:
            target_cur.execute(
                "INSERT INTO top_cities_cache VALUES (?, ?, ?, ?, ?, ?)",
                (polity_id, city_id, city_name, lat, lon, count)
            )

    target_cur.execute("SELECT COUNT(*) FROM top_cities_cache")
    print(f"  Created {target_cur.fetchone()[0]:,} top cities cache entries")

    target_conn.commit()

    # =========================================================================
    # 7. Generate evolution.json for frontend
    # =========================================================================
    print("\n7. Generating evolution.json...")
    target_cur.execute("""
        SELECT polity_id, year, count
        FROM evolution_cache
        ORDER BY polity_id, year
    """)

    evolution_data = defaultdict(list)
    for row in target_cur:
        evolution_data[str(row[0])].append({"year": row[1], "count": row[2]})

    evolution_path = frontend_public / "evolution.json"
    with open(evolution_path, 'w') as f:
        json.dump(evolution_data, f, separators=(',', ':'))

    print(f"  Generated {evolution_path} ({len(evolution_data)} polities)")

    # =========================================================================
    # 8. Generate occupations.json for frontend
    # =========================================================================
    print("\n8. Generating occupations.json...")
    occupations_data = {}

    for polity_id in tqdm(polity_ids, desc="Occupations"):
        target_cur.execute("""
            SELECT occupations_en
            FROM individuals_light
            WHERE polity_id = ? AND occupations_en IS NOT NULL
        """, (polity_id,))

        occ_counts = defaultdict(int)
        for row in target_cur:
            # Split semicolon-separated occupations and count each
            for occ in row[0].split('; '):
                occ = occ.strip()
                if occ:
                    occ_counts[occ] += 1

        if occ_counts:
            # Sort by count descending, take top 20
            sorted_occs = sorted(occ_counts.items(), key=lambda x: x[1], reverse=True)[:20]
            occupations_data[str(polity_id)] = [
                {"name": name, "count": count} for name, count in sorted_occs
            ]

    occupations_path = frontend_public / "occupations.json"
    with open(occupations_path, 'w') as f:
        json.dump(occupations_data, f, separators=(',', ':'))

    print(f"  Generated {occupations_path} ({len(occupations_data)} polities)")

    # =========================================================================
    # 9. Update individuals_count in polities based on actual data
    # =========================================================================
    print("\n9. Updating polity individual counts...")
    target_cur.execute("""
        UPDATE polities SET individuals_count = (
            SELECT COUNT(*) FROM individuals_light WHERE individuals_light.polity_id = polities.id
        )
    """)
    target_conn.commit()

    # =========================================================================
    # Final commit and optimization
    # =========================================================================
    print("\n10. Optimizing database...")
    target_cur.execute("VACUUM")
    target_cur.execute("ANALYZE")

    # Close connections
    source_conn.close()
    if clio_conn:
        clio_conn.close()
    target_conn.close()

    # Report final size
    size_mb = target_db.stat().st_size / (1024 * 1024)
    print(f"\nDone! Database size: {size_mb:.1f} MB")
    print(f"Output: {target_db}")


if __name__ == "__main__":
    main()
