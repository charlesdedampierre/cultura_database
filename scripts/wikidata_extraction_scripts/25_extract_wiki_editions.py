"""Every Wikimedia site (Wikipedia editions, Wikiquote, Commons...) with its English name
and the language it is written in.

Output: data/raw_data_from_wikidata/wikidata_extraction_scripts_v2/wiki_editions.json
    {"https://fr.wikipedia.org": {"qid": "Q8447", "dbname": "frwiki", "label_en": "French Wikipedia", "language": "Q150"}}
"""
import json
from pathlib import Path

from wikidata import PREFIXES, clean_literal, extract_qid, qlever_stream

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw_data_from_wikidata" / "wikidata_extraction_scripts_v2" / "wiki_editions.json"

QUERY = PREFIXES + """SELECT ?item ?dbname ?website ?label ?language WHERE {
  ?item wdt:P1800 ?dbname ; wdt:P856 ?website .
  OPTIONAL { ?item rdfs:label ?label FILTER(LANG(?label) = "en") }
  OPTIONAL { ?item wdt:P407 ?language }
}"""


def main():
    found = {}
    for item, dbname, website, label, language in qlever_stream(QUERY):
        url = website.strip("<>").rstrip("/").replace("http://", "https://")
        if url in found:
            continue
        found[url] = {
            "qid": extract_qid(item),
            "dbname": clean_literal(dbname),
            "label_en": clean_literal(label) or None,
            "language": extract_qid(language) if language else None,
        }
    OUT.write_text(json.dumps(found, ensure_ascii=False, indent=1))
    print(f"{len(found):,} Wikimedia sites; saved {OUT}")


if __name__ == "__main__":
    main()
