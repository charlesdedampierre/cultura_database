# Tables of cultura_database_V4.duckdb

One DuckDB file, opened read-only with `duckdb.connect('cultura_database_V4.duckdb', read_only=True)`. Individuals are joined across tables on their Wikidata identifier (`entity.qid`, or `qid` in the link tables). Nested types used by several tables are described once, under Nested types.

## `individual`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Individual's Wikidata item. |
| `birth_date` | list of Date | Every birth date, one per source, in order: Wikidata property, Wikidata description, life-expectancy estimate (enrichment step 13). |
| `death_date` | list of Date | Every death date, on the same terms. |
| `floruit_date` | list of Date | Every floruit date: Wikidata property, then Wikidata description. |
| `place_of_birth` | Place | Birthplace, P19: qid and name only. |
| `place_of_death` | Place | Deathplace, P20: qid and name only. |
| `sex_or_gender` | str | P21, as a qid. |
| `occupation` | list of Occupation | Occupations, P106, as qids; labels are in the Occupation table. |
| `country_of_citizenship` | list of Place | Countries of citizenship, P27, historical states included. |
| `work_location` | list of Place | Work locations, P937: qid and name only. |
| `residence` | list of Place | Residences, P551: qid and name only. |
| `employer` | list of Institution | Employers, P108: qid and name only; details in the Institution table. |
| `educated_at` | list of Institution | Schools and universities, P69: qid and name only; details in the Institution table. |
| `position_held` | list of PositionHeld | Positions held, P39: one per non-deprecated statement, in Wikidata's order, with its start and end dates when stated (step 09). |
| `writing_language` | list of str | Writing languages, P6886, as qids. |
| `external_id` | list of IndividualIdentifier | Records held by external databases. |
| `sitelink` | list of IndividualSitelink | Wikimedia pages about the individual, one per edition. |
| `work` | list of IndividualWork | Works credited to the individual. |
| `works_period` | WorksPeriod | Years spanned by their dated works. |
| `is_human` | bool | False when a place they are tied to is fictional (enrichment step 04). |
| `is_scientist` | bool | True when an occupation descends from scientist, Q901. |
| `is_artist` | bool | True when an occupation descends from artist, Q483501. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `individual_enriched`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Individual, joining to Individual.entity.qid. |
| `birth_date` | IndividualDate | The Wikidata birth, else the death year minus the cohort's mean age at death (01_notebooks_dates/01_age_at_death); a coarse_label alone for an individual with only coarse dates (01_notebooks_dates/05_coarse_dates). |
| `death_date` | IndividualDate | The Wikidata death, else the birth year plus the cohort's mean age at death, for births up to 1920 (01_notebooks_dates/01_age_at_death); a coarse_label alone for an individual with only coarse dates (01_notebooks_dates/05_coarse_dates). |
| `start_of_active_life` | IndividualDate | The earliest dated work, position start or position end, else the birth year plus the cohort's median age at the start of the active life, no later than its end (01_notebooks_dates/03_b_active_life). For an individual with a century- or millennium-level birth or death: a century label without a year, the century of the estimate, else the century of the birth (enrichment step 10). |
| `end_of_active_life` | IndividualDate | The latest dated work, position start or position end, else the birth year plus the cohort's median age at the end of the active life, capped at the death (01_notebooks_dates/03_b_active_life). For an individual with a century- or millennium-level birth or death: a century label without a year, the century of the estimate, else the century of the death (enrichment step 10). |
| `active_life_ongoing` | bool | True when the individual has no death year and end_of_active_life is in or after 2026 (or empty): the active life is still going on, its end is 'ongoing', its polities were matched up to 2026, and there is no post-active stage. False for an active life that has ended; empty for an individual given no life stage (no birth year or no active life) (02_notebooks_polity/01_life_stage_polities_export.py). |
| `pre_active_life_polity` | list of PolityMatch | Every polity matched from birth_date to start_of_active_life, longest overlap first. |
| `active_life_polity` | list of PolityMatch | Every polity matched from start_of_active_life to end_of_active_life (to 2026 when active_life_ongoing), longest overlap first. |
| `post_active_life_polity` | list of PolityMatch | Every polity matched from end_of_active_life to death_date, longest overlap first; empty for an individual with no death year. |
| `main_polity` | PolityMatch | The first match of active_life_polity, the polity with the longest overlap. |
| `notability` | Notability | Western and non-Western Wikipedia coverage and the cross-cultural score (enrichment step 06). |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Rule and inputs of each value, keyed by column. |

