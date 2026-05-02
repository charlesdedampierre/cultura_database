"""One-off: rewrite works.relationship from raw P-ids to human-readable
role names ("author", "director", ...) and re-point the matching
`wikidata_properties_definition` rows.

Idempotent: only updates rows whose value still starts with `P`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB = PROJECT_ROOT / "data" / "humans_clean.sqlite3"

RELATIONSHIP_BY_PID = {
    "P50":  "author",
    "P57":  "director",
    "P58":  "screenwriter",
    "P86":  "composer",
    "P98":  "editor",
    "P110": "illustrator",
    "P162": "producer",
    "P170": "creator",
    "P175": "performer",
}


def main() -> None:
    print(f"[works-rel] opening {DB}")
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        cur = conn.cursor()

        before_pid = cur.execute(
            "SELECT COUNT(*) FROM works WHERE relationship LIKE 'P%'"
        ).fetchone()[0]
        print(f"  rows still labelled with a P-id: {before_pid:,}")

        for pid, name in RELATIONSHIP_BY_PID.items():
            cur.execute(
                "UPDATE works SET relationship = ? WHERE relationship = ?",
                (name, pid),
            )
            print(f"  P{pid[1:]:>3} -> {name:<13} updated {cur.rowcount:>10,} rows")
            conn.commit()

        leftover = cur.execute(
            "SELECT relationship, COUNT(*) FROM works "
            "WHERE relationship LIKE 'P%' GROUP BY relationship"
        ).fetchall()
        if leftover:
            print("  leftover P-id values still in works.relationship:")
            for r, n in leftover:
                print(f"    {r}: {n:,}")
        else:
            print("  works.relationship fully migrated to role names")

        # Re-point wikidata_properties_definition entries: change
        # column_name from "relationship='P50'" to "relationship='author'".
        for pid, name in RELATIONSHIP_BY_PID.items():
            cur.execute(
                "UPDATE wikidata_properties_definition "
                "SET column_name = ? "
                "WHERE table_name = 'works' AND column_name = ?",
                (f"relationship='{name}'", f"relationship='{pid}'"),
            )
        conn.commit()

        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_works_rel ON works(relationship)"
        )
        conn.commit()

        print("[works-rel] committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
