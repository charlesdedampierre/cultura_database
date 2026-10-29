"""Download one biography from each scholarly dictionary, for a Cultura individual it covers.

For each dictionary of DICTIONARIES, reads the identifiers from the individual_identifier table of
the Cultura database, or, for a property missing there, from the Wikidata SPARQL endpoint the
Wikidata items carrying it (or the Wikisource article describing them); keeps the Cultura individuals with an English label, a birth year and a
death year in the enriched database (for the Deutsche Biographie, only those with an NDB or ADB
article), and downloads the biography of a random one; when the page
cannot be read, the next candidate is tried. The text is extracted from the page with trafilatura.
Saved to scripts/5-annotations/dictionary_exploration/dictionary_texts.json.

Usage: .venv/bin/python scripts/5-annotations/building_scripts/dictionary_texts.py [--only dbe,hls] [--born-before 1500]
"""

import argparse
import csv
import io
import json
import random
import time
from pathlib import Path
from urllib.parse import unquote

import duckdb
import requests
import trafilatura
from bs4 import BeautifulSoup
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
ENRICHED_DB = ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"
OUT = ROOT / "scripts" / "5-annotations" / "dictionary_exploration" / "dictionary_texts.json"
RAW = OUT.parent / "raw"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "cultura-database research (cdedampierre@bunka.ai)"}
PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/> PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/> PREFIX schema: <http://schema.org/>"""
SEED = 42
TRIES = 3
MIN_TEXT = 400

DICTIONARIES = {
    "deutsche_biographie": {"name": "Deutsche Biographie (NDB/ADB)", "pid": "P7902", "sparql": "SELECT DISTINCT ?h ?id WHERE { VALUES ?source { wd:Q222784 wd:Q590208 } ?h wdt:P1343 ?source ; wdt:P7902 ?id }", "url": "https://www.deutsche-biographie.de/{}.html", "tries": 40, "home": "https://www.deutsche-biographie.de"},
    "dbe": {"name": "Diccionario Biográfico Español", "pid": "P4459", "url": "https://dbe.rah.es/biografias/{}", "home": "https://dbe.rah.es"},
    "hls": {"name": "Historisches Lexikon der Schweiz", "pid": "P902", "url": "https://hls-dhs-dss.ch/de/articles/{}", "home": "https://hls-dhs-dss.ch"},
    "oebl": {"name": "Österreichisches Biographisches Lexikon", "pid": "P6194", "url": "https://www.biographien.ac.at/oebl/oebl_{}.xml", "reject": ("s. unter", "miterwähnt"), "home": "https://www.biographien.ac.at"},
    "dib": {"name": "Dictionary of Irish Biography", "pid": "P6829", "url": "https://doi.org/10.3318/dib.{}.v1", "home": "https://www.dib.ie"},
    "dwb": {"name": "Dictionary of Welsh Biography", "pid": "P1648", "url": "https://biography.wales/article/{}", "home": "https://biography.wales"},
    "sbl": {"name": "Svenskt biografiskt lexikon", "pid": "P3217", "url": "https://sok.riksarkivet.se/sbl/Presentation.aspx?id={}", "home": "https://sok.riksarkivet.se/sbl"},
    "nbl": {"name": "Norsk biografisk leksikon", "pid": "P5080", "url": "https://nbl.snl.no/{}", "selector": ".article-text", "home": "https://nbl.snl.no"},
    "dbl": {"name": "Dansk Biografisk Leksikon", "pid": "P8341", "url": "https://biografiskleksikon.lex.dk/{}", "home": "https://biografiskleksikon.lex.dk"},
    "iranica": {"name": "Encyclopaedia Iranica", "pid": "P3021", "url": "https://www.iranicaonline.org/articles/{}", "home": "https://www.iranicaonline.org"},
    "encykorea": {"name": "Encyclopedia of Korean Culture", "pid": "P9475", "url": "https://encykorea.aks.ac.kr/Article/{}", "home": "https://encykorea.aks.ac.kr"},
    "dhbb": {"name": "Dicionário Histórico-Biográfico Brasileiro", "pid": "P9451", "url": "https://www.fgv.br/cpdoc/acervo/dicionarios/verbete-biografico/{}", "home": "https://www.fgv.br/cpdoc"},
    "dcb": {"name": "Dictionary of Canadian Biography", "pid": "P2753", "url": "https://www.biographi.ca/en/bio/{}E.html", "home": "https://www.biographi.ca"},
    "adb": {"name": "Australian Dictionary of Biography", "pid": "P1907", "url": "https://adb.anu.edu.au/biography/{}", "home": "https://adb.anu.edu.au"},
    "dnzb": {"name": "Dictionary of New Zealand Biography", "pid": "P2745", "url": "https://teara.govt.nz/en/biographies/{}", "home": "https://teara.govt.nz"},
    "sep": {"name": "Stanford Encyclopedia of Philosophy", "pid": "P3123", "url": "https://plato.stanford.edu/entries/{}/", "home": "https://plato.stanford.edu"},
    "mactutor": {"name": "MacTutor History of Mathematics", "pid": "P1563", "url": "https://mathshistory.st-andrews.ac.uk/Biographies/{}/", "home": "https://mathshistory.st-andrews.ac.uk"},
    "catholic_encyclopedia": {"name": "Catholic Encyclopedia (1913)", "pid": "P3241", "url": "https://www.newadvent.org/cathen/{}.htm", "home": "https://www.newadvent.org/cathen"},
    "pauly_wissowa": {"name": "Paulys Realencyclopädie (Pauly-Wissowa)", "source": "Q1138524", "wikisource": "de", "tries": 15, "home": "https://de.wikisource.org/wiki/Paulys_Realencyclopädie_der_classischen_Altertumswissenschaft"},
    "smith_dgrbm": {"name": "Smith's Dictionary of Greek and Roman Biography and Mythology", "source": "Q1210336", "wikisource": "en", "home": "https://en.wikisource.org/wiki/Dictionary_of_Greek_and_Roman_Biography_and_Mythology"},
    "britannica_1911": {"name": "Encyclopaedia Britannica, 11th edition (1911)", "source": "Q867541", "wikisource": "en", "home": "https://en.wikisource.org/wiki/1911_Encyclopædia_Britannica"},
}


