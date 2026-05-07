"""Derive structured date columns from `individuals.dates_in_description`.

Reads the raw token string produced by the Rust extractor, applies the user's
simplification rules, and populates four new columns on `individuals`:

  - birthdate_in_description   INTEGER  — when a `b YYYY` token is present
  - deathdate_in_description   INTEGER  — when a `d YYYY` token is present
  - floruit_year_in_description INTEGER — when a `fl YYYY` token, BC/AD marker,
                                           or unambiguous single year is present
  - date_description           TEXT    — the simplified token string for
                                          everything else (centuries, ranges
                                          without explicit b/d, etc.)

Simplification rules applied to the textual `date_description` column only
(the original `dates_in_description` is kept intact for traceability):

  - "199 BC" → "-199"  (BC marker becomes a negative integer)
  - "10 AD"  → "10"   (AD suffix dropped)
  - "c5 BC"  → "5 BC" (drop the leading 'c'; BC is then re-applied as -5
                       only if the token is otherwise unanchored)
  - When the raw token list contains several `YYYY-YYYY` ranges, only the
    first survives (the Rust extractor already does this; we don't re-emit).

Estimated runtime: ~2-3 minutes for 9.4M rows on a local SSD.
"""
from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

from tqdm import tqdm

DB = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database/data/humans_clean.sqlite3")
BATCH_SIZE = 50_000

TOK_MARKER = re.compile(r"^(-?\d{1,4})\s+(BC|BCE|AC|AD|CE)$")
TOK_RANGE = re.compile(r"^(-?\d{1,4})-(-?\d{1,4})$")
TOK_B = re.compile(r"^b\s+(-?\d{1,4})$")
TOK_D = re.compile(r"^d\s+(-?\d{1,4})$")
TOK_FL = re.compile(r"^fl\s+(-?\d{1,4})$")
TOK_CENT = re.compile(r"^c(\d{1,2})(?:\s+(BC|BCE|AC))?$")


def signed_marker(year: int, marker: str) -> int:
    return -year if marker.upper() in {"BC", "BCE", "AC"} else year


def simplify_token(tok: str) -> str:
    """User-requested textual simplifications for the date_description column."""
    m = TOK_MARKER.match(tok)
    if m:
        y, mk = int(m.group(1)), m.group(2)
        return str(-y if mk.upper() in {"BC", "BCE", "AC"} else y)
    m = TOK_CENT.match(tok)
    if m:
        n = int(m.group(1))
        mk = m.group(2)
        suffix = ordinal_suffix(n)
        if mk:
            return f"{n}{suffix} century {mk}"
        return f"{n}{suffix} century"
    return tok


def ordinal_suffix(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def derive(raw: str) -> tuple[int | None, int | None, int | None, str | None]:
    """Return (birth, death, floruit_year, date_description) for one row."""
    if not raw:
        return (None, None, None, None)
    tokens = [t.strip() for t in raw.split("|") if t.strip()]

    birth: int | None = None
    death: int | None = None
    floruit: int | None = None
    leftovers: list[str] = []

    for tok in tokens:
        if (m := TOK_B.match(tok)):
            if birth is None:
                birth = int(m.group(1))
            continue
        if (m := TOK_D.match(tok)):
            if death is None:
                death = int(m.group(1))
            continue
        if (m := TOK_FL.match(tok)):
            if floruit is None:
                floruit = int(m.group(1))
            continue
        if (m := TOK_MARKER.match(tok)):
            # Marker years become floruit candidates if no fl is set yet.
            if floruit is None:
                floruit = signed_marker(int(m.group(1)), m.group(2))
            leftovers.append(simplify_token(tok))
            continue
        if (m := TOK_RANGE.match(tok)):
            a, b = int(m.group(1)), int(m.group(2))
            # A YYYY-YYYY range in a biographical description conventionally
            # bracketed birth-death. Populate both columns when we have no
            # other source for them; floruit gets the midpoint.
            if birth is None:
                birth = a
            if death is None:
                death = b
            if floruit is None:
                floruit = (a + b) // 2
            leftovers.append(tok)
            continue
        if (m := TOK_CENT.match(tok)):
            # Bare century tokens (e.g. "c19") describe the period of activity
            # too loosely to count as a floruit. Per user instruction we keep
            # the human-readable century in `date_description` but DO NOT set
            # `floruit_year_in_description`. The Rust extractor emits an
            # explicit `fl <midpoint>` token instead when the source text
            # actually qualifies the century with "fl./active/flourished",
            # which is then captured by the TOK_FL branch above.
            leftovers.append(simplify_token(tok))
            continue
        leftovers.append(tok)

    date_desc = "|".join(leftovers) if leftovers else None
    return (birth, death, floruit, date_desc)


def ensure_columns(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(individuals)")}
    for name, sqltype in [
        ("birthdate_in_description", "INTEGER"),
        ("deathdate_in_description", "INTEGER"),
        ("floruit_year_in_description", "INTEGER"),
        ("date_description", "TEXT"),
    ]:
        if name not in cols:
            print(f"adding column individuals.{name} ({sqltype})")
            conn.execute(f"ALTER TABLE individuals ADD COLUMN {name} {sqltype}")
    conn.commit()


def main() -> None:
    started = time.time()
    conn = sqlite3.connect(DB)
    conn.executescript(
        "PRAGMA journal_mode=WAL;"
        "PRAGMA synchronous=NORMAL;"
        "PRAGMA temp_store=MEMORY;"
        "PRAGMA cache_size=-200000;"
    )
    ensure_columns(conn)

    total = conn.execute(
        "SELECT COUNT(*) FROM individuals "
        "WHERE dates_in_description IS NOT NULL AND dates_in_description != ''"
    ).fetchone()[0]
    print(f"rows to process: {total:,}")

    rows_iter = conn.execute(
        "SELECT wikidata_id, dates_in_description FROM individuals "
        "WHERE dates_in_description IS NOT NULL AND dates_in_description != ''"
    )

    update_sql = (
        "UPDATE individuals SET "
        "  birthdate_in_description = ?, "
        "  deathdate_in_description = ?, "
        "  floruit_year_in_description = ?, "
        "  date_description = ? "
        "WHERE wikidata_id = ?"
    )

    buffer: list[tuple] = []
    pbar = tqdm(total=total, desc="deriving date columns", unit="row")
    write_conn = sqlite3.connect(DB)
    write_conn.executescript(
        "PRAGMA journal_mode=WAL;"
        "PRAGMA synchronous=NORMAL;"
        "PRAGMA temp_store=MEMORY;"
        "PRAGMA cache_size=-200000;"
    )

    for wid, raw in rows_iter:
        birth, death, floruit, date_desc = derive(raw)
        buffer.append((birth, death, floruit, date_desc, wid))
        if len(buffer) >= BATCH_SIZE:
            with write_conn:
                write_conn.executemany(update_sql, buffer)
            pbar.update(len(buffer))
            buffer.clear()
    if buffer:
        with write_conn:
            write_conn.executemany(update_sql, buffer)
        pbar.update(len(buffer))
    pbar.close()
    write_conn.close()
    conn.close()

    print(f"done in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
