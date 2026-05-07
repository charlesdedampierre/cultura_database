"""Merge CV-only Wikidata extracts into humans_clean.sqlite3.

Inputs:
  data/cv_missing_from_cultura/qids_to_extract.json   523 canonical QIDs
  data/cv_missing_from_cultura/qid_resolution.json    old → new redirect map
  data/cv_missing_from_cultura/wikidata_extract/      JSON outputs from
                                                      wikidata_extraction_scripts_v2
  data/similar_databases/cross-verified-database/...  for birth/death from CV

For every truly-missing canonical QID we:
  1. Insert into `individuals` with cross_verified_db=1, plus birthdate_from_CV
     and deathdate_from_CV pulled from the original (pre-redirect) CV row.
  2. Upsert reference rows into occupations, country_of_citizenship, places,
     writing_languages, identifier_types when we've extracted new entities
     not already known to Cultura.
  3. Insert linked records into identifiers, wikimedia_links,
     individual_writing_languages, works.

Bench-then-run: a dry-run pass logs intended row counts before any write.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/wikidata_extraction_scripts_v2"))

DB = ROOT / "data/humans_clean.sqlite3"
CV_DIR = ROOT / "data/cv_missing_from_cultura"
EXTRACT = CV_DIR / "wikidata_extract"
CV_CSV = ROOT / "data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def load_json(p: Path) -> dict:
    if not p.exists():
        return {}
    with p.open() as fh:
        return json.load(fh)


def parse_year(s) -> int | None:
    if not s:
        return None
    s = str(s).strip()
    if not s or s.startswith("_:"):
        return None
    sign = 1
    if s.startswith("-"):
        sign = -1
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]
    head = s.split("-", 1)[0].split("T", 1)[0]
    try:
        return sign * int(head)
    except ValueError:
        return None


def strip_iso(date_str: str | None) -> str | None:
    """Wikidata returns ISO timestamps like '1879-03-14T00:00:00Z'.
    Cultura's birthdate column stores them as 'YYYY-MM-DD'."""
    if not date_str:
        return date_str
    s = str(date_str).split("T", 1)[0]
    return s


