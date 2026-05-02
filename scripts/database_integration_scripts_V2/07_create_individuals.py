"""07 — Create the `individuals` table from v2 per-human extracts.

Joins the per-human JSONs into one row per Q5:

    main_info.json       -> name_en, description_en, gender, birthdate, deathdate,
                            floruit_date (P1317)
    places.json          -> birthcity_id, deathcity_id
    date_precisions.json -> birthdate_precision, deathdate_precision,
                            floruit_precision
    occupations.json     -> occupations_en (";"-joined name_en lookup)
    nationalities.json   -> country_of_citizenship_en (";"-joined name_en lookup
                            from the `country_of_citizenship` reference table)
    sitelinks.json       -> wikimedia_links_count
    catalogs.json        -> identifiers_count
    works.json           -> number_of_works
    writing_languages.json + writing_language_labels.json -> writing_language_name_en

Floruit (P1317) is stored on this table directly since 2026-05; the
former standalone `individuals_floruit` table was removed.

Reference tables (places, occupations, country_of_citizenship,
writing_languages, identifier_types) must exist already — `build_all.py`
runs them first.

Usage
-----
    python3 07_create_individuals.py
    python3 07_create_individuals.py --full
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import (
    WIKIDATA_V2_DIR,
    log,
    load_json,
    open_db,
    parse_run_mode,
)


P = WIKIDATA_V2_DIR


def _label_lookup(conn: sqlite3.Connection, table: str, key: str, val: str) -> dict[str, str]:
    return {row[0]: row[1] for row in conn.execute(f"SELECT {key}, {val} FROM {table}")}


def run(
    conn: sqlite3.Connection,
    main_info_path: Path = P / "main_info.json",
    places_path: Path = P / "places.json",
    precisions_path: Path = P / "date_precisions.json",
    occupations_path: Path = P / "occupations.json",
    nationalities_path: Path = P / "nationalities.json",
    sitelinks_path: Path = P / "sitelinks.json",
    catalogs_path: Path = P / "catalogs.json",
    works_path: Path = P / "works.json",
    writing_languages_path: Path = P / "writing_languages.json",
    writing_language_labels_path: Path = P / "writing_language_labels.json",
) -> int:
    log("[DB] 07: Creating individuals table...")

    main_info = load_json(main_info_path) if main_info_path.exists() else {}
    places = load_json(places_path) if places_path.exists() else {}
    precisions = load_json(precisions_path) if precisions_path.exists() else {}
    occs = load_json(occupations_path) if occupations_path.exists() else {}
    nats = load_json(nationalities_path) if nationalities_path.exists() else {}
    sitelinks = load_json(sitelinks_path) if sitelinks_path.exists() else {}
    catalogs = load_json(catalogs_path) if catalogs_path.exists() else {}
    works = load_json(works_path) if works_path.exists() else {}
    wl_per_human = load_json(writing_languages_path) if writing_languages_path.exists() else {}
    wl_labels = load_json(writing_language_labels_path) if writing_language_labels_path.exists() else {}

    occ_label = _label_lookup(conn, "occupations", "id", "name_en") if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='occupations'"
    ).fetchone() else {}
    coc_label = _label_lookup(
        conn, "country_of_citizenship", "wikidata_id", "name_en"
    ) if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='country_of_citizenship'"
    ).fetchone() else {}
    place_label = _label_lookup(conn, "places", "id", "name_en") if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='places'"
    ).fetchone() else {}

    conn.execute("DROP TABLE IF EXISTS individuals")
    conn.execute(
        """
        CREATE TABLE individuals (
            wikidata_id TEXT PRIMARY KEY,
            name_en TEXT,
            description_en TEXT,
            birthdate TEXT,
            birthdate_precision INTEGER,
            deathdate TEXT,
            deathdate_precision INTEGER,
            floruit_date TEXT,
            floruit_precision INTEGER,
            floruit_year INTEGER,
            gender TEXT,
            birthcity_id TEXT,
            birthcity_en TEXT,
            deathcity_id TEXT,
            deathcity_en TEXT,
            country_of_citizenship_en TEXT,
            country_of_citizenship_ids TEXT,
            occupations_en TEXT,
            writing_language_name_en TEXT,
            wikimedia_links_count INTEGER DEFAULT 0,
            identifiers_count INTEGER DEFAULT 0,
            number_of_works INTEGER DEFAULT 0
        )
        """
    )

    qids = (set(main_info) | set(places) | set(precisions) | set(occs) |
            set(nats) | set(sitelinks) | set(catalogs) | set(works) |
            set(wl_per_human))

    def _parse_year(s):
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

    rows = []
    for qid in qids:
        m = main_info.get(qid, {})
        pl = places.get(qid, {})
        pr = precisions.get(qid, {})

        occ_qids = occs.get(qid, []) or []
        occ_names = [occ_label.get(o) for o in occ_qids if occ_label.get(o)]

        coc_qids = nats.get(qid, []) or []
        coc_names = [coc_label.get(n) for n in coc_qids if coc_label.get(n)]

        wl_qids = wl_per_human.get(qid, []) or []
        wl_names = [wl_labels.get(w) for w in wl_qids if wl_labels.get(w)]

        floruit_date = m.get("floruit_date") or m.get("floruit")
        floruit_precision = pr.get("floruit_precision")
        floruit_year = _parse_year(floruit_date)

        rows.append((
            qid,
            m.get("name"),
            m.get("description"),
            m.get("birthdate"),
            pr.get("birthdate_precision"),
            m.get("deathdate"),
            pr.get("deathdate_precision"),
            floruit_date,
            floruit_precision,
            floruit_year,
            m.get("gender"),
            pl.get("birthplace"),
            place_label.get(pl.get("birthplace")) if pl.get("birthplace") else None,
            pl.get("deathplace"),
            place_label.get(pl.get("deathplace")) if pl.get("deathplace") else None,
            ";".join(coc_names) if coc_names else None,
            ";".join(coc_qids) if coc_qids else None,
            ";".join(occ_names) if occ_names else None,
            ";".join(wl_names) if wl_names else None,
            len(sitelinks.get(qid, []) or []),
            sum(len(v) for v in (catalogs.get(qid) or {}).values()),
            len(works.get(qid, []) or []),
        ))

    conn.executemany(
        "INSERT OR IGNORE INTO individuals "
        "(wikidata_id, name_en, description_en, birthdate, birthdate_precision, "
        " deathdate, deathdate_precision, floruit_date, floruit_precision, "
        " floruit_year, gender, birthcity_id, birthcity_en, deathcity_id, "
        " deathcity_en, country_of_citizenship_en, country_of_citizenship_ids, "
        " occupations_en, writing_language_name_en, wikimedia_links_count, "
        " identifiers_count, number_of_works) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indiv_name ON individuals(name_en)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_indiv_works ON individuals(number_of_works)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_individuals_floruit_year "
        "ON individuals(floruit_year)"
    )
    conn.commit()

    log(f"[DB] 07: Inserted {len(rows)} individuals.")
    return len(rows)


def _sample_main() -> None:
    import json as _json
    with tempfile.TemporaryDirectory() as tmp:
        # minimal fake universe for end-to-end shape check
        files = {
            "main_info.json": {"Q937": {"id": "Q937", "name": "Albert Einstein",
                                         "description": "physicist", "gender": "Q6581097",
                                         "birthdate": "1879-03-14T00:00:00Z",
                                         "deathdate": "1955-04-18T00:00:00Z",
                                         "floruit_date": "1915-01-01T00:00:00Z"}},
            "places.json": {"Q937": {"id": "Q937", "birthplace": "Q3012", "deathplace": "Q138518"}},
            "date_precisions.json": {"Q937": {"birthdate_precision": 11,
                                              "deathdate_precision": 11,
                                              "floruit_precision": 9,
                                              "id": "Q937"}},
            "occupations.json": {"Q937": ["Q169470"]},
            "nationalities.json": {"Q937": ["Q183"]},
            "sitelinks.json": {"Q937": ["https://en.wikipedia.org/wiki/Albert_Einstein"]},
            "catalogs.json": {"Q937": {"P214": ["75121530"]}},
            "works.json": {"Q937": [{"work": "Q1", "prop": "P50"}]},
            "writing_languages.json": {"Q937": ["Q188"]},
            "writing_language_labels.json": {"Q188": "German"},
        }
        # `run()` accepts `precisions_path`, not `date_precisions_path`,
        # so override the auto-derived kwarg name for that one file.
        path_kw_overrides = {"date_precisions.json": "precisions_path"}
        kw = {}
        for fname, payload in files.items():
            p = Path(tmp) / fname
            p.write_text(_json.dumps(payload))
            kwarg = path_kw_overrides.get(fname, fname.replace(".json", "_path"))
            kw[kwarg] = p

        with open_db(Path(tmp) / "sample.sqlite3") as conn:
            # seed reference tables that 07 looks up
            conn.executescript("""
                CREATE TABLE occupations (id TEXT PRIMARY KEY, name_en TEXT);
                CREATE TABLE country_of_citizenship (wikidata_id TEXT PRIMARY KEY, name_en TEXT);
                CREATE TABLE places (id TEXT PRIMARY KEY, name_en TEXT);
                INSERT INTO occupations VALUES ('Q169470','physicist');
                INSERT INTO country_of_citizenship VALUES ('Q183','German');
                INSERT INTO places VALUES ('Q3012','Ulm'),('Q138518','Princeton');
            """)
            n = run(conn, **kw)
            for row in conn.execute(
                "SELECT wikidata_id, name_en, gender, birthcity_en, deathcity_en, "
                "country_of_citizenship_en, occupations_en, writing_language_name_en, "
                "floruit_year, wikimedia_links_count, identifiers_count, "
                "number_of_works FROM individuals"
            ):
                log(f"  individuals: {row}")
        log(f"[sample] inserted {n} individuals")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db() as conn:
            run(conn)
    else:
        _sample_main()
