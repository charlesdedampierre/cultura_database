"""One-off schema migration for humans_clean.sqlite3 (2026-05).

Applies, in one transaction:

1. Drops legacy tables (already exported to data/legacy_regions/*.csv):
       regions, individuals_regions, individuals_countries, modern_country
2. Drops `individuals_impact_date` (superseded by `individuals_floruit_period`).
3. Renames tables:
       sitelinks                  -> wikimedia_links
       nationalities              -> country_of_citizenship
       cliopatria_polity_periods  -> polities_periods_cliopatria
4. Renames columns:
       individuals.nationalities_en        -> country_of_citizenship_en
       individuals.sitelinks_count         -> wikimedia_links_count
       individuals_keys.nationalities_ids  -> country_of_citizenship_ids
       individuals_cliopatria.impact_date  -> floruit_year
       consolidate.impact_year             -> floruit_year
5. Repopulates `properties_definition` with the canonical Wikidata
   property catalogue, pointing at the new table/column names.

All RENAME and DROP operations are metadata-only in SQLite, so this is
fast even on the 24 GB DB. Run with the .venv active.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"

TABLES_TO_DROP = [
    "regions",
    "individuals_regions",
    "individuals_countries",
    "modern_country",
    "individuals_impact_date",
]

TABLE_RENAMES = [
    ("sitelinks", "wikimedia_links"),
    ("nationalities", "country_of_citizenship"),
    ("cliopatria_polity_periods", "polities_periods_cliopatria"),
]

COLUMN_RENAMES = [
    ("individuals", "nationalities_en", "country_of_citizenship_en"),
    ("individuals", "sitelinks_count", "wikimedia_links_count"),
    ("individuals_keys", "nationalities_ids", "country_of_citizenship_ids"),
    ("individuals_cliopatria", "impact_date", "floruit_year"),
    ("consolidate", "impact_year", "floruit_year"),
]

# Index names are cosmetic — SQLite has no `ALTER INDEX RENAME`, and
# DROP+CREATE on multi-million-row indexes is expensive. We leave the
# old names in place; the indexes still cover the renamed columns
# correctly because ALTER TABLE RENAME COLUMN auto-rewrites their
# definitions.

# Canonical Wikidata properties used across the pipeline. Columns refer
# to the post-rename schema. Multi-table fields are listed per (table,
# column) to keep one row per location.
PROPERTIES: list[tuple[str, str, str, str, str]] = [
    # (property_id, property_name, description, table_name, column_name)
    ("rdfs:label", "label (English)", "English label of the entity",
     "individuals", "name_en"),
    ("rdfs:label", "label (English)", "English label of the entity",
     "occupations", "name_en"),
    ("rdfs:label", "label (English)", "English label of the entity",
     "country_of_citizenship", "name_en"),
    ("rdfs:label", "label (English)", "English label of the entity",
     "cities", "name_en"),
    ("rdfs:label", "label (English)", "English label of the entity",
     "writing_languages", "name"),
    ("schema:description", "description (English)",
     "English description of the entity",
     "individuals", "description_en"),
    ("schema:description", "description (English)",
     "English description of the entity",
     "country_of_citizenship", "description_en"),
    ("schema:description", "description (English)",
     "English description of the entity",
     "occupations", "description_en"),
    ("schema:about", "Wikipedia/Wikimedia link",
     "Sitelink URL pointing at a Wikimedia project page",
     "wikimedia_links", "url"),

    # Place / coordinate properties
    ("P17", "country",
     "sovereign state that this item is in",
     "cities", "country_id"),
    ("P17", "country",
     "sovereign state that this item is in",
     "country_of_citizenship", "country_id"),
    ("P19", "place of birth",
     "most specific known birth location of a person",
     "individuals", "birthcity_id"),
    ("P19", "place of birth",
     "most specific known birth location of a person",
     "individuals", "birthcity_en"),
    ("P19", "place of birth",
     "most specific known birth location of a person",
     "individuals_keys", "birthcity_id"),
    ("P20", "place of death",
     "most specific known death location of a person",
     "individuals", "deathcity_id"),
    ("P20", "place of death",
     "most specific known death location of a person",
     "individuals", "deathcity_en"),
    ("P20", "place of death",
     "most specific known death location of a person",
     "individuals_keys", "deathcity_id"),
    ("P21", "sex or gender",
     "sex or gender identity of a human",
     "individuals", "gender"),
    ("P21", "sex or gender",
     "sex or gender identity of a human",
     "individuals_keys", "gender_id"),
    ("P27", "country of citizenship",
     "country that recognizes the subject as its citizen",
     "individuals", "country_of_citizenship_en"),
    ("P27", "country of citizenship",
     "country that recognizes the subject as its citizen",
     "individuals_keys", "country_of_citizenship_ids"),
    ("P27", "country of citizenship",
     "country that recognizes the subject as its citizen",
     "country_of_citizenship", "wikidata_id"),
    ("P31", "instance of",
     "class of which the subject is an instance",
     "cities", "entity_type_ids"),
    ("P31", "instance of",
     "class of which the subject is an instance",
     "country_of_citizenship", "instance_of"),
    ("P36", "capital",
     "primary city of a country",
     "country_of_citizenship", "lat,lon"),
    ("P106", "occupation",
     "occupation of a person",
     "individuals", "occupations_en"),
    ("P106", "occupation",
     "occupation of a person",
     "occupations", "id"),
    ("P106", "occupation",
     "occupation of a person",
     "individuals_keys", "occupations_ids"),
    ("P569", "date of birth",
     "date on which the subject was born",
     "individuals", "birthdate"),
    ("P569", "date of birth",
     "date on which the subject was born",
     "individuals", "birthdate_precision"),
    ("P569", "date of birth",
     "date on which the subject was born",
     "individuals_floruit_period", "birthdate"),
    ("P570", "date of death",
     "date on which the subject died",
     "individuals", "deathdate"),
    ("P570", "date of death",
     "date on which the subject died",
     "individuals", "deathdate_precision"),
    ("P570", "date of death",
     "date on which the subject died",
     "individuals_floruit_period", "deathdate"),
    ("P625", "coordinate location",
     "geographic coordinates",
     "cities", "lat,lon"),
    ("P625", "coordinate location",
     "geographic coordinates",
     "country_of_citizenship", "lat,lon"),
    ("P1317", "floruit",
     "date when the person was active",
     "individuals_floruit", "floruit_date"),
    ("P1317", "floruit",
     "date when the person was active",
     "individuals_floruit_period", "floruit_date"),
    ("P1366", "replaced by",
     "entity replacing this item",
     "country_of_citizenship", "replaced_by"),
    ("P6886", "writing language",
     "language a person is producing literary or scientific works in",
     "individuals", "writing_language_name_en"),
    ("P6886", "writing language",
     "language a person is producing literary or scientific works in",
     "individual_writing_languages", "language_id"),
    ("P6886", "writing language",
     "language a person is producing literary or scientific works in",
     "individuals_keys", "writing_language_ids"),
    # Work-relationship properties (every row in `works`)
    ("P50", "author",
     "main creator(s) of a written work",
     "works", "relationship='P50'"),
    ("P57", "director",
     "director of a film/show",
     "works", "relationship='P57'"),
    ("P58", "screenwriter",
     "screenwriter of a film/show",
     "works", "relationship='P58'"),
    ("P86", "composer",
     "composer of a musical work",
     "works", "relationship='P86'"),
    ("P98", "editor",
     "editor of a book/journal",
     "works", "relationship='P98'"),
    ("P110", "illustrator",
     "person who illustrated this book or document",
     "works", "relationship='P110'"),
    ("P162", "producer",
     "person who produced a film/show",
     "works", "relationship='P162'"),
    ("P170", "creator",
     "maker of a creative work",
     "works", "relationship='P170'"),
    ("P175", "performer",
     "performer involved in this work",
     "works", "relationship='P175'"),
    # External identifiers (one row per Pxxx is in identifier_types)
    ("(any external-ID Pxxx)", "external identifier",
     "every wikibase:ExternalId property used by any Q5 human",
     "identifier_types", "property_id"),
    ("(any external-ID Pxxx)", "external identifier",
     "every wikibase:ExternalId property used by any Q5 human",
     "identifiers", "property_id"),
]


def _drop(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    print(f"  dropped {table}")


def _rename_table(conn: sqlite3.Connection, old: str, new: str) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (old,)
    ).fetchone():
        print(f"  skip rename {old} -> {new} (source missing)")
        return
    conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
    print(f"  renamed table {old} -> {new}")


def _rename_column(conn: sqlite3.Connection, table: str, old: str, new: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    cols = {r[1] for r in rows}
    if old not in cols:
        print(f"  skip rename {table}.{old} -> {new} (col missing)")
        return
    if new in cols:
        print(f"  skip rename {table}.{old} -> {new} (target exists)")
        return
    conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")
    print(f"  renamed col {table}.{old} -> {new}")


def _rebuild_properties_definition(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS properties_definition")
    conn.execute(
        """
        CREATE TABLE properties_definition (
            property_id TEXT,
            property_name TEXT,
            description TEXT,
            table_name TEXT,
            column_name TEXT,
            PRIMARY KEY (property_id, table_name, column_name)
        )
        """
    )
    # Only keep rows whose (table, column) actually exists in this DB.
    # `column_name` may be a single column, a composite "lat,lon", a
    # table-wide marker (the entity's PK), or a relationship filter
    # (`relationship='Pxxx'`) — accept all of those.
    def col_exists(table: str, col_spec: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        if not rows:
            return False
        cols = {r[1] for r in rows}
        if col_spec.startswith("relationship="):
            return "relationship" in cols
        for c in col_spec.split(","):
            if c.strip() not in cols:
                return False
        return True

    kept, dropped = [], []
    for row in PROPERTIES:
        _, _, _, table, col = row
        if col_exists(table, col):
            kept.append(row)
        else:
            dropped.append(row)

    conn.executemany(
        "INSERT OR IGNORE INTO properties_definition "
        "(property_id, property_name, description, table_name, column_name) "
        "VALUES (?, ?, ?, ?, ?)",
        kept,
    )
    conn.execute(
        "CREATE INDEX idx_pd_table ON properties_definition(table_name)"
    )
    if dropped:
        print(f"  skipped {len(dropped)} property rows whose column "
              "does not exist in this DB:")
        for row in dropped:
            print(f"    - {row[0]} -> {row[3]}.{row[4]}")
    return len(kept)


def main() -> None:
    print(f"[migrate] opening {DB}")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        conn.execute("BEGIN")

        print("\n[migrate] dropping legacy tables (idempotent)")
        for t in TABLES_TO_DROP:
            _drop(conn, t)

        # SQLite cannot ALTER TABLE on a renamed column if any auto-named
        # index references the original name; ALTER COLUMN auto-rewrites
        # indexes since 3.25, so we rename columns BEFORE renaming tables
        # to keep error messages aligned with the schema we audited.
        print("\n[migrate] renaming columns (idempotent)")
        for table, old, new in COLUMN_RENAMES:
            _rename_column(conn, table, old, new)

        print("\n[migrate] renaming tables (idempotent)")
        for old, new in TABLE_RENAMES:
            _rename_table(conn, old, new)

        print("\n[migrate] rebuilding properties_definition")
        n = _rebuild_properties_definition(conn)
        print(f"  inserted {n} property rows")

        conn.commit()
        print("\n[migrate] committed")
    except Exception:
        conn.rollback()
        print("[migrate] ROLLED BACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