## `polity`

| Field | Type | Description |
| --- | --- | --- |
| `cliopatria_id` | int | Polity id, assigned by this project when Cliopatria was loaded. |
| `name` | str | Name as Cliopatria spells it, 'Ottoman Empire'. |
| `meta_polities` | list of PolityLink | Meta polities this polity directly belonged to, with the years. |
| `child_polities` | list of PolityLink | Polities this meta polity was made of, with the years; empty on a base polity. |
| `existence_wikidata` | ExistencePeriod | Inception and dissolution according to Wikidata. |
| `entity` | WikidataEntity | Wikidata item Cliopatria resolved for the polity, if any. |
| `sitelink` | Sitelink | English Wikipedia article. |
| `territories` | list of Territory | Ground held, one entry per change of borders, oldest first. |
| `world` | list of str | Cultural worlds the polity belongs to, from lists in data/ai_outputs/ (enrichment step 05). |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `place`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Place's Wikidata item; cities, states and buildings share this table. |
| `coordinates` | Coordinates | Point location, P625. |
| `country` | WikidataEntity | Country Wikidata declares the place to be in, P17. |
| `instance_of` | list of WikidataEntity | Classes of the place, P31. |
| `existence` | ExistencePeriod | Years the place existed. |
| `present_day_state` | PresentDayState | State holding the ground today, from a reverse geocoder on the coordinates. |
| `sitelink` | Sitelink | English Wikipedia article. |
| `is_settlement` | bool | Whether the place is a populated place, from an AI classification of its classes (enrichment step 03). |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `institution`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Employer or school's Wikidata item. |
| `instance_of` | list of WikidataEntity | Classes of the institution, P31: university, company, monastery... |
| `location` | Place | Place it is in: P131, else headquarters P159, else location P276; qid and name only, coordinates and country are in the Place table. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `occupation`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Occupation's Wikidata item. |
| `subclass_of` | list of WikidataEntity | Parent occupations, P279. |
| `meta_occupation` | text: 'Culture', 'Discovery/Science', 'Leadership', 'Sports/Games', 'Other' | Cross-Verified level-1 domain of the occupation, from an AI classification of its label (enrichment step 09). |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `work`

| Field | Type | Description |
| --- | --- | --- |
| `entity` | WikidataEntity | Work's Wikidata item, its title as the label. |
| `instance_of` | list of WikidataEntity | Classes of the work, P31. |
| `inception` | Date | When the work was made, P571. |
| `publication_date` | Date | When it was first published, P577. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `identifier`

| Field | Type | Description |
| --- | --- | --- |
| `property` | WikidataProperty | Property carrying the identifier, 'P214' for VIAF. |
| `formatter_url` | str | URL template with $1 for the value, P1630. |
| `issuer` | WikidataEntity | Organisation issuing the identifiers, P1629. |
| `issuer_country` | PresentDayState | Country of the issuer. |
| `official_website` | str | Website of the property or of its issuer, P856. |
| `number_of_records` | int | How many records the database holds, P4876. |
| `inception` | Date | When the database was founded, P571. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `individual_identifier`

| Field | Type | Description |
| --- | --- | --- |
| `qid` | str | Individual, joining to Individual.entity.qid. |
| `pid` | str | Database, joining to Identifier.property.pid; a pair can recur with several values. |
| `value` | str | Identifier as the database issued it. |
| `url` | str | Record URL built from the formatter URL. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `sitelink`

| Field | Type | Description |
| --- | --- | --- |
| `url` | str | Wikimedia edition URL, 'https://fr.wikipedia.org'; not all are Wikipedias. |
| `label_en` | str | Edition name in English, 'French Wikipedia'. |
| `language` | str | Language of the edition, as a qid. |
| `is_western` | bool | Whether a Wikipedia edition counts as Western, from lists in data/ai_outputs/ (enrichment step 05); empty for other sites. |
| `number_of_articles` | int | How many individuals in Cultura the edition has a page on. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `wikidata_property`

| Field | Type | Description |
| --- | --- | --- |
| `pid` | str | Property identifier, 'P569'. |
| `label_en` | str | English label, 'date of birth'. |
| `description` | str | What the property means, in Wikidata's words. |

