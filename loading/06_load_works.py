"""Load works data into SQLite.

Reads: notable_works.json, authored_works.json, work_instances.json, work_identifiers.json
Creates: works, individual_works, work_identifiers tables
"""

import json
import os
import sqlite3

from tqdm import tqdm
from utils import EXTRACTED_DIR, clean_date, get_db_connection

WORKS_DIR = os.path.join(EXTRACTED_DIR, "works")


def create_tables(conn: sqlite3.Connection):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS works (
            work_wikidata_id        TEXT PRIMARY KEY,
            work_name               TEXT,
            instance_wikidata_id    TEXT,
            instance_label          TEXT,
            super_instance_wikidata_id TEXT,
            super_instance_label    TEXT,
            work_category           TEXT,
            creation_year           INTEGER
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS individual_works (
            wikidata_id      TEXT,
            work_wikidata_id TEXT,
            relationship     TEXT DEFAULT 'creator'
        )
    """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS work_identifiers (
            work_wikidata_id       TEXT,
            identifier_wikidata_id TEXT,
            identifier_name        TEXT
        )
    """
    )
    conn.commit()


def main():
    conn = get_db_connection()
    create_tables(conn)

    conn.execute("DELETE FROM works")
    conn.execute("DELETE FROM individual_works")
    conn.execute("DELETE FROM work_identifiers")

    # Load work instance hierarchy
    instance_hierarchy = {}
    instances_path = os.path.join(WORKS_DIR, "work_instances.json")
    if os.path.exists(instances_path):
        with open(instances_path) as f:
            instances = json.load(f)
        for inst in instances:
            instance_hierarchy[inst["instance_wikidata_id"]] = {
                "super_instance_wikidata_id": inst.get("super_instance_wikidata_id"),
                "super_instance_label": inst.get("super_instance_label", ""),
            }

    # Collect all works from notable and authored
    all_works = {}
    individual_works = []

    for filename, default_rel in [
        ("notable_works.json", "notable_work"),
        ("authored_works.json", "creator"),
    ]:
        filepath = os.path.join(WORKS_DIR, filename)
        if not os.path.exists(filepath):
            continue

        with open(filepath) as f:
            work_list = json.load(f)

        for w in tqdm(work_list, desc=f"Processing {filename}"):
            wk_id = w.get("work_wikidata_id", "")
            if not wk_id or not wk_id.startswith("Q"):
                continue

            # Add individual-work mapping
            individual_works.append(
                (
                    w["individual_wikidata_id"],
                    wk_id,
                    w.get("relationship", default_rel),
                )
            )

            # Add/update work info (first occurrence wins for metadata)
            if wk_id not in all_works:
                inst_id = w.get("instance_wikidata_id")
                hierarchy = instance_hierarchy.get(inst_id, {})
                creation_year = clean_date(w.get("inception", ""))

                all_works[wk_id] = (
                    wk_id,
                    w.get("work_name", ""),
                    inst_id,
                    w.get("instance_label", ""),
                    hierarchy.get("super_instance_wikidata_id"),
                    hierarchy.get("super_instance_label", ""),
                    None,  # work_category (can be enriched later)
                    creation_year,
                )

    # Insert works
    conn.executemany(
        "INSERT OR REPLACE INTO works VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        list(all_works.values()),
    )

    # Insert individual-work mappings (deduplicate)
    seen = set()
    deduped_iw = []
    for iw in individual_works:
        key = (iw[0], iw[1])
        if key not in seen:
            seen.add(key)
            deduped_iw.append(iw)

    conn.executemany("INSERT INTO individual_works VALUES (?, ?, ?)", deduped_iw)

    # Load work identifiers
    wk_id_path = os.path.join(WORKS_DIR, "work_identifiers.json")
    if os.path.exists(wk_id_path):
        with open(wk_id_path) as f:
            wk_ids_data = json.load(f)

        wk_id_rows = []
        for entry in wk_ids_data:
            wk_id = entry["work_wikidata_id"]
            for ident in entry.get("identifiers", []):
                wk_id_rows.append(
                    (
                        wk_id,
                        ident["identifier_wikidata_id"],
                        ident["identifier_name"],
                    )
                )

        conn.executemany("INSERT INTO work_identifiers VALUES (?, ?, ?)", wk_id_rows)

    conn.commit()

    works_count = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    iw_count = conn.execute("SELECT COUNT(*) FROM individual_works").fetchone()[0]
    wi_count = conn.execute("SELECT COUNT(*) FROM work_identifiers").fetchone()[0]
    print(
        f"Loaded {works_count} works, {iw_count} individual-work mappings, {wi_count} work identifiers"
    )

    conn.close()


if __name__ == "__main__":
    main()
