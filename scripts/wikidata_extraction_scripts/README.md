# wikidata_extraction_scripts_v2/

Clean, single-purpose scripts that pull each slice of the Cultura database
from Wikidata and save it as JSON. One script per topic, all sharing the
same client (`wikidata.py`) and the same CLI conventions.

This is a v2 rewrite of `extraction_scripts/all_humans/`. The legacy
JSON files in `data/all_humans/` are left untouched — every output of these
new scripts goes to the isolated subfolder
`data/all_humans/wikidata_extraction_scripts_v2/`.

## Layout

The pipeline is split into two passes. The **per-human pass** (01–09) pulls
one fact set per Q5 human. The **entity-metadata pass** (10–14) pulls
metadata for every QID those facts reference (places, nationalities,
occupations, modern countries, identifier-type properties), so downstream
SQLite consolidation has everything it needs without any extra Wikidata
calls.

### Per-human (01–09)

| Script | Output (under `data/all_humans/wikidata_extraction_scripts_v2/`) | Properties |
|---|---|---|
| `01_extract_main_info.py` | `main_info.json` | rdfs:label, schema:description, P21, P569, P570, P1317 |
| `02_extract_places.py` | `places.json` | P19, P20 |
| `03_extract_occupations.py` | `occupations.json`, `occupation_labels.json` | P106 + labels |
| `04_extract_nationalities.py` | `nationalities.json`, `nationality_labels.json` | P27 + labels |
| `05_extract_sitelinks.py` | `sitelinks.json` | schema:about / schema:isPartOf |
| `06_extract_catalogs.py` | `catalogs.json`, `catalog_properties.json`, `identifiers_per_property/Pxxx.json` | every `wikibase:ExternalId` property + values |
| `07_extract_works.py` | `works.json`, `work_labels.json` | P50 P170 P86 P57 P162 P98 P175 P110 P58 + labels |
| `08_extract_writing_languages.py` | `writing_languages.json`, `writing_language_labels.json` | P6886 + labels |
| `09_extract_date_precisions.py` | `date_precisions.json` | `wikibase:timePrecision` for P569 / P570 / P1317 |

### Entity metadata (10–14)

| Script | Output | Properties |
|---|---|---|
| `10_extract_place_metadata.py` | `place_metadata.json` | for every P19/P20 place: rdfs:label, P625, P17, P31 (entity types), enwiki URL |
| `11_extract_nationality_metadata.py` | `nationality_metadata.json` | for every P27: rdfs:label, schema:description, P31, P17, P1366, P36, P625, capital→P625, enwiki URL |
| `12_extract_occupation_metadata.py` | `occupation_metadata.json` | for every P106: schema:description, P31, P279 |
| `13_extract_modern_countries.py` | `modern_countries.json` | every Q with P298: rdfs:label, P298, P30, P36, enwiki URL |
| `14_extract_catalog_metadata.py` | `catalog_metadata.json` | for every external-ID property: rdfs:label, schema:description, P126/P137 (issuer), P17 (country), P571 (inception), P4876 (records), P856 (website), P1630 (formatter URL) |
| `run_all.py` | — | runs every extractor in order (01 → 14) |

The shared client lives in `wikidata.py`.

## Conventions

Every `NN_extract_*.py` exposes the same two flags:

```bash
python scripts/wikidata_extraction_scripts_v2/01_extract_main_info.py --test  # ~5 s, writes *.test.json
python scripts/wikidata_extraction_scripts_v2/01_extract_main_info.py         # full extraction, writes the real JSON
```

Or run them all in sequence:

```bash
python scripts/wikidata_extraction_scripts_v2/run_all.py --test
python scripts/wikidata_extraction_scripts_v2/run_all.py
```

### `--test` mode

1. Runs a `LIMIT 100` query against the **official Wikidata SPARQL endpoint**
   (WDQS) — chosen for tests because it is more reliable than QLever for
   tiny queries and decouples smoke tests from QLever's uptime.
2. Writes `*.test.json` to the output dir.
3. Prints a 5-row sample so you can eyeball the shape.

You can validate any script in seconds before launching the multi-minute
full pull.

### Full mode

The full extraction streams from **QLever**
(`https://qlever.cs.uni-freiburg.de/api/wikidata`) — necessary because the
queries return tens of millions of rows and WDQS would time out.

## Output directory

All JSON outputs are written to
`data/all_humans/wikidata_extraction_scripts_v2/` (created on demand). This
directory is intentionally separate from the legacy `data/all_humans/*.json`
files so the v2 pipeline never overwrites anything from v1.

## Re-running

Full extracts overwrite their output JSON. The catalogs script writes
per-property files under
`data/all_humans/wikidata_extraction_scripts_v2/identifiers_per_property/`
and skips any property whose JSON already exists, so you can resume safely.

## Dependencies

`requests`, `tqdm` — already in `requirements.txt`. Activate the project's
`.venv` before running.
