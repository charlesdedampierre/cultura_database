# database_enrichment/

Enrichment steps that read `data/cultura_v2.duckdb` — the database
`scripts/raw_to_db/build_database.py` writes from the raw files — and add to it the
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
| 00 | `00_productive_age_window.py` | `IndividualWikidata.date_of_birth`, `.floruit`, `CrossVerifiedPerson.level1_main_occ` | `data/productive_age_window.csv` | the measurement itself |
| 05b | `05b_occupation_stats.py` | `Individual.birth_date`, `.death_date`, `.floruit_date` (Wikidata entries only), `CrossVerifiedPerson.level1_main_occ` | `OccupationStats`, the table `occupation_stats` | the measurement itself |
| 06 | `06_peak_productivity.py` | `Individual.birth_date`, `.death_date`, `.floruit_date`, `.works_period` | `IndividualEnriched.peak_productivity` | the database itself |
| 06b | `06b_western_continents_and_worlds.py` | `Sitelink.url`, `PresentDayState.name`, `Polity.name` | `Sitelink.is_western`, `PresentDayState.continent`, `PresentDayState.is_western`, `Polity.world` (and the polities nested in `IndividualEnriched.polity`) | the lists in the script itself, drawn up by Claude |
| 08 | `08_polity_assignment.py` | `Individual.place_of_birth`, `.place_of_death`, `.country_of_citizenship`, `Place.coordinates`, `Place.sitelink`, `Polity.territories`, `Polity.sitelink`, `IndividualEnriched.peak_productivity` | `IndividualEnriched.polity`, `.polity_count` | the database itself |
| 05 | `05_is_human.py` | `Individual.place_of_birth`, `.place_of_death`, `.country_of_citizenship`, `Place.instance_of` | `Individual.is_human` | `city_entity_types.json` |

01 and 02 are the fields a language model produced. 06b holds lists Claude drew up for this project — Western and non-Western Wikipedia languages, Western countries, the Latin America and Middle East regroupings, and the cultural worlds of polities — and writes them; the datamodel only declares the fields. Neither script calls one:
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

## The productive age window

`00_productive_age_window.py` measures it rather than assuming it: for every
individual whose birth year and Wikidata floruit are both stated to the year,
the age at that floruit, quartered, globally and per cross-verified occupation
category. It writes `data/productive_age_window.csv`, which 06 reads. The
numbers are 29 to 53 over 16 106 individuals globally, and the file carries the
count beside each window so a category measured on 10 people is visible as such.

## Life expectancy and productivity window per occupation and cohort

05b writes `occupation_stats`: one row per cross-verified occupation category
(plus `All`, every individual) and fifty-year birth cohort, from 3500 BCE to
2049 — 777 rows, none empty. Each holds the quartiles of age at death (Wikidata
birth and death) and of age at floruit (Wikidata birth and floruit). A cohort
with fewer than 10 lives, or 5 floruits, borrows a wider pool — one cohort on
each side, three, the occupation over all cohorts, every individual — and the
rule in `field_provenance` names the pool used. Recent cohorts run low: only
those who have already died carry a death date. It runs before 06 so that the
peak-productivity window can read it.

## The peak activity window

06 is the one to read closely. Its priority is the order of two tuples and
nothing else:

- `RULES` — `floruit`, `works_span`, `works_single`, `birth_and_death`,
  `birth_only`, `death_only`, and an individual none of them fits gets
  `no_data`. The first that yields a window wins. The tuple is the first thing
  in the file; each rule is written below it and registers itself, and the
  script refuses to start if the two disagree.
- `SOURCE_PRIORITY` — `wikidata_property`, `wikidata_entity_description`,
  `cross_verified_database`, `wikipedia_article`, `life_expectancy_estimate`.
  Within a rule, the date from the earliest source in this list is the one
  used. Each date's source is read off its own provenance, so moving a source
  is moving one name in this tuple.

`peak_productivity` holds three things: `start_year`, `end_year`, and
`assignation_method`, which names the rule and the date source that produced
them. It is always a range. Where a source states a single year — a floruit, or
the only dated work — that year anchors the range rather than becoming it.

Year-precise dates are tried before coarse ones: the whole of `RULES` runs over
day, month and year precision first, and only then over decade, century and
millennium. `assignation_method` on the row names the rule and the source that
won, `works_span` or `birth_death_property`, so every window says how it was
made. An individual no rule fits gets `no_data`.

The window inferred from a birth year is read from
`data/productive_age_window.csv`, category `global`. The per-occupation windows
in that file are not applied: they are keyed by the cross-verified occupation
category, which this database does not carry.

## The polity assignment

08 puts each individual on the ground they stood on while they were at work. It
is `scripts/legacy/database_consolidation_V2/04_individuals_cliopatria_rs`
rewritten in Python, and its priority is two tuples, as 06's is:

- `PHASES` — `polygon_containing_the_place`, then
  `wikipedia_article_shared_with_the_polity` for those the polygons left
  unmatched.
- `LOCATION_PRIORITY` — per phase. Polygons are tried deathplace, birthplace,
  country of citizenship; articles country of citizenship, deathplace,
  birthplace. The first location that matches anything ends the search, so a
  deathplace inside a polygon settles it and the birthplace is never tried.

Every polity whose territory covers the place and whose years overlap the peak
activity window is kept, not only the closest fit: a city inside both a kingdom
and the empire above it produces two matches, and `polity_count` is the length
of that list.

`years_spent_in_polity` counts each calendar year of the window **once**,
however many of that polity's territories cover it. The Rust summed the
per-territory overlaps instead, which is why a polity with 212 territory rows
could report 744 years inside a 65-year life; its own comment says the union
was intended. `COUNT_YEARS_ONCE` at the top of the file switches between the
two.
