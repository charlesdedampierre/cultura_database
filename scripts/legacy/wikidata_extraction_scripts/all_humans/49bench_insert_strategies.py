"""Benchmark four INSERT strategies on a 250K-row representative subset.

Build a fixed scratch input (`_bench_stage`) once — drawn from properties
that did NOT exist in the original identifiers table — so every strategy
operates on the same 250K representative rows.

Strategies
----------
A  JOIN INSERT OR IGNORE with all 3 secondary indexes in place (baseline)
B  drop 3 indexes, JOIN INSERT OR IGNORE, recreate 1 index (extrapolated)
C  bare INSERT OR IGNORE (wikidata_id, property_id, value) only — no JOINs
   leaves individual_name/identifier_name NULL for new rows
D  C followed by an UPDATE pass to fill names via JOIN

Each timed body is wrapped in BEGIN/ROLLBACK so the main DB is untouched.

Output: terminal + logs/insert_strategy_bench.log
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "humans_clean.sqlite3"
LOG = ROOT / "logs" / "insert_strategy_bench.log"

SAMPLE_SIZE = 250_000
FULL_TARGET = 29_000_000


def fmt(d: float) -> str:
    return f"{d:.1f}s" if d < 60 else f"{d/60:.1f}min"


def log(line: str) -> None:
    print(line, flush=True)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def open_db() -> sqlite3.Connection:
    c = sqlite3.connect(DB, timeout=60, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=OFF")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-2000000")
    return c


def build_scratch_input(conn: sqlite3.Connection) -> int:
    """Precompute a fixed 250K-row sample from genuinely-new properties."""
    log("[setup] building _bench_stage from properties NOT in identifiers")
    conn.execute("DROP TABLE IF EXISTS _bench_stage")
    conn.execute("DROP TABLE IF EXISTS _bench_new_pids")
    t0 = time.time()
    conn.execute("""
        CREATE TEMP TABLE _bench_new_pids AS
        SELECT property_id FROM (
            SELECT DISTINCT property_id FROM _stage_identifiers
        )
        WHERE property_id NOT IN (
            SELECT DISTINCT property_id FROM identifiers
        )
    """)
    n_new = conn.execute("SELECT COUNT(*) FROM _bench_new_pids").fetchone()[0]
    log(f"[setup] {n_new:,} new property IDs available  ({fmt(time.time()-t0)})")

    t0 = time.time()
    conn.execute(f"""
        CREATE TABLE _bench_stage AS
        SELECT s.wikidata_id, s.property_id, s.value
        FROM _stage_identifiers s
        WHERE s.property_id IN (SELECT property_id FROM _bench_new_pids)
        LIMIT {SAMPLE_SIZE}
    """)
    n = conn.execute("SELECT COUNT(*) FROM _bench_stage").fetchone()[0]
    log(f"[setup] _bench_stage populated with {n:,} rows  ({fmt(time.time()-t0)})")
    return n


JOIN_INSERT = """
INSERT OR IGNORE INTO identifiers
    (wikidata_id, individual_name, property_id, identifier_name, value, url)
SELECT s.wikidata_id, i.name_en, s.property_id, t.name_en, s.value, NULL
FROM _bench_stage s
LEFT JOIN individuals      i ON i.wikidata_id = s.wikidata_id
LEFT JOIN identifier_types t ON t.property_id = s.property_id
"""

BARE_INSERT = """
INSERT OR IGNORE INTO identifiers (wikidata_id, property_id, value)
SELECT wikidata_id, property_id, value FROM _bench_stage
"""

UPDATE_NAMES = """
UPDATE identifiers
SET individual_name = (SELECT name_en FROM individuals
                        WHERE individuals.wikidata_id = identifiers.wikidata_id),
    identifier_name = (SELECT name_en FROM identifier_types
                        WHERE identifier_types.property_id = identifiers.property_id)
WHERE individual_name IS NULL
  AND wikidata_id IN (SELECT wikidata_id FROM _bench_stage)
