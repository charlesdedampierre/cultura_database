"""
Add the cross-verified-database (Laouenan et al., 2022) occupation ontology
columns to humans_clean.occupations.

The cross-verified DB stores, per individual (Wikidata Q-id):
    level1_main_occ   coarse domain   (Culture / Discovery-Science / ...)
    level2_main_occ   sub-domain      (Culture-core / Politics / Academia / ...)
    level3_main_occ   fine label      (playwright / footballer / painter / ...)

humans_clean.occupations is keyed on Wikidata occupation Q-ids
(e.g. Q1622272 = "university teacher"). There is no direct Q-id-to-ontology
mapping shipped with the cross-verified DB — its level3 labels are stemmed
text tokens, not Wikidata IDs.

We bridge the two by majority vote across shared individuals:
  for every Wikidata occupation Q-id appearing in individuals_keys.occupations_ids,
  count how many cross-verified individuals carrying that Q-id have which
  (level1, level2, level3) tuple, then assign the modal tuple to that Q-id.

Adds three TEXT columns to occupations: level1_main_occ, level2_main_occ,
level3_main_occ. Idempotent: re-running updates the values.
"""

from __future__ import annotations

import csv
import gzip
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "humans_clean.sqlite3"
CSV_GZ = (
    ROOT
    / "data"
    / "similar_databases"
    / "cross-verified-database"
    / "cross-verified-database.utf8.csv.gz"
)


def load_cross_verified_per_individual() -> dict[str, tuple[str, str, str]]:
    """wikidata_code -> (level1, level2, level3). Empty strings normalised to ''."""
    out: dict[str, tuple[str, str, str]] = {}
    with gzip.open(CSV_GZ, "rt", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader)
        i_qid = header.index("wikidata_code")
        i_l1 = header.index("level1_main_occ")
        i_l2 = header.index("level2_main_occ")
        i_l3 = header.index("level3_main_occ")
        for row in tqdm(reader, total=2_291_817, desc="cross-verified rows"):
            qid = row[i_qid].strip()
            if not qid:
                continue
            out[qid] = (row[i_l1].strip(), row[i_l2].strip(), row[i_l3].strip())
    return out


def vote_per_occupation(
    con: sqlite3.Connection,
    cv: dict[str, tuple[str, str, str]],
) -> dict[str, dict[str, str]]:
    """For each Wikidata occupation Q-id, return modal level1/level2/level3."""
    cur = con.execute(
        "SELECT wikidata_id, occupations_ids FROM individuals_keys "
        "WHERE occupations_ids IS NOT NULL AND occupations_ids <> ''"
    )
    # Three independent counters per occupation Q-id (one per level).
    # Voting per level (rather than per (l1,l2,l3) tuple) is more robust
    # because the same wikidata occupation can map to several level3 stems.
    c1: dict[str, Counter] = defaultdict(Counter)
    c2: dict[str, Counter] = defaultdict(Counter)
    c3: dict[str, Counter] = defaultdict(Counter)

    for wikidata_id, occ_ids in tqdm(cur, desc="voting", unit=" indiv"):
        labels = cv.get(wikidata_id)
        if labels is None:
            continue
        l1, l2, l3 = labels
        for occ in occ_ids.split(";"):
            occ = occ.strip()
            if not occ:
                continue
            if l1:
                c1[occ][l1] += 1
            if l2:
                c2[occ][l2] += 1
            if l3:
                c3[occ][l3] += 1

    result: dict[str, dict[str, str]] = {}
    all_occ = set(c1) | set(c2) | set(c3)
    for occ in all_occ:
        result[occ] = {
            "level1_main_occ": c1[occ].most_common(1)[0][0] if c1[occ] else None,
            "level2_main_occ": c2[occ].most_common(1)[0][0] if c2[occ] else None,
            "level3_main_occ": c3[occ].most_common(1)[0][0] if c3[occ] else None,
            "n_votes": sum(c1[occ].values()),
        }
    return result


def ensure_columns(con: sqlite3.Connection) -> None:
    cols = {row[1] for row in con.execute("PRAGMA table_info(occupations)")}
    for c in ("level1_main_occ", "level2_main_occ", "level3_main_occ", "ontology_n_votes"):
        if c not in cols:
            ctype = "INTEGER" if c == "ontology_n_votes" else "TEXT"
            con.execute(f"ALTER TABLE occupations ADD COLUMN {c} {ctype}")


def write(con: sqlite3.Connection, votes: dict[str, dict[str, str]]) -> None:
    rows = [
        (v["level1_main_occ"], v["level2_main_occ"], v["level3_main_occ"], v["n_votes"], occ)
        for occ, v in votes.items()
    ]
    con.executemany(
        "UPDATE occupations SET level1_main_occ=?, level2_main_occ=?, "
        "level3_main_occ=?, ontology_n_votes=? WHERE id=?",
        tqdm(rows, desc="updating occupations", unit=" rows"),
    )


def main() -> None:
    print("[1/4] Loading cross-verified ontology per individual...")
    cv = load_cross_verified_per_individual()
    print(f"      {len(cv):,} individuals with ontology labels")

    print("[2/4] Voting modal labels per Wikidata occupation Q-id...")
    with sqlite3.connect(DB) as con:
        con.text_factory = lambda b: b.decode("utf-8", errors="replace")
        votes = vote_per_occupation(con, cv)
        print(f"      {len(votes):,} occupations received votes")

        print("[3/4] Ensuring columns exist on occupations table...")
        ensure_columns(con)

        print("[4/4] Writing results...")
        write(con, votes)
        con.commit()

        # Quick coverage report.
        total = con.execute("SELECT COUNT(*) FROM occupations").fetchone()[0]
        with_l1 = con.execute(
            "SELECT COUNT(*) FROM occupations WHERE level1_main_occ IS NOT NULL"
        ).fetchone()[0]
        print(f"\nCoverage: {with_l1:,} / {total:,} occupations now carry level1_main_occ "
              f"({with_l1/total:.1%})")

        sample = con.execute(
            "SELECT id, name_en, level1_main_occ, level2_main_occ, level3_main_occ, "
            "ontology_n_votes FROM occupations "
            "WHERE level1_main_occ IS NOT NULL "
            "ORDER BY ontology_n_votes DESC LIMIT 15"
        ).fetchall()
        print("\nTop 15 occupations by vote count:")
        print(f"{'id':<12} {'name':<30} {'L1':<22} {'L2':<28} {'L3':<22} votes")
        for r in sample:
            print(f"{r[0]:<12} {(r[1] or '')[:28]:<30} {(r[2] or '')[:20]:<22} "
                  f"{(r[3] or '')[:26]:<28} {(r[4] or '')[:20]:<22} {r[5]}")


if __name__ == "__main__":
    main()