def query(sparql):
    for attempt in range(5):
        response = requests.post(WIKIDATA_SPARQL, data={"query": PREFIXES + sparql}, headers={**HEADERS, "Accept": "text/tab-separated-values"}, timeout=600)
        if response.status_code != 429:
            break
        time.sleep(int(response.headers.get("Retry-After", 60)))
    response.raise_for_status()
    rows = list(csv.reader(io.StringIO(response.text), delimiter="\t"))[1:]
    return [(row[0].rsplit("/", 1)[-1].rstrip(">"), row[1].strip('"<>')) for row in rows]


def identifiers(connection, dictionary):
    if "sparql" in dictionary:
        return query(dictionary["sparql"])
    if "pid" in dictionary:
        rows = connection.execute("SELECT qid, value FROM individual_identifier WHERE pid = ?", [dictionary["pid"]]).fetchall()
        if rows:
            return rows
        return query(f"SELECT ?h ?id WHERE {{ ?h wdt:{dictionary['pid']} ?id }}")
    site, source = dictionary["wikisource"], dictionary["source"]
    return query(f"""SELECT DISTINCT ?h ?id WHERE {{
        {{ ?h p:P1343 ?statement . ?statement ps:P1343 wd:{source} ; pq:P805 ?article }}
        UNION {{ ?article wdt:P1433 wd:{source} ; wdt:P921 ?h }}
        ?id schema:about ?article ; schema:isPartOf <https://{site}.wikisource.org/> }}""")


