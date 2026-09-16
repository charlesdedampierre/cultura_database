import os
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datamodels"))

import datamodel_in_duckdb as D
import sources as S
import to_duckdb as C
import to_raw as T
from write import write_table

TARGET = S.ROOT / "data" / "cultura_v2.duckdb"
SAMPLE = int(os.environ.get("SAMPLE", "500"))
SCRATCH = Path(os.environ.get("SCRATCH", "/tmp")) / "raw_to_db"


def main():
    qids = T.sample_qids(SAMPLE)
    print(f"{len(qids)} individuals", flush=True)

    raw_individuals = T.individuals(qids)

    place_qids = sorted({q for i in raw_individuals for q in (i.place_of_birth, i.place_of_death) if q})
    country_qids = sorted({q for i in raw_individuals for q in i.country_of_citizenship})
    occupation_qids = sorted({q for i in raw_individuals for q in i.occupation})
    work_qids = sorted({c.work for i in raw_individuals for c in i.work if c.work})
    pids = sorted({p for i in raw_individuals for p in i.external_id})
    sites = sorted({link.site for i in raw_individuals for link in i.sitelink if link.site})

    raw_places = T.places(place_qids)
    raw_countries = T.countries(country_qids)
    raw_occupations = T.occupations(occupation_qids)
    raw_works = T.works(work_qids)
    raw_identifiers = T.external_id_properties(pids)
    raw_properties = T.properties()
    raw_polities = T.polities()

    spans = {}
    for span in raw_polities:
        spans.setdefault(span.name, []).append(span)

    individuals = [C.individual(raw) for raw in raw_individuals]

    tables = {
        "individual": individuals,
        "individual_enriched": [],
        "polity": [C.polity(number, group) for number, group in enumerate(spans.values(), start=1)],
        "place": [C.place(raw) for raw in raw_places] + [C.country(raw) for raw in raw_countries],
        "occupation": [C.occupation(raw) for raw in raw_occupations],
        "work": [C.work(raw) for raw in raw_works],
        "identifier": [C.identifier(raw) for raw in raw_identifiers],
        "individual_identifier": [entry for one in individuals for entry in one.external_id],
        "sitelink": [C.sitelink(site) for site in sites],
        "wikidata_property": [C.wikidata_property(raw) for raw in raw_properties],
        "individual_sitelink": [entry for one in individuals for entry in one.sitelink],
        "individual_work": [entry for one in individuals for entry in one.work],
    }

    if TARGET.exists():
        TARGET.unlink()
    connection = duckdb.connect(str(TARGET))
    for name, model in D.TABLES.items():
        count = write_table(connection, name, model, tables[name], SCRATCH)
        print(f"   {name:24} {count:>9,}", flush=True)
    connection.close()
    print(f"\n{TARGET}  {TARGET.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
