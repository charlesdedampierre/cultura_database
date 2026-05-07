# Cross-database comparison — verbatim sources for every cell

For each cell of `notebooks/tables/table2_six_databases.csv` (Table 2 of notebook
`20_cultura_vs_cross_verified.ipynb`), this file records:

- **Verbatim** — the exact sentence quoted from the source paper, **or**
- **Computation** — the dataset queried and the code performed.

Cell coordinates are written `(row → column)`.

---

## 1.  Cultura  (`data/humans_clean.sqlite3`)

> Computed by SQL queries on the project's master SQLite database.

| Cell | Value | Computation |
|---|---|---|
| Total individuals | 13,002,897 | `SELECT COUNT(*) FROM individuals` |
| Linked to a polity / citizenship | 6,128,228 | `SELECT COUNT(DISTINCT wikidata_id) FROM individuals_cliopatria`  *(historical-state attachment via the CliopatriaPolities pipeline)* |
| With a date (floruit) | 7,508,361 | `SELECT COUNT(*) FROM individuals_floruit_period WHERE floruit_period_start IS NOT NULL` |
| With an occupation | 9,032,161 | `SELECT COUNT(*) FROM individuals WHERE occupations_en IS NOT NULL AND occupations_en != ''` |

---

## 2.  Cross-Verified  (Laouenan et al. 2022)

**Source data:** `data/similar_databases/cross-verified-database/cross-verified-database.utf8.csv.gz`  (n = 2,291,817 rows).
**Paper:** *A cross-verified database of notable people, 3500 BC – 2018 AD*, Laouenan, Bhargava, Eyméoud, Gergaud, Plique, Wasmer (2022).

> Computed directly from the published CSV (no paper interpretation needed).

| Cell | Value | Computation |
|---|---|---|
| Total individuals | 2,291,817 | `len(cv)` — number of rows in `cross-verified-database.utf8.csv.gz` |
| Linked to a polity / citizenship | 2,238,318 | `cv["citizenship_1_b"].notna().sum()`  *(`citizenship_1_b` = "Primary citizenship (cleaned country name)" per `columns_dictionary.csv`)* |
| With a date (birth or death) | 2,140,640 | `(cv["birth"].notna() \| cv["death"].notna()).sum()` |
| With an occupation | 2,276,400 | `(cv["level1_main_occ"].notna() & (cv["level1_main_occ"] != "Missing")).sum()` — `level1_main_occ` is always populated; the literal value `"Missing"` (15,417 rows) marks absence |

---

## 3.  Pantheon 2.0  (Yu et al. / MIT Macro Connections, 2025 update)

**Source data:** `data/similar_databases/pantheon 2.0/person_2025_update.csv`  (n = 126,582 rows).

> Computed directly from the CSV.

| Cell | Value | Computation |
|---|---|---|
| Total individuals | 126,582 | `len(p2)` |
| Linked to a polity / citizenship | 123,104 | `(p2["bplace_country"].notna() \| p2["dplace_country"].notna()).sum()` — Pantheon does not store legal citizenship; birth / death country is the closest proxy |
| With a date (birth or death year) | 125,324 | `(p2["birthyear"].notna() \| p2["deathyear"].notna()).sum()` |
| With an occupation | 126,520 | `p2["occupation"].notna().sum()`  *(single-string profession field)* |

---

## 4.  HBR — Human Biographical Record  (Nekoei & Sinn 2020)

**Paper PDF:** `data/similar_databases/HBR/Nekoei and Sinn - 2020 - Human Biographical Record (HBR).pdf`.
**Underlying data:** not redistributed; access request pending (see `data/similar_databases/HBR/access_request_email.md`).
All counts here are derived from the **published Table 1** of the paper (column 1 — full HBR), applying the percentage to the total population.

| Cell | Value | Source |
|---|---|---|
| Total individuals | 7,015,353 | **Verbatim, Table 1, row "Number of Observations":** `7,015,353`. *(Also stated in the abstract: "more than seven million notable individuals across recorded human history".)* |
| Linked to a polity / citizenship | ≈ 5,442,210 | **Computation:** `7,015,353 × 77.59 %`. **Verbatim, Table 1, row "Country":** "77.59%". *Paper text: "HBR records the country at birth, death, and a country representing the places where the individual flourished (we refer to this country as main country)."* |
| With a date (year of birth) | ≈ 4,239,378 | **Computation:** `7,015,353 × 60.43 %`. **Verbatim, Table 1, row "Year of birth":** "60.43%". *(HBR does not publish a combined "birth-or-death" share; year-of-birth is the closest single field. Year of death is 30.05 % — many subjects are still alive — and is dominated by the year-of-birth coverage.)* |
| With an occupation | ≈ 5,324,653 | **Computation:** `7,015,353 × 75.9 %`. **Verbatim, Table 1, row "Occupation":** "75.9%". *Paper text: "We also document the occupation by categorizing individuals into political, spiritual and intelligentsia."* |