## `individual_sitelink`

| Field | Type | Description |
| --- | --- | --- |
| `qid` | str | Entity the page is about. |
| `url` | str | Page URL. |
| `site_url` | str | Edition, joining to Sitelink.url. |
| `title` | str | Article title in that edition. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## `individual_work`

| Field | Type | Description |
| --- | --- | --- |
| `qid` | str | Individual credited. |
| `work_qid` | str | Work, joining to Work.entity.qid. |
| `credit_property` | WikidataProperty | Property that credits them: P50 author, P170 creator, P175 performer... |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

## Nested types

### AIAnswer

| Field | Type | Description |
| --- | --- | --- |
| `model_name` | str | Exact model id that produced the value. |
| `prompt_id` | str | Name of the prompt file in scripts/prompts/ that was sent. |

### Cohort

| Field | Type | Description |
| --- | --- | --- |
| `occupation` | str | Meta occupation of the cohort; empty when the cohort is every individual. |
| `century` | int | First year of the cohort's century of birth, -500 for 500-401 BC; empty when the age is averaged over the centuries. |
| `individuals` | int | Individuals the cohort's age was learnt from. |
| `age` | float | Age the estimate used: the cohort's mean age at death, its median age at the first or the last work, or its median age at the start or the end of the active life. |

### Coordinates

| Field | Type | Description |
| --- | --- | --- |
| `latitude` | float | Decimal degrees, negative south of the equator. |
| `longitude` | float | Decimal degrees, negative west of Greenwich. |

### Date

| Field | Type | Description |
| --- | --- | --- |
| `iso` | str | ISO date, '1879-03-14'; a leading minus is before the common era. Empty for a bare year. |
| `year` | int | The year alone; negative before the common era. |
| `precision` | text: 'day', 'month', 'year', 'decade', 'century', 'millennium' | How precisely the source states the date. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Where this one date came from: no rule for a stated date, a rule for one the project worked out. |

### ExistencePeriod

| Field | Type | Description |
| --- | --- | --- |
| `inception` | Date | When it came into being, P571. |
| `dissolution` | Date | When it ceased to exist, P576; empty if it still exists. |

### IndividualDate

| Field | Type | Description |
| --- | --- | --- |
| `iso` | str | ISO date, '1879-03-14'; a leading minus is before the common era. Empty for a bare year. |
| `year` | int | The year alone; negative before the common era. |
| `precision` | text: 'day', 'month', 'year', 'decade', 'century', 'millennium' | How precisely the source states the date. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Where this one date came from: no rule for a stated date, a rule for one the project worked out. |
| `source` | text: 'wikidata', 'dated works', 'dated works and positions', 'estimated', 'estimated from the century dates' | 'wikidata' for a birth or death stated in Wikidata, 'dated works' for a work date read from the individual's works, 'dated works and positions' for an active-life date read from the individual's dated works and positions held, 'estimated' when imputed from the ages of the cohort, 'estimated from the century dates' for the century-level active life of an individual known only to the century (enrichment step 10). |
| `cohort` | Cohort | Cohort whose age gave an estimated date. |
| `coarse_label` | str | '6th AC', '6th BC' ('2nd millennium BC' for a millennium) for an individual with only coarse dates, who could not be imputed: the year is left empty so that analyses do not draw it in, and these categories must be removed before any use of the year (01_notebooks_dates/05_coarse_dates). |

### Notability

| Field | Type | Description |
| --- | --- | --- |
| `number_of_western_editions` | int | Western Wikipedia editions with a page on the individual. |
| `number_of_non_western_editions` | int | Non-Western Wikipedia editions with a page on the individual. |
| `cross_cultural_score` | float | Geometric mean of the two counts; 0 when either is 0. |

### PolityLink

| Field | Type | Description |
| --- | --- | --- |
| `cliopatria_id` | int | Linked polity's id in the Polity table. |
| `name` | str | Linked polity's name. |
| `hierarchy_type` | text: 'composite_polity', 'allegiance', 'alliance', 'vassalage', 'personal_union' | Kind of meta polity the link goes through. |
| `start_year` | int | First year of the link. |
| `end_year` | int | Last year of the link. |

### PolityMatch