def candidates(connection, ids, born_before=None):
    connection.execute("CREATE OR REPLACE TEMP TABLE dictionary (qid VARCHAR, id VARCHAR)")
    connection.executemany("INSERT INTO dictionary VALUES (?, ?)", ids)
    rows = connection.execute("""
        SELECT dictionary.qid, min(dictionary.id), individual_enriched.entity.label_en, individual_enriched.birth_date.year
        FROM dictionary
        JOIN enriched.individual_enriched ON individual_enriched.entity.qid = dictionary.qid
        WHERE individual_enriched.birth_date.year IS NOT NULL AND individual_enriched.death_date.year IS NOT NULL
          AND individual_enriched.entity.label_en IS NOT NULL
        GROUP BY ALL ORDER BY dictionary.qid
    """).fetchall()
    rows = random.Random(SEED).sample(rows, len(rows))
    early = [row for row in rows if born_before and row[3] < born_before]
    return [row[:3] for row in early or rows]


def wikisource_text(url):
    site, title = url.split("/wiki/", 1)
    response = requests.get(f"{site}/w/api.php", params={"action": "parse", "page": unquote(title), "prop": "text", "format": "json", "formatversion": 2}, headers=HEADERS, timeout=60)
    response.raise_for_status()
    html = response.json()["parse"]["text"]
    return html, trafilatura.extract(html) or ""


def page_text(url, selector=None):
    response = requests.get(url, headers=HEADERS, timeout=60)
    response.raise_for_status()
    html = response.content.decode(response.apparent_encoding or "utf-8", errors="replace")
    if selector:
        blocks = BeautifulSoup(html, "html.parser").select(selector)
        return response.url, html, "\n".join(block.get_text(" ", strip=True) for block in blocks)
    return response.url, html, trafilatura.extract(html, include_comments=False, favor_recall=True) or ""


def download(key, dictionary, connection, born_before=None):
    ids = identifiers(connection, dictionary)
    found = candidates(connection, ids, born_before)
    result = {"dictionary": key, "name": dictionary["name"], "home": dictionary["home"], "wikidata_items": len(ids), "cultura_candidates": len(found), "attempts": []}
    for qid, identifier, label in found[:dictionary.get("tries", TRIES)]:
        url = identifier if "wikisource" in dictionary else dictionary["url"].format(identifier)
        try:
            final_url, html, text = (url, *wikisource_text(url)) if "wikisource" in dictionary else page_text(url, dictionary.get("selector"))
        except (requests.RequestException, KeyError, ValueError) as error:
            result["attempts"].append({"qid": qid, "url": url, "error": str(error)[:200]})
            continue
        result["attempts"].append({"qid": qid, "url": final_url, "characters": len(text)})
        if len(text) >= MIN_TEXT and not any(mark in text for mark in dictionary.get("reject", ())):
            raw = RAW / f"{key}_{qid}.html"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(html, encoding="utf-8")
            return {**result, "qid": qid, "label": label, "id": identifier, "url": final_url, "raw_path": str(raw.relative_to(ROOT)), "text": text}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="")
    parser.add_argument("--born-before", type=int, help="draw the example among individuals born before this year, when the dictionary has any")
    args = parser.parse_args()
    keys = [key for key in DICTIONARIES if not args.only or key in args.only.split(",")]

    saved = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    connection = duckdb.connect(str(DB), read_only=True)
    connection.execute(f"ATTACH '{ENRICHED_DB}' AS enriched (READ_ONLY)")
    for key in tqdm(keys, desc="dictionaries"):
        try:
            saved[key] = download(key, DICTIONARIES[key], connection, args.born_before)
        except requests.RequestException as error:
            saved[key] = {"dictionary": key, "name": DICTIONARIES[key]["name"], "error": str(error)[:200]}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(saved, ensure_ascii=False, indent=1), encoding="utf-8")

    for key in keys:
        row = saved[key]
        status = f"{row['label']} ({row['qid']}), {len(row['text'])} characters" if "text" in row else f"FAILED {row.get('error') or row.get('attempts')}"
        print(f"  {key:22} items {row.get('wikidata_items', 0):7} | in Cultura {row.get('cultura_candidates', 0):6} | {status}")


if __name__ == "__main__":
    main()
