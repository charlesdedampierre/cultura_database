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
| 05b | `05b_cohort_age_stats.py` | `Individual.birth_date`, `.death_date`, `.floruit_date` (Wikidata entries only), `CrossVerifiedPerson.level1_main_occ` | `CohortAgeStats`, the table `cohort_age_stats` | the measurement itself |
| 06 | `06_peak_productivity.py` | `Individual.birth_date`, `.death_date`, `.floruit_date`, `.works_period` | `IndividualEnriched.peak_productivity`, and one more entry in `Individual.birth_date`, `.death_date` estimated from life expectancy | the database itself |
| 06b | `06b_western_continents_and_worlds.py` | `Sitelink.url`, `PresentDayState.name`, `Polity.name` | `Sitelink.is_western`, `PresentDayState.continent`, `PresentDayState.is_western`, `Polity.world` (and the polities nested in `IndividualEnriched.polity`) | the lists in the script itself, drawn up by Claude |
| 07b | `07b_polity_hierarchy.py` | `PolityCliopatria.name`, `.type`, `.components`, `.member_of` | `Polity.meta_polities`, `Polity.child_polities` (and splits each meta polity into a row of its own) | the Cliopatria GeoJSON |
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

05b writes `cohort_age_stats`: one row per cross-verified occupation category
(plus `All`, every individual) and fifty-year birth cohort, from 3500 BCE to
1949 — 763 rows, none empty. Cohorts born from 1950 on are left out, most of them being still alive. Each holds the quartiles of age at death (Wikidata
birth and death) and of age at floruit (Wikidata birth and floruit). A cohort
with fewer than 10 lives, or 5 floruits, borrows a wider pool — one cohort on
each side, three, the occupation over all cohorts, every individual — and the
rule in `field_provenance` names the pool used. People born from 1950 on are
left out of every pool, not only of their own cohort. It runs before 06 so that the
peak-productivity window can read it.

## The peak activity window

06 is the one to read closely. Its priority is the order of `RULES` and nothing
else; each rule is written below the tuple and registers itself, and the script
refuses to start if the two disagree. The first rule that yields a window wins:

1. Dates stated to the year or the decade — `died_young` (dead at 18 or
   younger: the whole life counts), `floruit`, `birth_and_death`, `birth_only`,
   `death_only` (the birth is the death minus the cohort's median life
   expectancy, then the productive-age window runs from it, cut at the death).
2. Births and deaths stated only to the century or millennium, giving a
   window named in centuries: born and dead in the same century → that century;
   in consecutive centuries → "late 4th century – early 5th century"; birth
   only → that century and the next; death only → the century before and that
   one. A floruit stated only to the century or millennium is never used.
3. Dated works — `works_span`, `works_single` — the last resort, used only when
   no birth, death or floruit says anything.

Within a rule, the date from the source earliest in `SOURCE_PRIORITY` is used.

`peak_productivity` holds `start_year`, `end_year`, `assignation_method`,
`precision` (`year`, `century`, `millennium`) and `label`. For a century window
the label is the claim; the years are only the bounds of those centuries, kept
so 08 can test territories against them.

The productive-age window and the life expectancy are read from
`cohort_age_stats`, for the individual's cross-verified occupation (or All) and
fifty-year birth cohort.
Only dates stated to the year or the decade choose the cohort; an individual
dated by nothing finer than a century has no cohort, and so no life expectancy
or productive-age window, though a century rule can still give them a window.

06 also fills the birth or death year an individual lacks from the one they
have, by the median life expectancy of the same cohort row: a death year and no
birth year stated to the year or the decade gives a birth year (the same one
`death_only` uses), and a birth year and no death year gives a death year, but
only to someone born more than 110 years ago, who cannot still be alive. Each
estimate is appended after every stated date, at precision `year` with no
`iso`, and its own `field_provenance` names the rule and its inputs, so it reads
as `life_expectancy_estimate` in `SOURCE_PRIORITY`. Each run first removes the
estimates the previous run appended, so the window is always built on stated
dates and a rerun does not stack them.

## The polity assignment

08 puts each individual on the ground they stood on while they were at work. It
is `scripts/legacy/database_consolidation_V2/04_individuals_cliopatria_rs`
rewritten in Python, and its priority is two tuples, as 06's is:

- `TESTS` — the location and the way it is matched, in order: the country of
  citizenship's Wikipedia article; the deathplace by polygon, then by article;
  the birthplace by polygon, then by article; and last the country of
  citizenship by polygon. The deathplace comes before the birthplace because,
  of every order of these tests, it agreed best with the Treccani biographies
  (37 of 49 individuals, against 32 with the birthplace first). A state's coordinates are one point near its middle,
  which puts anyone with Italian citizenship in the Papal States, so that test
  only runs when nothing else matched. The first test that matches anything
  ends the search.

Within each test the sub-polities are tried first, and a meta polity (one with
`child_polities`) is matched only when no sub-polity is. Each match carries the
polity's `meta_polities`.

Every polity whose territory covers the place and whose years overlap the peak
activity window is kept, not only the closest fit: a city inside both a kingdom
and another polity overlapping it produces two matches, and `polity_count` is the length
of that list.

`years_spent_in_polity` counts each calendar year of the window **once**,
however many of that polity's territories cover it. The Rust summed the
per-territory overlaps instead, which is why a polity with 212 territory rows
could report 744 years inside a 65-year life; its own comment says the union
was intended. `COUNT_YEARS_ONCE` at the top of the file switches between the
two.