def url_from_formatter(fmt: str | None, value: str | None) -> str | None:
    if not fmt or not value:
        return None
    return fmt.replace("$1", value)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Only print counts; don't write to the DB.")
    args = parser.parse_args()

    print("[load] resolution + extracts")
    canonical_qids = set(json.loads((CV_DIR / "qids_to_extract.json").read_text()))
    resolution = json.loads((CV_DIR / "qid_resolution.json").read_text())

    # canonical -> list of CV (pre-redirect) QIDs whose redirect resolves to it
    canon_to_cv: dict[str, list[str]] = {}
    for old, info in resolution.items():
        if not info["exists"]:
            continue
        new = info["redirect"] or old
        if new in canonical_qids:
            canon_to_cv.setdefault(new, []).append(old)

    main_info = load_json(EXTRACT / "main_info.json")
    places = load_json(EXTRACT / "places.json")
    precisions = load_json(EXTRACT / "date_precisions.json")
    occs = load_json(EXTRACT / "occupations.json")
    occ_labels = load_json(EXTRACT / "occupation_labels.json")
    nats = load_json(EXTRACT / "nationalities.json")
    nat_labels = load_json(EXTRACT / "nationality_labels.json")
    sitelinks = load_json(EXTRACT / "sitelinks.json")
    catalogs = load_json(EXTRACT / "catalogs.json")
    catalog_props = load_json(EXTRACT / "catalog_properties.json")
    works = load_json(EXTRACT / "works.json")
    work_labels = load_json(EXTRACT / "work_labels.json")
    wl_per_human = load_json(EXTRACT / "writing_languages.json")
    wl_labels = load_json(EXTRACT / "writing_language_labels.json")
    place_meta = load_json(EXTRACT / "place_metadata.json")
    nat_meta = load_json(EXTRACT / "nationality_metadata.json")
    occ_meta = load_json(EXTRACT / "occupation_metadata.json")
    catalog_meta = load_json(EXTRACT / "catalog_metadata.json")
    instance_of = load_json(EXTRACT / "instance_of.json")

    # formatter URL + label lookup. catalog_properties.json is a dict like
    # {"n_properties": N, "properties": [{"property_id", "label", "formatter_url"}, ...]}
    fmt_by_pid: dict[str, str] = {}
    label_by_pid: dict[str, str] = {}
    prop_list = []
    if isinstance(catalog_props, dict):
        prop_list = catalog_props.get("properties") or []
    elif isinstance(catalog_props, list):
        prop_list = catalog_props
    for row in prop_list:
        pid = row.get("property_id")
        if not pid:
            continue
        fmt_by_pid[pid] = row.get("formatter_url") or ""
        label_by_pid[pid] = row.get("label") or ""

    print(f"[load] {len(canonical_qids):,} target QIDs, "
          f"{len(main_info):,} main_info rows extracted")

    # CV birth/death by old QID
    print("[load] CV birth/death years (DuckDB)")
    dcon = duckdb.connect()
    dcon.execute(f"""
        CREATE TEMP TABLE cv AS
        SELECT wikidata_code AS qid,
               CASE WHEN TRY_CAST(birth AS INTEGER) IS NOT NULL
                    THEN CAST(TRY_CAST(birth AS INTEGER) AS VARCHAR) END AS birth,
               CASE WHEN TRY_CAST(death AS INTEGER) IS NOT NULL
                    THEN CAST(TRY_CAST(death AS INTEGER) AS VARCHAR) END AS death
        FROM read_csv_auto('{CV_CSV}', header=true, ignore_errors=true);
    """)
    cv_old_qids = sorted({q for qs in canon_to_cv.values() for q in qs})
    cv_dates: dict[str, tuple[str | None, str | None]] = {}
    if cv_old_qids:
        import polars as pl_
        targets_df = pl_.DataFrame({"qid": cv_old_qids})
        dcon.register("targets", targets_df)
        rows = dcon.execute("""
            SELECT cv.qid, cv.birth, cv.death
            FROM cv JOIN targets t ON t.qid = cv.qid;
        """).fetchall()
        for q, b, d in rows:
            cv_dates[q] = (b, d)
    dcon.close()

    print(f"[load] CV dates loaded for {len(cv_dates):,} old QIDs")

    # ----- DB connection
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("PRAGMA journal_mode = WAL;")
    cur.execute("PRAGMA synchronous = NORMAL;")
    cur.execute("PRAGMA temp_store = MEMORY;")
    cur.execute("PRAGMA cache_size = -2000000;")

    existing_individual = {r[0] for r in cur.execute(
        f"SELECT wikidata_id FROM individuals "
        f"WHERE wikidata_id IN ({','.join('?' * len(canonical_qids))})",
        list(canonical_qids),
    ).fetchall()} if canonical_qids else set()
    print(f"[check] {len(existing_individual)} of {len(canonical_qids)} canonical "
          f"QIDs already in individuals (will be updated, not re-inserted)")

    # Existing reference IDs to know what to upsert
    existing_occ = {r[0] for r in cur.execute("SELECT id FROM occupations")}
    existing_coc = {r[0] for r in cur.execute("SELECT wikidata_id FROM country_of_citizenship")}
    existing_place = {r[0] for r in cur.execute("SELECT id FROM places")}
    existing_wl = {r[0] for r in cur.execute("SELECT id FROM writing_languages")}
    existing_idtypes = {r[0] for r in cur.execute("SELECT property_id FROM identifier_types")}

    # ----- assemble individuals rows
    occ_label = {r[0]: r[1] for r in cur.execute("SELECT id, name_en FROM occupations")}
    coc_label = {r[0]: r[1] for r in cur.execute("SELECT wikidata_id, name_en FROM country_of_citizenship")}
    place_label = {r[0]: r[1] for r in cur.execute("SELECT id, name_en FROM places")}

    # extend with new labels we just extracted (so the joined names are correct)
    for q, lbl in occ_labels.items():
        occ_label.setdefault(q, lbl)
    for q, lbl in nat_labels.items():
        coc_label.setdefault(q, lbl)
    for q, meta in (place_meta.items() if isinstance(place_meta, dict) else []):
        if isinstance(meta, dict):
            place_label.setdefault(q, meta.get("label"))

    individual_rows = []
    indiv_writing_lang_rows = []
    identifier_rows = []
    wikimedia_rows = []
    work_rows = []

    new_occ_ids: set[str] = set()
    new_coc_ids: set[str] = set()
    new_place_ids: set[str] = set()
    new_wl_ids: set[str] = set()
    new_idtype_ids: set[str] = set()

    for qid in tqdm(sorted(canonical_qids), desc="assemble"):
        m = main_info.get(qid, {})
        pl = places.get(qid, {})
        pr = precisions.get(qid, {})
        occ_qids = occs.get(qid, []) or []
        coc_qids = nats.get(qid, []) or []
        wl_qids = wl_per_human.get(qid, []) or []
        sites = sitelinks.get(qid, []) or []
        cats = catalogs.get(qid, {}) or {}
        wks = works.get(qid, []) or []

        # collect needed reference IDs
        for o in occ_qids:
            if o not in existing_occ:
                new_occ_ids.add(o)
        for n in coc_qids:
            if n not in existing_coc:
                new_coc_ids.add(n)
        for place_qid in (pl.get("birthplace"), pl.get("deathplace")):
            if place_qid and place_qid not in existing_place:
                new_place_ids.add(place_qid)
        for w in wl_qids:
            if w not in existing_wl:
                new_wl_ids.add(w)
        for pid in cats.keys():
            if pid not in existing_idtypes:
                new_idtype_ids.add(pid)

        occ_names = [occ_label.get(o) for o in occ_qids if occ_label.get(o)]
        coc_names = [coc_label.get(n) for n in coc_qids if coc_label.get(n)]
        wl_names = [wl_labels.get(w) for w in wl_qids if wl_labels.get(w)]

        floruit_date = strip_iso(m.get("floruit_date") or m.get("floruit"))
        floruit_year = parse_year(floruit_date)

        types = instance_of.get(qid, []) or []
        non_human = 0 if "Q5" in types else 1

        # CV dates: pick first old QID's CV row that has values
        b_cv, d_cv = (None, None)
        for old in canon_to_cv.get(qid, []):
            ob, od = cv_dates.get(old, (None, None))
            if ob and not b_cv:
                b_cv = ob
            if od and not d_cv:
                d_cv = od
            if b_cv and d_cv:
                break

        name = m.get("name")
        individual_rows.append((
            qid,                                            # wikidata_id
            name,                                           # name_en
            m.get("description"),                           # description_en
            strip_iso(m.get("birthdate")),                  # birthdate
            pr.get("birthdate_precision"),                  # birthdate_precision
            strip_iso(m.get("deathdate")),                  # deathdate
            pr.get("deathdate_precision"),                  # deathdate_precision
            ";".join(coc_names) if coc_names else None,     # country_of_citizenship_en
            place_label.get(pl.get("birthplace")) if pl.get("birthplace") else None,
            place_label.get(pl.get("deathplace")) if pl.get("deathplace") else None,
            ";".join(occ_names) if occ_names else None,     # occupations_en
            len(sites),                                     # wikimedia_links_count
            m.get("gender"),                                # gender
            sum(len(v) for v in cats.values()),             # identifiers_count
            ";".join(wl_names) if wl_names else None,       # writing_language_name_en
            len(wks),                                       # number_of_works
            floruit_date,                                   # floruit_date
            pr.get("floruit_precision"),                    # floruit_precision
            floruit_year,                                   # floruit_year
            1,                                              # cross_verified_db
            b_cv,                                           # birthdate_from_CV
            d_cv,                                           # deathdate_from_CV
            non_human,                                      # non_human
        ))

        # writing language linkage
        for w in wl_qids:
            indiv_writing_lang_rows.append((qid, name, w, wl_labels.get(w)))

        # identifiers
        for pid, vals in cats.items():
            fmt = fmt_by_pid.get(pid, "")
            label = (catalog_meta.get(pid, {}) or {}).get("label") or label_by_pid.get(pid)
            for v in vals:
                identifier_rows.append((
                    qid, name, pid, label, v, url_from_formatter(fmt, v),
                ))

        # wikimedia links
        for url in sites:
            site_title = unquote(url.rsplit("/", 1)[-1].replace("_", " "))
            domain = url.split("//", 1)[-1].split("/", 1)[0]
            wikimedia_rows.append((qid, name, domain, site_title, url))

        # works
        for w in wks:
            if isinstance(w, dict):
                work_rows.append((qid, name, w.get("work"),
                                  work_labels.get(w.get("work")), w.get("prop")))
            else:
                work_rows.append((qid, name, w, work_labels.get(w), None))

    # ----- summary
    print("\n--- planned writes ---")
    print(f"  individuals (insert/replace) : {len(individual_rows):>6,}")
    print(f"  individual_writing_languages : {len(indiv_writing_lang_rows):>6,}")
    print(f"  identifiers                  : {len(identifier_rows):>6,}")
    print(f"  wikimedia_links              : {len(wikimedia_rows):>6,}")
    print(f"  works                        : {len(work_rows):>6,}")
    print(f"  new occupation refs          : {len(new_occ_ids):>6,}")
    print(f"  new country_of_citizenship   : {len(new_coc_ids):>6,}")
    print(f"  new place refs               : {len(new_place_ids):>6,}")
    print(f"  new writing_language refs    : {len(new_wl_ids):>6,}")
    print(f"  new identifier_type refs     : {len(new_idtype_ids):>6,}")

    if args.dry_run:
        print("\n--dry-run set, no DB writes.")
        return

    # ----- writes
    print("\n[write] reference upserts")
    cur.executemany(
        "INSERT OR IGNORE INTO occupations(id, name_en, description_en) "
        "VALUES (?, ?, ?)",
        [(o, occ_labels.get(o), (occ_meta.get(o, {}) or {}).get("description"))
         for o in new_occ_ids],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO country_of_citizenship(wikidata_id, name_en, description_en, en_wikipedia_url, lat, lon) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                n,
                nat_labels.get(n) or (nat_meta.get(n, {}) or {}).get("label"),
                (nat_meta.get(n, {}) or {}).get("description"),
                (nat_meta.get(n, {}) or {}).get("en_wikipedia_url"),
                (nat_meta.get(n, {}) or {}).get("lat"),
                (nat_meta.get(n, {}) or {}).get("lon"),
            )
            for n in new_coc_ids
        ],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO places(id, name_en, lat, lon, original_country_name_id) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                p,
                (place_meta.get(p, {}) or {}).get("label"),
                (place_meta.get(p, {}) or {}).get("lat"),
                (place_meta.get(p, {}) or {}).get("lon"),
                (place_meta.get(p, {}) or {}).get("country"),
            )
            for p in new_place_ids
        ],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO writing_languages(id, name) VALUES (?, ?)",
        [(w, wl_labels.get(w) or w) for w in new_wl_ids],
    )
    cur.executemany(
        "INSERT OR IGNORE INTO identifier_types(property_id, name_en) VALUES (?, ?)",
        [
            (
                p,
                (catalog_meta.get(p, {}) or {}).get("label") or label_by_pid.get(p),
            )
            for p in new_idtype_ids
        ],
    )

    print("[write] individuals")
    cur.executemany(
        """
        INSERT OR REPLACE INTO individuals
            (wikidata_id, name_en, description_en,
             birthdate, birthdate_precision,
             deathdate, deathdate_precision,
             country_of_citizenship_en,
             birthcity_en, deathcity_en,
             occupations_en, wikimedia_links_count,
             gender, identifiers_count, writing_language_name_en,
             number_of_works, floruit_date, floruit_precision, floruit_year,
             cross_verified_db,
             birthdate_from_CV, deathdate_from_CV,
             non_human)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        individual_rows,
    )

    print("[write] individual_writing_languages")
    cur.executemany(
        "INSERT OR REPLACE INTO individual_writing_languages "
        "(wikidata_id, individual_name, language_id, language_name) "
        "VALUES (?, ?, ?, ?)",
        indiv_writing_lang_rows,
    )

    print("[write] identifiers")
    cur.executemany(
        "INSERT OR REPLACE INTO identifiers "
        "(wikidata_id, individual_name, property_id, identifier_name, value, url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        identifier_rows,
    )

    print("[write] wikimedia_links")
    cur.executemany(
        "INSERT INTO wikimedia_links (wikidata_id, individual_name, site, title, url) "
        "VALUES (?, ?, ?, ?, ?)",
        wikimedia_rows,
    )

    print("[write] works")
    cur.executemany(
        "INSERT INTO works (individual_id, individual_name, work_id, work_name, relationship) "
        "VALUES (?, ?, ?, ?, ?)",
        work_rows,
    )

    con.commit()
    con.close()

    # ----- report
    print("\n[done] verifying...")
    con = sqlite3.connect(DB)
    cur = con.cursor()
    n = cur.execute(
        f"SELECT COUNT(*) FROM individuals WHERE wikidata_id IN "
        f"({','.join('?' * len(canonical_qids))}) AND cross_verified_db = 1",
        list(canonical_qids),
    ).fetchone()[0]
    print(f"  individuals merged with cross_verified_db=1: {n}")
    con.close()


if __name__ == "__main__":
    main()
