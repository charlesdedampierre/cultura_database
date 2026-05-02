"""One-off schema migration for humans_clean.sqlite3 (2026-05, part 2).

Applies, in one transaction:

1. Renames tables for clarity:
       cities                -> places
       consolidate           -> consolidated_database
       properties_definition -> wikidata_properties_definition
2. Folds `individuals_floruit` into `individuals` and drops the
   standalone table:
       adds individuals.floruit_date / floruit_precision / floruit_year
       UPDATEs them from individuals_floruit
       DROPs individuals_floruit

Idempotent — every step checks current state before acting.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"

TABLE_RENAMES = [
    ("cities", "places"),
    ("consolidate", "consolidated_database"),
    ("properties_definition", "wikidata_properties_definition"),
]

FLORUIT_COLUMNS = [
    ("floruit_date", "TEXT"),
    ("floruit_precision", "INTEGER"),
    ("floruit_year", "INTEGER"),
]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _rename_table(conn: sqlite3.Connection, old: str, new: str) -> None:
    if not _table_exists(conn, old):
        print(f"  skip rename {old} -> {new} (source missing)")
        return
    if _table_exists(conn, new):
        print(f"  skip rename {old} -> {new} (target already exists)")
        return
    conn.execute(f"ALTER TABLE {old} RENAME TO {new}")
    print(f"  renamed table {old} -> {new}")


def _fold_floruit_into_individuals(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "individuals"):
        print("  skip fold: individuals table missing")
        return

    cols = _columns(conn, "individuals")
    for name, decl in FLORUIT_COLUMNS:
        if name in cols:
            continue
        conn.execute(f"ALTER TABLE individuals ADD COLUMN {name} {decl}")
        print(f"  added individuals.{name} {decl}")

    if _table_exists(conn, "individuals_floruit"):
        before = conn.execute(
            "SELECT COUNT(*) FROM individuals WHERE floruit_year IS NOT NULL"
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE individuals
            SET floruit_date      = (SELECT floruit_date      FROM individuals_floruit f WHERE f.wikidata_id = individuals.wikidata_id),
                floruit_precision = (SELECT floruit_precision FROM individuals_floruit f WHERE f.wikidata_id = individuals.wikidata_id),
                floruit_year      = (SELECT floruit_year      FROM individuals_floruit f WHERE f.wikidata_id = individuals.wikidata_id)
            WHERE wikidata_id IN (SELECT wikidata_id FROM individuals_floruit)
            """
        )
        after = conn.execute(
            "SELECT COUNT(*) FROM individuals WHERE floruit_year IS NOT NULL"
        ).fetchone()[0]
        print(f"  filled floruit on individuals: {before} -> {after}")

        conn.execute("DROP TABLE individuals_floruit")
        print("  dropped individuals_floruit")
    else:
        print("  individuals_floruit already absent (idempotent)")

    # Index on the new floruit_year column.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_individuals_floruit_year "
        "ON individuals(floruit_year)"
    )


def main() -> None:
    print(f"[migrate-2] opening {DB}")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        conn.execute("BEGIN")

        print("\n[migrate-2] renaming tables")
        for old, new in TABLE_RENAMES:
            _rename_table(conn, old, new)

        print("\n[migrate-2] folding individuals_floruit into individuals")
        _fold_floruit_into_individuals(conn)

        conn.commit()
        print("\n[migrate-2] committed")
    except Exception:
        conn.rollback()
        print("[migrate-2] ROLLED BACK")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