| Field | Type | Description |
| --- | --- | --- |
| `polity` | Polity | Matched polity: id, name, world and meta_polities only. |
| `years_spent_in_polity` | int | Years of the stage spent inside this polity, each year counted once. |
| `assignation_method` | text: 'polygon_of_birthplace', 'polygon_of_deathplace', 'polygon_of_country_of_citizenship', 'polygon_of_work_location', 'polygon_of_residence', 'polygon_of_employer', 'polygon_of_educated_at', 'polygon_of_position_held', 'url_of_birthplace', 'url_of_deathplace', 'url_of_country_of_citizenship', 'url_of_work_location', 'url_of_residence', 'url_of_employer', 'url_of_educated_at', 'url_of_position_held' | Which Wikidata location field and which test made the match: 'polygon' when the place's coordinates fall inside the Cliopatria territory, 'url' when the place's Wikipedia article is the polity's own. |
| `location` | str | Label of the place, institution or country the match was read from. |
| `seshat` | list of Seshat | Seshat polities of the polity's territories overlapping the stage, oldest first. |

### PositionHeld

| Field | Type | Description |
| --- | --- | --- |
| `position` | WikidataEntity | Position's Wikidata item, its name as the label: 'Pope', 'Dean of St Paul's'. |
| `start_date` | Date | When they took the position: the statement's start time P580. |
| `end_date` | Date | When they left it: the statement's end time P582. |

### PresentDayState

| Field | Type | Description |
| --- | --- | --- |
| `name` | str | State name in English, 'Russia'. |
| `iso_3166_1_alpha_3_code` | str | ISO 3166-1 alpha-3 code, 'RUS'. |
| `continent` | str | Continent, with 'Latin America' and 'Middle East' regrouped from lists in data/ai_outputs/ (enrichment step 05). |
| `is_western` | bool | Whether the state counts as Western, from a list in data/ai_outputs/ (enrichment step 05). |

### Provenance

| Field | Type | Description |
| --- | --- | --- |
| `raw` | list of str | Fields of datamodel_raw.py the value was read from, as 'Model.field'. |
| `inputs` | list of str | Computed fields of this schema the value was built from. |
| `rule` | str | For a computed value, the rule that produced it, in one sentence. |
| `ai_answer` | AIAnswer | Set when a language model produced the value: which model and prompt. |
| `retrieved_on` | date | Day the source was read. |

### Seshat

| Field | Type | Description |
| --- | --- | --- |
| `id` | str | Seshat Databank polity id, 'fr_valois_k_2'; its page is https://seshat-db.com/core/polity/<id>. |
| `long_name` | str | Seshat long name, 'French Kingdom - Late Valois', from the Seshat API (api/core/polities); None for an id the API does not list. |

### Territory

| Field | Type | Description |
| --- | --- | --- |
| `start_year` | int | First year the polity held this ground. |
| `end_year` | int | Last year it held it. |
| `area` | float | Area in square kilometres. |
| `geometry` | str | GeoJSON Polygon or MultiPolygon as a string, WGS 84 longitude/latitude. |
| `seshat_id` | str | Polity's Seshat Databank id over this span, where Seshat coded it. |
| `present_day_states` | list of PresentDayState | States holding this ground today. |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Source or rule of each value, keyed by column. |

### WikidataEntity

| Field | Type | Description |
| --- | --- | --- |
| `qid` | str | Wikidata identifier, 'Q937'; the join key between tables. |
| `label_en` | str | English (or 'mul') label. |
| `label_non_en` | str | Label in another language, only where there is no English one. |
| `label_language` | str | Language code of the label the item has: 'en', 'mul', 'ru'... |
| `description` | str | English one-line Wikidata description. |

### WorksPeriod

| Field | Type | Description |
| --- | --- | --- |
| `first_year` | int | Year of the earliest cleaned work date (inception, else publication); estimated as birth year + age_at_first_work when no work is dated. |
| `last_year` | int | Year of the latest cleaned work date; estimated as birth year + age_at_last_work when no work is dated. |
| `age_at_first_work` | int | first_year minus the birth year. |
| `age_at_last_work` | int | last_year minus the birth year. |
| `source` | text: 'dated works', 'estimated' | 'dated works' when read from the individual's works, 'estimated' when imputed from the mean ages of their cohort (01_notebooks_dates/02_works_periods). |
| `field_provenance` | dict[str, datamodel_in_duckdb.Provenance] | Rule of each value, keyed by field: how the dated works were cleaned, or which cohort mean estimated it. |