---

## 5.  Schich et al. (2014) — *Science*

**Paper PDF:** `data/similar_databases/schich_2014/Schich et al. - 2014 - A network framework of cultural history.pdf`.
**Underlying data:** Freebase (FB) sub-dataset of the paper, plus AKL and ULAN. The migration-network analysis in Figs. 1–3 uses the FB subset because it is the only one with broad geographic coverage.

| Cell | Value | Source |
|---|---|---|
| Total individuals | 120,211 | **Verbatim:** "We also constructed a worldwide historical migration network, connecting 37,062 locations via the birth-death data of **120,211 individuals** in the FB data set from King David in 1069 BCE to Poppy Barlow in 2012 CE." *(The paper's headline figure of "more than 150,000" combines all three sources; FB is the analyzed core.)* |
| Linked to a polity / citizenship | — | Schich's data layer is **city-level birth and death locations**, not citizenship or polity. No structured polity field is published. |
| With a date | 120,211 | By construction — every FB individual in the migration network has both birth and death dates. *Verbatim:* "Notable individuals with birth and death locations, alive in a given year from 1 to 2012 CE…". |
| With an occupation | — | Occupation is only used as a stratification (e.g. "FB governance", "AKL fine arts" in Fig. 4); the paper does not report an occupation-completeness count for the FB sub-dataset. |

*(For reference, the paper also notes "death locations are under-reported (e.g., 153,000 out of 1.1 million in AKL)" — AKL has ≈ 1.1 M total entries but is artist-only and only partly used.)*

---

## 6.  Chaney (2024) — *Modern Library Holdings and Historic City Growth*

**Paper PDFs:** `data/similar_databases/chaney_2024/citiesforweb.pdf` (main) and `appendixcities.pdf` (data appendix).
**Underlying data:** built from VIAF authority clusters + 31 Islamic biographical dictionaries + Brockelmann/Sezgin/PUA. **Europe + MENA only**, authors only, dates < 1800.

| Cell | Value | Source |
|---|---|---|
| Total individuals | 537,247 | **Verbatim, appendix p. 3:** "After discarding clusters not in the European and MENA regions, clusters that do not correspond to individuals authors (e.g. those representing political dynasties or families) and those containing additional information that the author died on or after 1800 I was left with **537,247** authority clusters." |
| Linked to a polity / region | 486,179 | **Verbatim, appendix p. 3:** "When this was done, **470,189 and 15,990 unique names remained for Europe and MENA respectively**." Sum = 486,179 (region = polity-equivalent in Chaney). The narrower "assigned to one of 1,055 cities" subset is 213,894 (verbatim: "the resulting Europe/MENA dataset contains **213,894 georeferenced authors**"). |
| With a date | 537,247 | By construction — **verbatim, appendix p. 3:** "I first removed clusters that did not contain at least one numerical character in the birth or death fields, as well as those containing birth or death years after 1799." |
| With an occupation | 537,247 | All entries are **authors** by VIAF construction (single-occupation database). |

---

## Notes on what is *not* comparable

- **Cultura's unique fields** — "only in non-Western Wikipedia / catalogs", "in Wikidata + ≥ 1 catalog (no Wiki)", and overlap with Cross-Verified — depend on the per-individual Wikipedia and authority-file pivot tables built in this project (`wikimedia_links`, `identifiers`, `identifier_types`). None of the other five databases publish that join, so those rows appear in Table 1 (Cultura vs CV) only.
- **Citizenship vs. country vs. region** — these three fields are not equivalent across datasets. Cross-Verified ships a cleaned legal citizenship; Cultura attaches historical polities via Cliopatria; Pantheon 2.0 only stores birth/death country; HBR uses a "main country" derived from McEvedy's atlas; Chaney encodes Europe/MENA at the region level. We treat them as the closest "geographic anchor per individual" each database offers.
- **Date completeness** — Cultura uses an **estimated floruit period**; the others use raw birth and/or death years. The 7.5 M Cultura figure is therefore broader (it includes anyone whose century-of-activity could be inferred), not narrower.

---

*Generated alongside `notebooks/20_cultura_vs_cross_verified.ipynb` and `notebooks/tables/table2_six_databases.{csv,pdf,png}`.*