"""


def bench_A(conn: sqlite3.Connection) -> float:
    log("[A] JOIN INSERT with all indexes")
    conn.execute("BEGIN")
    t0 = time.time()
    conn.execute(JOIN_INSERT)
    elapsed = time.time() - t0
    conn.execute("ROLLBACK")
    log(f"[A] {fmt(elapsed)}  ({SAMPLE_SIZE/elapsed:,.0f} rows/s)")
    return elapsed


def bench_B(conn: sqlite3.Connection) -> tuple[float, float]:
    log("[B] drop-3-indexes / JOIN INSERT / recreate one index")
    conn.execute("BEGIN")
    conn.execute("DROP INDEX idx_identifiers_wikidata")
    conn.execute("DROP INDEX idx_identifiers_property")
    conn.execute("DROP INDEX idx_identifiers_name")
    t0 = time.time()
    conn.execute(JOIN_INSERT)
    insert_elapsed = time.time() - t0
    log(f"[B] INSERT  {fmt(insert_elapsed)}  ({SAMPLE_SIZE/insert_elapsed:,.0f} rows/s)")

    t0 = time.time()
    conn.execute("CREATE INDEX idx_identifiers_wikidata ON identifiers(wikidata_id)")
    one_idx = time.time() - t0
    log(f"[B] CREATE INDEX(wikidata_id) on existing 30M rows: {fmt(one_idx)}")
    conn.execute("ROLLBACK")
    return insert_elapsed, one_idx


def bench_C(conn: sqlite3.Connection) -> float:
    log("[C] BARE INSERT (no JOINs, names left NULL) with all indexes")
    conn.execute("BEGIN")
    t0 = time.time()
    conn.execute(BARE_INSERT)
    elapsed = time.time() - t0
    conn.execute("ROLLBACK")
    log(f"[C] {fmt(elapsed)}  ({SAMPLE_SIZE/elapsed:,.0f} rows/s)")
    return elapsed


def bench_E(conn: sqlite3.Connection) -> tuple[float, float]:
    log("[E] drop-3-indexes / BARE INSERT / recreate one index")
    conn.execute("BEGIN")
    conn.execute("DROP INDEX idx_identifiers_wikidata")
    conn.execute("DROP INDEX idx_identifiers_property")
    conn.execute("DROP INDEX idx_identifiers_name")
    t0 = time.time()
    conn.execute(BARE_INSERT)
    insert_elapsed = time.time() - t0
    log(f"[E] INSERT  {fmt(insert_elapsed)}  ({SAMPLE_SIZE/insert_elapsed:,.0f} rows/s)")
    t0 = time.time()
    conn.execute("CREATE INDEX idx_identifiers_wikidata ON identifiers(wikidata_id)")
    one_idx = time.time() - t0
    log(f"[E] CREATE INDEX(wikidata_id) on 30M rows: {fmt(one_idx)}")
    conn.execute("ROLLBACK")
    return insert_elapsed, one_idx


def bench_D(conn: sqlite3.Connection) -> tuple[float, float]:
    log("[D] BARE INSERT then UPDATE-for-names")
    conn.execute("BEGIN")
    t0 = time.time()
    conn.execute(BARE_INSERT)
    insert_elapsed = time.time() - t0
    log(f"[D] INSERT  {fmt(insert_elapsed)}  ({SAMPLE_SIZE/insert_elapsed:,.0f} rows/s)")

    t0 = time.time()
    conn.execute(UPDATE_NAMES)
    update_elapsed = time.time() - t0
    log(f"[D] UPDATE  {fmt(update_elapsed)}  "
        f"({SAMPLE_SIZE/update_elapsed:,.0f} rows/s)")
    conn.execute("ROLLBACK")
    return insert_elapsed, update_elapsed


def main() -> None:
    log(f"\n=== bench {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    log(f"sample={SAMPLE_SIZE:,}  full_target={FULL_TARGET:,}")

    conn = open_db()
    n_stage = conn.execute("SELECT COUNT(*) FROM _stage_identifiers").fetchone()[0]
    n_idents = conn.execute("SELECT COUNT(*) FROM identifiers").fetchone()[0]
    log(f"_stage_identifiers : {n_stage:,}")
    log(f"identifiers        : {n_idents:,}")

    build_scratch_input(conn)

    eA = bench_A(conn)
    eB_ins, eB_one_idx = bench_B(conn)
    eC = bench_C(conn)
    eD_ins, eD_upd = bench_D(conn)
    eE_ins, eE_one_idx = bench_E(conn)

    scale = FULL_TARGET / SAMPLE_SIZE
    final_size = n_idents + FULL_TARGET
    idx_scale = final_size / max(n_idents, 1)

    pA = eA * scale
    pB = eB_ins * scale + 3 * eB_one_idx * idx_scale
    pC = eC * scale
    pD = eD_ins * scale + eD_upd * scale
    pE = eE_ins * scale + 3 * eE_one_idx * idx_scale

    log("\n--- projection for full 29M-row run ---")
    log(f"A  JOIN INSERT (with indexes)              : {fmt(pA)}")
    log(f"B  drop-indexes / JOIN INSERT / recreate   : {fmt(pB)}")
    log(f"C  BARE INSERT (names NULL)                : {fmt(pC)}")
    log(f"D  BARE INSERT + UPDATE-for-names          : {fmt(pD)}")
    log(f"E  drop-indexes / BARE INSERT / recreate   : {fmt(pE)}")

    fastest = min((pA, "A"), (pB, "B"), (pC, "C"), (pD, "D"), (pE, "E"))
    log(f"\n>>> fastest: {fastest[1]} at {fmt(fastest[0])} "
        f"(speedup vs A: {pA/fastest[0]:.1f}×)")

    # cleanup
    conn.execute("DROP TABLE IF EXISTS _bench_stage")
    conn.execute("DROP TABLE IF EXISTS _bench_new_pids")
    conn.close()


if __name__ == "__main__":
    main()
