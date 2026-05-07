#!/usr/bin/env python3
"""Re-add URL-matched individuals to individuals_cliopatria WITHOUT requiring
an impact_date. These are individuals whose nationality/birthcity/deathcity URL
matches a polity, but who have no impact_date available.
Then update the consolidate table accordingly."""

import sqlite3
import time

DB_PATH = "/workspace/data/humans_clean.sqlite3"
TASK_LOG = "/workspace/task.log"
BATCH = 50_000


def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(TASK_LOG, "a") as f:
        f.write(line + "\n")


def main():
    log("=== Add URL-matched individuals without impact_date ===")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-2000000")
    conn.execute("PRAGMA busy_timeout=60000")

    # 1. Build url_to_polity lookup
    log("[1/5] Building url_to_polity lookup...")
    url_to_polity = {}
    for pid, name, url in conn.execute(
        "SELECT id, name, wikipedia_url FROM polities_cliopatria WHERE wikipedia_url IS NOT NULL"
    ):
        url_to_polity.setdefault(url, (name, pid))
    log(f"    {len(url_to_polity)} polity URLs")

    # 2. Build nationality URL lookup: nat_wikidata_id -> (name_en, url)
    log("[2/5] Building nationality and city URL lookups...")
    nat_lookup = {}
    for wid, name, url in conn.execute(
        "SELECT wikidata_id, name_en, en_wikipedia_url FROM nationalities WHERE en_wikipedia_url IS NOT NULL"
    ):
        nat_lookup[wid] = (name or "", url)

    city_lookup = {}
    for cid, name, url in conn.execute(
        "SELECT id, name_en, en_wikipedia_url_original_country_name FROM cities WHERE en_wikipedia_url_original_country_name IS NOT NULL"
    ):
        city_lookup[cid] = (name or "", url)
    log(f"    {len(nat_lookup)} nationalities, {len(city_lookup)} cities with URLs")

    # 3. Build set of individuals who already have an impact_date
    log("[3/5] Loading individuals with impact_date...")
    has_impact = set()
    for row in conn.execute("SELECT wikidata_id FROM individuals_impact_date"):
        has_impact.add(row[0])
    log(f"    {len(has_impact):,} individuals with impact_date")

    # 4. Process unmatched individuals in batches
    log("[4/5] Processing unmatched individuals for URL matches...")
    total_unmatched = conn.execute(
        """
        SELECT COUNT(*) FROM individuals i
        WHERE NOT EXISTS (SELECT 1 FROM individuals_cliopatria ic WHERE ic.wikidata_id = i.wikidata_id)
    """
    ).fetchone()[0]
    log(f"    {total_unmatched:,} unmatched individuals to check")

    offset = 0
    inserted = 0
    cnt_nat = 0
    cnt_death = 0
    cnt_birth = 0

    while True:
        rows = conn.execute(
            """
            SELECT i.wikidata_id, i.name_en, k.nationalities_ids, k.birthcity_id, k.deathcity_id
            FROM individuals i
            LEFT JOIN individuals_keys k ON i.wikidata_id = k.wikidata_id
            WHERE NOT EXISTS (SELECT 1 FROM individuals_cliopatria ic WHERE ic.wikidata_id = i.wikidata_id)
            ORDER BY i.rowid
            LIMIT ? OFFSET ?
        """,
            (BATCH, offset),
        ).fetchall()

        if not rows:
            break

        to_insert = []
        for wid, name_en, nat_ids, bc_id, dc_id in rows:
            # Skip if this individual HAS an impact_date (they were already
            # evaluated and either kept or correctly rejected by date check)
            if wid in has_impact:
                continue

            matched = None

            # Priority: URL nationality
            if nat_ids:
                for nat_id in nat_ids.split(";"):
                    nat_id = nat_id.strip()
                    if not nat_id:
                        continue
                    info = nat_lookup.get(nat_id)
                    if info:
                        nat_name, url = info
                        polity = url_to_polity.get(url)
                        if polity:
                            matched = (
                                polity[0],
                                polity[1],
                                "nationality",
                                nat_name,
                                nat_id,
                                "url",
                            )
                            break

            # Priority: URL deathcity
            if not matched and dc_id:
                dc_id = dc_id.strip()
                if dc_id:
                    info = city_lookup.get(dc_id)
                    if info:
                        city_name, url = info
                        polity = url_to_polity.get(url)
                        if polity:
                            matched = (
                                polity[0],
                                polity[1],
                                "deathplace",
                                city_name,
                                dc_id,
                                "url",
                            )

            # Priority: URL birthcity
            if not matched and bc_id:
                bc_id = bc_id.strip()
                if bc_id:
                    info = city_lookup.get(bc_id)
                    if info:
                        city_name, url = info
                        polity = url_to_polity.get(url)
                        if polity:
                            matched = (
                                polity[0],
                                polity[1],
                                "birthplace",
                                city_name,
                                bc_id,
                                "url",
                            )

            if matched:
                polity_name, polity_id, origin, matched_name, matched_wid, method = (
                    matched
                )
                to_insert.append(
                    (
                        wid,
                        name_en,
                        polity_name,
                        polity_id,
                        origin,
                        matched_name,
                        matched_wid,
                        method,
                    )
                )
                if origin == "nationality":
                    cnt_nat += 1
                elif origin == "deathplace":
                    cnt_death += 1
                else:
                    cnt_birth += 1

        if to_insert:
            conn.execute("BEGIN TRANSACTION")
            conn.executemany(
                """
                INSERT OR IGNORE INTO individuals_cliopatria
                (wikidata_id, name_en, polity_name, polity_id, origin, matched_name, matched_wikidata_id, method, impact_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
                to_insert,
            )
            conn.commit()
            inserted += len(to_insert)

        offset += len(rows)
        if offset % 500_000 < BATCH:
            log(
                f"    Progress: {offset:,}/{total_unmatched:,} checked, {inserted:,} inserted"
            )

    log(
        f"    Done: {inserted:,} URL matches added (nat:{cnt_nat:,}, death:{cnt_death:,}, birth:{cnt_birth:,})"
    )

    # 5. Update consolidate + individuals_count
    log("[5/5] Updating consolidate and polities_cliopatria...")

    added_to_consolidate = conn.execute(
        """
        INSERT INTO consolidate (wikidata_id, name_en, impact_year, polity_name, occupations, gender, references_count)
        SELECT ic.wikidata_id, ic.name_en, NULL, ic.polity_name, i.occupations_en, i.gender, i.identifiers_count
        FROM individuals_cliopatria ic
        JOIN individuals i ON ic.wikidata_id = i.wikidata_id
        WHERE ic.method = 'url' AND ic.impact_date IS NULL
        AND NOT EXISTS (SELECT 1 FROM consolidate c WHERE c.wikidata_id = ic.wikidata_id)
    """,
        [],
    ).rowcount
    conn.commit()
    log(f"    Added {added_to_consolidate:,} rows to consolidate")

    # Update individuals_count in polities_cliopatria
    conn.execute("UPDATE polities_cliopatria SET individuals_count = 0")
    conn.execute(
        """
        UPDATE polities_cliopatria SET individuals_count = (
            SELECT COUNT(*) FROM individuals_cliopatria ic
            WHERE ic.polity_id = polities_cliopatria.id
        )
    """
    )
    conn.commit()
    log("    Updated polities_cliopatria.individuals_count")

    # Final stats
    ic_total = conn.execute("SELECT COUNT(*) FROM individuals_cliopatria").fetchone()[0]
    co_total = conn.execute("SELECT COUNT(*) FROM consolidate").fetchone()[0]
    log(f"    individuals_cliopatria: {ic_total:,}")
    log(f"    consolidate: {co_total:,}")

    conn.close()
    log("=== Done ===")


if __name__ == "__main__":
    main()
