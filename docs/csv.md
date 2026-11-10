# Columns of cultura_database_V4.csv

One row per individual, comma-separated with a header. Lists are separated by ' | '. Years before the common era are negative; a date known only to the century or millennium is written as its label ('4th BC').

| Field | Type | Description |
| --- | --- | --- |
| `wikidata_id` | str | The individual's Wikidata qid, 'Q937'. Individual.entity.qid. |
| `label` | str | The English label, else the label in another language. Individual.entity.label_en, else label_non_en. |
| `sex_or_gender` | str | 'male', 'female', 'trans woman', 'trans man' or 'non-binary', else the Wikidata qid of the value. Individual.sex_or_gender. |
| `birth_year` | str | Year of birth, negative before the common era, '-450'; for a date known only to the century or millennium, its label, '20th AC', '4th BC', '2nd millennium AC'. IndividualEnriched.birth_date.year (else coarse_label): Wikidata, else estimated from the cohort's age at death. |
| `birth_precision` | text: 'year', 'decade', 'century', 'millennium' | Precision of birth_year; a date stated to the day or month counts as 'year'. IndividualEnriched.birth_date.precision. |
| `birth_source` | str | 'wikidata (P569, date of birth)' when stated in Wikidata's date of birth; when imputed, 'estimated (cohort: <occupation domain>, born <century of birth>, mean age at death <age>)', the cohort whose mean age at death was subtracted from the death year. IndividualEnriched.birth_date.source. |
| `death_year` | str | Year of death, written as birth_year is. IndividualEnriched.death_date.year (else coarse_label). |
| `death_precision` | text: 'year', 'decade', 'century', 'millennium' | Precision of death_year, as birth_precision. IndividualEnriched.death_date.precision. |
| `death_source` | str | 'wikidata (P570, date of death)' when stated in Wikidata's date of death; when imputed, 'estimated (cohort: ...)' as birth_source, the cohort whose mean age at death was added to the birth year. IndividualEnriched.death_date.source. |
| `active_life_start` | str | First year of the active life, written as birth_year is ('20th AC' for an active life estimated for an individual with a century-level date); empty only for an individual with a century- or millennium-level date and no active life. IndividualEnriched.start_of_active_life.year (else coarse_label). |
| `active_life_end` | str | Last year of the active life, written as active_life_start. IndividualEnriched.end_of_active_life.year (else coarse_label). |
| `active_life_start_precision` | text: 'year', 'decade', 'century', 'millennium' | Precision of active_life_start, as birth_precision. IndividualEnriched.start_of_active_life.precision. |
| `active_life_end_precision` | text: 'year', 'decade', 'century', 'millennium' | Precision of active_life_end, as birth_precision. IndividualEnriched.end_of_active_life.precision. |
| `active_life_source` | str | 'dated works and positions (wikidata: P571, P577, P39)' when read from the individual's dated works (inception P571, else publication date P577) and positions held (P39, with start P580 and end P582), 'estimated (cohort: <occupation domain>, born <century of birth>, ages <median age at start>–<median age at end>)' when imputed from the activity ages of that cohort, 'estimated from the century dates' for the century-level active life of an individual known only to the century (enrichment step 10). IndividualEnriched.start_of_active_life.source. |
| `occupations` | str | English labels of the Wikidata occupations (P106), separated by ' \| '. Individual.occupation, labels from the Occupation table. |
| `occupation_domain` | str | Occupational domains of the individual's occupations (Culture, Discovery/Science, Leadership, Sports/Games), each once in order of first appearance, 'Other' left out, separated by ' \| '; empty when none. Occupation.meta_occupation of each Individual.occupation. |
| `is_scientist` | bool | True when an occupation descends from scientist, Q901. Individual.is_scientist. |
| `is_artist` | bool | True when an occupation descends from artist, Q483501. Individual.is_artist. |
| `pre_active_life_seshat_ids` | str | Seshat ids of the polities matched from birth to the start of the active life ('it_roman_principate', page https://seshat-db.com/core/polity/<id>); 'no Seshat polity associated with Cliopatria id <id> (<Cliopatria name>)' for a matched Cliopatria polity that Seshat does not cover; polities with the most years first, oldest first within a polity, each once, separated by ' \| '. IndividualEnriched.pre_active_life_polity.seshat.id. |
| `pre_active_life_seshat_polities` | str | Seshat long names of pre_active_life_seshat_ids, same order; 'no Seshat name' for an id the API does not list; the same text as the id for a polity Seshat does not cover, separated by ' \| '. |
| `pre_active_life_polity_source` | str | Source of the pre-active life polities: the Wikidata field the stage's polities were located from, how (the Wikipedia article or the coordinates of the place), as 'work location (P937), place coordinates'; one entry per distinct source, separated by ' \| '. PolityMatch.assignation_method. |
| `active_life_seshat_ids` | str | As pre_active_life_seshat_ids, over the active life (for an individual with a century-level date and no dated active life, over its century window, enrichment step 10). IndividualEnriched.active_life_polity.seshat.id. |
| `active_life_seshat_polities` | str | Seshat long names of active_life_seshat_ids, as pre_active_life_seshat_polities. |
| `active_life_polity_source` | str | Source of the active life polities: the Wikidata field the stage's polities were located from, how (the Wikipedia article or the coordinates of the place), as 'work location (P937), place coordinates'; one entry per distinct source, separated by ' \| '. PolityMatch.assignation_method. |
| `post_active_life_seshat_ids` | str | As pre_active_life_seshat_ids, from the end of the active life to death; 'active life ended at death' when the active life runs to the death year, so there is no post-active stage. IndividualEnriched.post_active_life_polity.seshat.id. |
| `post_active_life_seshat_polities` | str | Seshat long names of post_active_life_seshat_ids, as pre_active_life_seshat_polities; 'active life ended at death' as in post_active_life_seshat_ids. |
| `post_active_life_polity_source` | str | Source of the post-active life polities, as active_life_polity_source; 'active life ended at death' when there is no post-active stage. |
| `number_of_works` | int | Distinct works Wikidata credits to the individual (P50 author, P170 creator, P175 performer...), Individual.work counted once per work_qid; 0 for none. |
