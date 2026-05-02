# database_integration_scripts_V2/

Build a fresh `data/humans_v2.sqlite3` from the JSON outputs of
`scripts/wikidata_extraction_scripts_v2/`. One script per table, all sharing
`common.py` and the same `--full` / `--sample` CLI.

This pipeline never touches the legacy `data/humans_clean.sqlite3` — it
always writes to a separate file (`data/humans_v2.sqlite3` for full builds
or `data/humans_v2.sample.sqlite3` for the end-to-end test).

## Layout

| # | Script | Output table | Inputs (under `data/all_humans/wikidata_extraction_scripts_v2/`) |
|---|---|---|---|
| 02 | `02_create_cities.py` | `cities` | `place_metadata.json`, `modern_countries.json` (lookup-only — no `modern_country` table any more; the raw country list lives in `data/legacy_regions/modern_country.csv`) |
| 03 | `03_create_country_of_citizenship.py` | `country_of_citizenship` | `nationality_metadata.json`, `nationality_labels.json` |
| 04 | `04_create_occupations.py` | `occupations` | `occupation_labels.json`, `occupation_metadata.json` |
| 05 | `05_create_writing_languages.py` | `writing_languages` | `writing_language_labels.json` |
| 06 | `06_create_identifier_types.py` | `identifier_types` | `catalog_properties.json`, `catalog_metadata.json` |
| 07 | `07_create_individuals.py` | `individuals` | `main_info.json`, `places.json`, `date_precisions.json`, `occupations.json`, `nationalities.json`, `sitelinks.json`, `catalogs.json`, `works.json`, `writing_languages.json`, `writing_language_labels.json` |
| 08 | `08_create_identifiers.py` | `identifiers` | `catalogs.json` |
| 09 | `09_create_wikimedia_links.py` | `wikimedia_links` | `sitelinks.json` |
| 10 | `10_create_works.py` | `works` | `works.json`, `work_labels.json` |
| 11 | `11_create_individual_writing_languages.py` | `individual_writing_languages` | `writing_languages.json` |
| 12 | `12_create_individuals_floruit.py` | `individuals_floruit` | `main_info.json`, `date_precisions.json` |

The 2026-05 schema cleanup retired five tables:
`modern_country`, `regions`, `individuals_regions`, `individuals_countries`,
`individuals_impact_date`. Their data is preserved as CSV under
`data/legacy_regions/`. Three tables were renamed in the same change:
`sitelinks → wikimedia_links`, `nationalities → country_of_citizenship`,
`cliopatria_polity_periods → polities_periods_cliopatria`. The
extraction-pass JSON filenames (`sitelinks.json`, `nationalities.json`,
`modern_countries.json`) are kept as-is so we don't have to re-run the
multi-hour Wikidata pull.

The shared module `common.py` exposes:

- `WIKIDATA_V2_DIR` — `data/all_humans/wikidata_extraction_scripts_v2`
- `DB_PATH`         — `data/humans_v2.sqlite3` (the v2 build target)
- `SAMPLE_DB_PATH`  — `data/humans_v2.sample.sqlite3` (used by the test)
- `LEGACY_DB_PATH`  — `data/humans_clean.sqlite3` (read-only reference; never written)

## Running

```bash
# 1. produce the JSON inputs (full extraction takes hours)
python scripts/wikidata_extraction_scripts_v2/run_all.py

# 2. build the SQLite
python scripts/database_integration_scripts_V2/build_all.py
```

Each script also runs standalone in synthetic-sample mode:

```bash
python scripts/database_integration_scripts_V2/02_create_cities.py
python scripts/database_integration_scripts_V2/02_create_cities.py --full
```

## End-to-end test

The fastest way to validate the whole pipeline:

```bash
python scripts/wikidata_extraction_scripts_v2/run_all.py --test     # ~2 min, populates *.test.json
python scripts/database_integration_scripts_V2/test_end_to_end.py   # builds humans_v2.sample.sqlite3
```

`test_end_to_end.py`:

1. Verifies `humans_clean.sqlite3` is not modified.
2. Builds a fresh `data/humans_v2.sample.sqlite3` from the v2
   `*.test.json` files.
3. Asserts every table exists and meets a minimum row threshold.

## Downstream consolidation

Three follow-on concerns live in `scripts/database_consolidation/` because
they need either time-aware logic or external Cliopatria data:

1. `01_individuals_floruit_period.py` — derive a working period per Q5
2. `02–03` — import Cliopatria polities + period geometries
3. `04_individuals_cliopatria.py` — assign each Q5 to a polity (year-aware,
   polygon-first, URL fallback)

See `scripts/database_consolidation/README.md`.

## Legacy

The previous in-place "fix everything" pipeline (60+ scripts: encoding
fixes, region rebuilds, polity renames, etc.) is preserved under
`legacy/` for reference. None of it is part of the v2 build.
