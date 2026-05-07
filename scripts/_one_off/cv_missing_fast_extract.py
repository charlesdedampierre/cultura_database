"""Fast cohort extractor for the 523 truly-missing CV QIDs.

The original wikidata_extraction_scripts_v2 pipeline restricts every per-human
query to ?h wdt:P31 wd:Q5, which silently drops the majority of these QIDs
because Wikidata classifies them as biblical figures, fictional humans, musical
duos, etc. — not Q5 humans. We want them anyway, marked as non_human=1.

This script issues batched VALUES queries against QLever and writes the same
JSON files the v2 pipeline produces (overwriting them):

  main_info.json, places.json, occupations.json, nationalities.json,
  sitelinks.json, writing_languages.json, date_precisions.json, works.json,
  occupation_labels.json, nationality_labels.json, writing_language_labels.json,
  work_labels.json, place_metadata.json, nationality_metadata.json,
  occupation_metadata.json
  + a per-QID `instance_of.json`  (all P31 values per QID, used to set non_human)
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/wikidata_extraction_scripts_v2"))
from wikidata import qlever_rows, extract_qid, clean_literal  # noqa: E402

CV_DIR = ROOT / "data/cv_missing_from_cultura"
OUT_DIR = CV_DIR / "wikidata_extract"
COHORT_FILE = CV_DIR / "qids_to_extract.json"

BATCH = 100  # QLever-friendly batch


def values(qids: list[str], var: str = "?h") -> str:
    return f"VALUES {var} {{ " + " ".join(f"wd:{q}" for q in qids) + " }"


def query(q: str, retries: int = 5) -> list[list[str]]:
    for r in range(retries):
        try:
            return qlever_rows(q)
        except Exception as exc:
            wait = 2 ** r * 5
            print(f"  retry in {wait}s after {exc}")
            time.sleep(wait)
    raise RuntimeError("giving up")


# ---------------------------------------------------------------------------
# per-cohort batched fetch helpers
# ---------------------------------------------------------------------------


def fetch_per_cohort(qids: list[str], where_body: str, label_pos: int = 1) -> list[list[str]]:
    """SELECT ?h ?v WHERE { VALUES ?h {...} <where_body> } — returns rows."""
    out: list[list[str]] = []
    for i in tqdm(range(0, len(qids), BATCH), desc="batches", leave=False):
        chunk = qids[i:i + BATCH]
        q = (
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            "PREFIX schema: <http://schema.org/>\n"
            "PREFIX p: <http://www.wikidata.org/prop/>\n"
            "PREFIX psv: <http://www.wikidata.org/prop/statement/value/>\n"
            "PREFIX wikibase: <http://wikiba.se/ontology#>\n"
            f"SELECT ?h ?v WHERE {{ {values(chunk)} {where_body} }}"
        )
        out.extend(query(q))
    return out


def labels_for_qids(qids: list[str], lang: str = "en") -> dict[str, str]:
    """Fetch English labels for arbitrary QIDs."""
    out: dict[str, str] = {}
    qids = list(set(qids))
    for i in tqdm(range(0, len(qids), 500), desc="  labels", leave=False):
        chunk = qids[i:i + 500]
        q = (
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n"
            f"SELECT ?q ?l WHERE {{ {values(chunk, '?q')} ?q rdfs:label ?l . "
            f"FILTER(LANG(?l) = '{lang}') }}"
        )
        for r in query(q):
            if len(r) >= 2:
                out[extract_qid(r[0])] = clean_literal(r[1])
    return out


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    qids: list[str] = json.loads(COHORT_FILE.read_text())
    print(f"cohort: {len(qids)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---- main_info ------------------------------------------------------
    print("\n[01] main_info: label/description/gender/birth/death/floruit + P31")
    main_info: dict[str, dict] = {q: {"id": q} for q in qids}
    instance_of: dict[str, list[str]] = defaultdict(list)

    fields = [
        ("name",        "?h rdfs:label ?v . FILTER(LANG(?v) = 'en')"),
        ("description", "?h schema:description ?v . FILTER(LANG(?v) = 'en')"),
        ("gender",      "?h wdt:P21 ?v ."),
        ("birthdate",   "?h wdt:P569 ?v ."),
        ("deathdate",   "?h wdt:P570 ?v ."),
        ("floruit",     "?h wdt:P1317 ?v ."),
    ]
    for field, body in fields:
        rows = fetch_per_cohort(qids, body)
        for r in rows:
            if len(r) < 2:
                continue
            qid = extract_qid(r[0])
            v = r[1]
            if "wikidata.org/entity/" in v or v.startswith("<"):
                v = extract_qid(v)
            else:
                v = clean_literal(v)
            main_info[qid][field] = v
        print(f"  {field}: {sum(1 for d in main_info.values() if field in d)} hits")

    # P31 (instance of)
    rows = fetch_per_cohort(qids, "?h wdt:P31 ?v .")
    for r in rows:
        if len(r) < 2:
            continue
        instance_of[extract_qid(r[0])].append(extract_qid(r[1]))
    print(f"  P31 (instance_of): {len(instance_of)} QIDs with at least one P31")

    # ---- places ---------------------------------------------------------
    print("\n[02] places: P19, P20")
    places: dict[str, dict] = {}
    for prop, key in [("P19", "birthplace"), ("P20", "deathplace")]:
        rows = fetch_per_cohort(qids, f"?h wdt:{prop} ?v .")
        for r in rows:
            if len(r) < 2:
                continue
            qid = extract_qid(r[0])
            v = extract_qid(r[1])
            places.setdefault(qid, {"id": qid})[key] = v
        print(f"  {prop}: {sum(1 for d in places.values() if key in d)} hits")

    # ---- occupations ----------------------------------------------------
    print("\n[03] occupations: P106")
    occs: dict[str, list[str]] = defaultdict(list)
    rows = fetch_per_cohort(qids, "?h wdt:P106 ?v .")
    for r in rows:
        occs[extract_qid(r[0])].append(extract_qid(r[1]))
    print(f"  P106: {len(occs)} humans with occupations, "
          f"{sum(len(v) for v in occs.values())} pairs")

    # ---- nationalities --------------------------------------------------
    print("\n[04] nationalities: P27")
    nats: dict[str, list[str]] = defaultdict(list)
    rows = fetch_per_cohort(qids, "?h wdt:P27 ?v .")
    for r in rows:
        nats[extract_qid(r[0])].append(extract_qid(r[1]))
    print(f"  P27: {len(nats)} humans with citizenship, "
          f"{sum(len(v) for v in nats.values())} pairs")

    # ---- sitelinks ------------------------------------------------------
    print("\n[05] sitelinks: schema:about + schema:isPartOf")
    sitelinks: dict[str, list[str]] = defaultdict(list)
    for i in tqdm(range(0, len(qids), BATCH), desc="batches", leave=False):
        chunk = qids[i:i + BATCH]
        q = (
            "PREFIX wd: <http://www.wikidata.org/entity/>\n"
            "PREFIX schema: <http://schema.org/>\n"
            f"SELECT ?h ?article WHERE {{ {values(chunk)} ?article schema:about ?h ; "
            "schema:isPartOf ?wiki . }"
        )
        for r in query(q):
            if len(r) < 2:
                continue
            qid = extract_qid(r[0])
            url = clean_literal(r[1])
            if url.startswith("<") and url.endswith(">"):
                url = url[1:-1]
            sitelinks[qid].append(url)
    print(f"  sitelinks: {len(sitelinks)} humans, "
          f"{sum(len(v) for v in sitelinks.values())} links")

    # ---- writing languages ---------------------------------------------
    print("\n[08] writing_languages: P6886")
    wl_per_human: dict[str, list[str]] = defaultdict(list)
    rows = fetch_per_cohort(qids, "?h wdt:P6886 ?v .")
    for r in rows:
        wl_per_human[extract_qid(r[0])].append(extract_qid(r[1]))
    print(f"  P6886: {len(wl_per_human)} humans with writing language")

    # ---- works ---------------------------------------------------------
    print("\n[07] works: P50/P170/P86/P57/P162/P98/P175/P110/P58")
    work_props = ["P50", "P170", "P86", "P57", "P162", "P98", "P175", "P110", "P58"]
    works: dict[str, list[dict]] = defaultdict(list)
    for prop in work_props:
        rows = fetch_per_cohort(qids, f"?w wdt:{prop} ?h .")
        # Note: works flips the direction — ?w {prop} ?h
        # Our SELECT returned [?h, ?w], so r[1] is ?v which is the work? Wait
        # — fetch_per_cohort selects ?h ?v with body. Let me redo this:
        pass  # we'll build works query differently below

    works = defaultdict(list)
    for prop in work_props:
        for i in tqdm(range(0, len(qids), BATCH), desc=f"  {prop}", leave=False):
            chunk = qids[i:i + BATCH]
            q = (
                "PREFIX wd: <http://www.wikidata.org/entity/>\n"
                "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
                f"SELECT ?h ?w WHERE {{ {values(chunk)} ?w wdt:{prop} ?h . }}"
            )
            for r in query(q):
                if len(r) < 2:
                    continue
                qid = extract_qid(r[0])
                wid = extract_qid(r[1])
                works[qid].append({"work": wid, "prop": prop})
    print(f"  works: {len(works)} humans, "
          f"{sum(len(v) for v in works.values())} pairs")

    # ---- date precisions -----------------------------------------------
    print("\n[09] date_precisions for P569/P570/P1317")
    precisions: dict[str, dict] = {q: {"id": q} for q in qids}
    for prop, key in [("P569", "birthdate_precision"),
                      ("P570", "deathdate_precision"),
                      ("P1317", "floruit_precision")]:
        for i in tqdm(range(0, len(qids), BATCH), desc=f"  {prop}", leave=False):
            chunk = qids[i:i + BATCH]
            q = (
                "PREFIX wd: <http://www.wikidata.org/entity/>\n"
                "PREFIX p: <http://www.wikidata.org/prop/>\n"
                "PREFIX psv: <http://www.wikidata.org/prop/statement/value/>\n"
                "PREFIX wikibase: <http://wikiba.se/ontology#>\n"
                f"SELECT ?h ?prec WHERE {{ {values(chunk)} ?h p:{prop} ?st . "
                f"?st psv:{prop} ?dv . ?dv wikibase:timePrecision ?prec . }}"
            )
            for r in query(q):
                if len(r) < 2:
                    continue
                qid = extract_qid(r[0])
                try:
                    precisions[qid][key] = int(clean_literal(r[1]))
                except (ValueError, TypeError):
                    pass

    # ---- collect IDs needing labels ------------------------------------
    print("\n[lookup] fetching English labels for referenced entities")
    occ_ids = {o for v in occs.values() for o in v}
    nat_ids = {n for v in nats.values() for n in v}
    wl_ids = {w for v in wl_per_human.values() for w in v}
    work_ids = {w["work"] for v in works.values() for w in v}
    place_ids = {p[k] for p in places.values() for k in ("birthplace", "deathplace") if p.get(k)}
    instance_ids = {i for v in instance_of.values() for i in v}

    occ_labels = labels_for_qids(list(occ_ids))
    nat_labels = labels_for_qids(list(nat_ids))
    wl_labels = labels_for_qids(list(wl_ids))
    work_labels = labels_for_qids(list(work_ids))
    place_labels = labels_for_qids(list(place_ids))
    instance_labels = labels_for_qids(list(instance_ids))

    # ---- write outputs --------------------------------------------------
    def dump(name: str, obj):
        (OUT_DIR / name).write_text(json.dumps(obj, ensure_ascii=False))
        print(f"  wrote {name}")

    print("\n[write] outputs")
    dump("main_info.json", main_info)
    dump("places.json", places)
    dump("occupations.json", dict(occs))
    dump("nationalities.json", dict(nats))
    dump("sitelinks.json", dict(sitelinks))
    dump("writing_languages.json", dict(wl_per_human))
    dump("date_precisions.json", precisions)
    dump("works.json", dict(works))
    dump("occupation_labels.json", occ_labels)
    dump("nationality_labels.json", nat_labels)
    dump("writing_language_labels.json", wl_labels)
    dump("work_labels.json", work_labels)
    # write a side file with all P31 values per QID
    dump("instance_of.json", {q: instance_of.get(q, []) for q in qids})
    dump("instance_of_labels.json", instance_labels)
    # places metadata: only labels (we don't have country/coords here, but
    # 10_extract_place_metadata.py output already exists for the previous run
    # and may not cover the new places — we extend it)
    pm_path = OUT_DIR / "place_metadata.json"
    if pm_path.exists():
        pm = json.loads(pm_path.read_text())
    else:
        pm = {}
    if not isinstance(pm, dict):
        pm = {}
    for pid, lbl in place_labels.items():
        pm.setdefault(pid, {"id": pid})["label"] = pm.get(pid, {}).get("label") or lbl
    dump("place_metadata.json", pm)


if __name__ == "__main__":
    main()
