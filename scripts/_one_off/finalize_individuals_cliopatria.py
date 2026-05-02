"""Finish what 04_individuals_cliopatria.py started: create the few
trailing indexes and refresh polities_cliopatria.number_individuals.

The full match committed 6,128,228 rows, then crashed on a CREATE INDEX
with `database is locked` (a stale handle on the .sqlite3 file). This
script re-opens the DB cleanly and runs only the missing steps.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = (Path(__file__).resolve().parents[2]
      / "data" / "humans_clean.sqlite3")


def main() -> None:
    print(f"[finalize] opening {DB}")
    # Wait up to 2h for any concurrent writer (e.g. the identifier-load
    # job) to release the lock before erroring out.
    conn = sqlite3.connect(DB, timeout=7200)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=7200000")
    try:
        for sql in (
            "CREATE INDEX IF NOT EXISTS idx_ic_method "
            "ON individuals_cliopatria(method)",
            "CREATE INDEX IF NOT EXISTS idx_ic_matched_wid "
            "ON individuals_cliopatria(matched_wikidata_id)",
            "CREATE INDEX IF NOT EXISTS idx_ic_floruit_start "
            "ON individuals_cliopatria(floruit_period_start)",
            "CREATE INDEX IF NOT EXISTS idx_ic_floruit_end "
            "ON individuals_cliopatria(floruit_period_end)",
        ):
            print(f"  {sql}")
            conn.execute(sql)
        conn.commit()

        print("\n[finalize] refreshing polities_cliopatria.number_individuals")
        counts: dict[int, int] = {}
        for (pid_str,) in conn.execute(
            "SELECT polity_id FROM individuals_cliopatria"
        ):
            if not pid_str:
                continue
            for p in pid_str.split(";"):
                p = p.strip()
                if p.isdigit() or (p.startswith("-") and p[1:].isdigit()):
                    counts[int(p)] = counts.get(int(p), 0) + 1
        print(f"  computed counts for {len(counts)} polities")
        cols = {r[1] for r in conn.execute(
            "PRAGMA table_info(polities_cliopatria)"
        )}
        if "number_individuals" not in cols:
            conn.execute(
                "ALTER TABLE polities_cliopatria "
                "ADD COLUMN number_individuals INTEGER DEFAULT 0"
            )
        conn.execute("UPDATE polities_cliopatria SET number_individuals = 0")
        conn.executemany(
            "UPDATE polities_cliopatria SET number_individuals = ? WHERE id = ?",
            [(c, pid) for pid, c in counts.items()],
        )
        conn.commit()

        # Pull the final row counts to confirm.
        n_indiv = conn.execute(
            "SELECT COUNT(*) FROM individuals_cliopatria"
        ).fetchone()[0]
        n_with_pol = conn.execute(
            "SELECT SUM(number_individuals) FROM polities_cliopatria"
        ).fetchone()[0]
        print(f"\n[finalize] individuals_cliopatria rows: {n_indiv:,}")
        print(f"           sum(polities.number_individuals): {n_with_pol:,}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
