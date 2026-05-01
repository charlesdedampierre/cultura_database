# City duplicates — preliminary findings

Date: 2026-04-23
DB: `data/humans_clean.sqlite3` · table `cities`
Rows in TSV: 1,727 candidate pairs (see `city_duplicate_candidates.tsv`)

## Method used
- Filtered to `is_urban_settlement = 1` with non-NULL coordinates.
- Kept only entries whose `entity_type_ids` contains a "core city" P31:
  `Q515` city, `Q1549591` big city, `Q5119` capital, `Q200250` metropolis,
  `Q174844` megacity, `Q208511` global city.
- Self-joined on same `iso_a3_code` and |Δlat| < 0.02, |Δlon| < 0.02 (~2 km),
  where `name_en` differs.
- Output ordered by approximate geodesic distance.

## Pattern 1 — Language / transliteration variants (the Rome/Roma case)
| Country | A | B | Distance | IDs |
|---|---|---|---|---|
| ITA | Rome | Roma | ~130 m | Q220 / Q18287233 |
| AUT | Vienna | Wien | ~1.2 km | Q1741 / Q702289 |
| POL | Olsztyn | Allenstein (German) | 0 m | Q82765 / Q21979688 |
| JPN | Kyoto | Kyōto | ~14 m | Q34600 / Q740246 |
| FRA | Clermont-Ferrand | Clairmont | ~230 m | Q42168 / Q2975160 |

## Pattern 2 — Historical vs modern name, same location
| Country | Historical | Modern |
|---|---|---|
| ITA | Mediolanum | Milan |
| EGY | Cusae | El Quseyya |
| VNM | Phú Xuân | Huế |
| CHN | Gungnae (Goguryeo) | Ji'an |
| PSE | Aelia Capitolina | East Jerusalem |

## Pattern 3 — City entity vs administrative container at same centroid
| Country | Pair | Note |
|---|---|---|
| BEL | City of Brussels · Brussels · Brussels-Capital Region (Q239 / Q111901161 / Q240) | 3-way duplicate at centroid |
| ESP | Madrid · "Madrid city" (Q2807 / Q116170766) | Wikidata dual-entry |
| ESP | Badajoz · "Badajoz city"; Ávila · "Ávila City" | same pattern |
| SVN | Kranjska Gora · Municipality of Kranjska Gora | town vs municipality |
| TUR | Tekirdağ · Süleymanpaşa district | city vs encompassing district |
| IND | Virar · Vasai-Virar | town absorbed by successor city |

## Undetectable by coords (no lat/lon in DB — likely duplicates)
- Köln (Q690441) ≈ Cologne (Q365)
- Moskva (Q2638679) ≈ Moscow (Q649)
- København (Q1751706) ≈ Copenhagen (Q1748)
- Lisboa (Q37521246) ≈ Lisbon (Q597)
- Warszawa (Q7970960) ≈ Warsaw (Q270)

## Artefacts
- `annotations/city_duplicate_candidates.tsv` — full list of 1,727 candidate pairs
  within 2 km, same country, different names, both core-city P31.

## Next steps (not yet done)
1. Systematic scan: broaden to all urban settlements, not just core-city P31, and
   output candidates with similarity score (normalized edit distance on names).
2. Resolve NULL-coord variants by fetching Wikidata `P1448` (official name) /
   `skos:altLabel` via QLever.
3. Produce a `city_aliases` table (`alias_id → canonical_id`) and let the map
   collapse duplicates at render time without destroying data.
