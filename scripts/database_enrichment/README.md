# database_enrichment/

Enrichment steps that read `data/cultura_v2.duckdb` — the database
`scripts/raw_to_db/build.py` writes from the raw files — and add to it the
fields that are not stated by any source. The raw build computes nothing; every
computed field in `datamodel_in_duckdb.py` is written here.

Each script declares its contract at the top, as an `Enrichment`, and prints it
when it runs:

| | |
|---|---|
| `reads` | the fields of `datamodel_in_duckdb.py` the rule is applied to |
| `writes` | the field it fills |
| `rule` | what was done to get from one to the other, in one sentence |
| `answers` | where the saved result lives, for a field a model produced |
| `prompt_id` | the prompt in `prompts/`, for a field a model produced |

That same declaration becomes the `Provenance` written into the row's
`field_provenance`, so the contract in the code and the record in the database
cannot drift apart.

## Steps

| # | Script | Reads | Writes | Answers |
|---|---|---|---|---|
| 01 | `01_is_settlement.py` | `Place.instance_of` | `Place.is_settlement` | `data/raw_data_from_wikidata/entity_type_classification.json` |
| 02 | `02_wikipedia_dates.py` | `Individual.entity` | one more entry in `Individual.birth_date`, `.death_date`, `.floruit_date` | `data/humans_clean.duckdb` columns `birthdate_from_wikipedia`, `deathdate_from_wikipedia`, `floruit_from_wikipedia` |
| 03 | `03_works_period.py` | `Individual.work`, `Work.publication_date`, `Work.inception` | `Individual.works_period` | the database itself |
| 04 | `04_is_scientist_is_artist.py` | `Individual.occupation` | `Individual.is_scientist`, `Individual.is_artist` | `suboccupations_scientist_artist.json` |
| 05 | `05_is_human.py` | `Individual.place_of_birth`, `.place_of_death`, `.country_of_citizenship`, `Place.instance_of` | `Individual.is_human` | `city_entity_types.json` |

01 and 02 are the fields a language model produced. Neither script calls one:
the answers were saved when the model was run and are read back from where they
were saved, so a rerun cannot change them. 03, 04 and 05 are rules, and the
rule is in the script.

05 is worth reading before it is used. It tests the individual's places, not
the individual: False means a birthplace, deathplace or citizenship whose
Wikidata classes are labelled fictional, mythical, legendary, imaginary or
hypothetical. Someone born in a fictional city is taken to be a fictional
character. A False is evidence, a True is only the absence of it.

## Running

```bash
.venv/bin/python scripts/database_enrichment/01_is_settlement.py
.venv/bin/python scripts/database_enrichment/02_wikipedia_dates.py
```

`CULTURA_DB` points them at another database; `SCRATCH` at another staging
directory.

## Still to write

`IndividualEnriched` is empty until the two rule-based steps are written: the
peak activity window, and the polity assignment that reads it.
