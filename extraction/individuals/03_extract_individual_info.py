"""Extract biographical info for each individual from Wikidata.

Queries: gender (P21), birthdate (P569), deathdate (P570), floruit (P1317),
nationality (P27), birthcity (P19), deathcity (P20), writing language (P6886),
position held (P39), social classification (P3716), time period (P2348),
manner of death (P1196), field of work (P101), VIAF (P214), sitelinks, description.
Saves to data/extracted/individuals/individual_info.json.
"""

import json
import os
import sys
from multiprocessing import Pool

from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from wikidata_api import sparql_query

OUTPUT_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "extracted", "individuals"
)
NUM_WORKERS = 8


def get_info(wiki_id: str) -> dict | None:
    """Get biographical info for a single individual."""
    query = """
    SELECT ?genderLabel ?birthdateLabel ?deathdateLabel ?floruitLabel
           ?nationality ?nationalityLabel
           ?birthcity ?birthcityLabel
           ?deathcity ?deathcityLabel
           ?writingLang ?writingLangLabel
           ?position ?positionLabel
           ?socialClass ?socialClassLabel
           ?timePeriod ?timePeriodLabel
           ?mannerOfDeath ?mannerOfDeathLabel
           ?fieldOfWork ?fieldOfWorkLabel
           ?viaf ?description (LANG(?description) AS ?descLang)
           (COUNT(DISTINCT ?sitelink) AS ?sitelinks)
    WHERE {
      OPTIONAL { wd:%s schema:description ?description. }
      OPTIONAL { wd:%s wdt:P21 ?gender. }
      OPTIONAL { wd:%s wdt:P569 ?birthdate. }
      OPTIONAL { wd:%s wdt:P570 ?deathdate. }
      OPTIONAL { wd:%s wdt:P1317 ?floruit. }
      OPTIONAL { wd:%s wdt:P27 ?nationality. }
      OPTIONAL { wd:%s wdt:P19 ?birthcity. }
      OPTIONAL { wd:%s wdt:P20 ?deathcity. }
      OPTIONAL { wd:%s wdt:P6886 ?writingLang. }
      OPTIONAL { wd:%s wdt:P39 ?position. }
      OPTIONAL { wd:%s wdt:P3716 ?socialClass. }
      OPTIONAL { wd:%s wdt:P2348 ?timePeriod. }
      OPTIONAL { wd:%s wdt:P1196 ?mannerOfDeath. }
      OPTIONAL { wd:%s wdt:P101 ?fieldOfWork. }
      OPTIONAL { wd:%s wdt:P214 ?viaf. }
      OPTIONAL { ?sitelink schema:about wd:%s. }
      SERVICE wikibase:label { bd:serviceParam wikibase:language 'en'. }
    }
    GROUP BY ?genderLabel ?birthdateLabel ?deathdateLabel ?floruitLabel
             ?nationality ?nationalityLabel
             ?birthcity ?birthcityLabel
             ?deathcity ?deathcityLabel
             ?writingLang ?writingLangLabel
             ?position ?positionLabel
             ?socialClass ?socialClassLabel
             ?timePeriod ?timePeriodLabel
             ?mannerOfDeath ?mannerOfDeathLabel
             ?fieldOfWork ?fieldOfWorkLabel
             ?viaf ?description ?descLang
    """ % tuple(
        [wiki_id] * 16
    )

    try:
        rows = sparql_query(query)
        if not rows:
            return None

        # Collect all values (there may be multiple rows for multi-valued properties)
        genders = set()
        birthdates = set()
        deathdates = set()
        floruits = set()
        nationalities = []
        birthcities = []
        deathcities = []
        writing_languages = []
        positions = []
        social_classes = []
        time_periods = []
        manners_of_death = []
        fields_of_work = []
        viaf_ids = set()
        sitelinks_count = 0
        descriptions = {}

        for row in rows:
            if row.get("genderLabel"):
                genders.add(row["genderLabel"])
            if row.get("birthdateLabel"):
                birthdates.add(row["birthdateLabel"])
            if row.get("deathdateLabel"):
                deathdates.add(row["deathdateLabel"])
            if row.get("floruitLabel"):
                floruits.add(row["floruitLabel"])
            if row.get("viaf"):
                viaf_ids.add(row["viaf"])
            if row.get("sitelinks"):
                sitelinks_count = max(sitelinks_count, int(row["sitelinks"]))
            if row.get("description"):
                lang = row.get("descLang", "unknown")
                descriptions[lang] = row["description"]
            if row.get("nationality"):
                nat_id = row["nationality"].split("/")[-1]
                nationalities.append(
                    {"wikidata_id": nat_id, "name": row.get("nationalityLabel", "")}
                )
            if row.get("birthcity"):
                bc_id = row["birthcity"].split("/")[-1]
                birthcities.append(
                    {"wikidata_id": bc_id, "name": row.get("birthcityLabel", "")}
                )
            if row.get("deathcity"):
                dc_id = row["deathcity"].split("/")[-1]
                deathcities.append(
                    {"wikidata_id": dc_id, "name": row.get("deathcityLabel", "")}
                )
            if row.get("writingLang"):
                wl_id = row["writingLang"].split("/")[-1]
                writing_languages.append(
                    {"wikidata_id": wl_id, "name": row.get("writingLangLabel", "")}
                )
            if row.get("position"):
                pos_id = row["position"].split("/")[-1]
                positions.append(
                    {"wikidata_id": pos_id, "name": row.get("positionLabel", "")}
                )
            if row.get("socialClass"):
                sc_id = row["socialClass"].split("/")[-1]
                social_classes.append(
                    {"wikidata_id": sc_id, "name": row.get("socialClassLabel", "")}
                )
            if row.get("timePeriod"):
                tp_id = row["timePeriod"].split("/")[-1]
                time_periods.append(
                    {"wikidata_id": tp_id, "name": row.get("timePeriodLabel", "")}
                )
            if row.get("mannerOfDeath"):
                mod_id = row["mannerOfDeath"].split("/")[-1]
                manners_of_death.append(
                    {"wikidata_id": mod_id, "name": row.get("mannerOfDeathLabel", "")}
                )
            if row.get("fieldOfWork"):
                fow_id = row["fieldOfWork"].split("/")[-1]
                fields_of_work.append(
                    {"wikidata_id": fow_id, "name": row.get("fieldOfWorkLabel", "")}
                )

        # Deduplicate helper
        def dedupe(items):
            seen = set()
            result = []
            for item in items:
                if item["wikidata_id"] not in seen:
                    seen.add(item["wikidata_id"])
                    result.append(item)
            return result or None

        return {
            "wikidata_id": wiki_id,
            "descriptions": descriptions or None,
            "gender": list(genders) if genders else None,
            "birthdate": list(birthdates)[0] if birthdates else None,
            "deathdate": list(deathdates)[0] if deathdates else None,
            "floruit": list(floruits)[0] if floruits else None,
            "nationalities": dedupe(nationalities),
            "birthcities": dedupe(birthcities),
            "deathcities": dedupe(deathcities),
            "writing_languages": dedupe(writing_languages),
            "positions_held": dedupe(positions),
            "social_classifications": dedupe(social_classes),
            "time_periods": dedupe(time_periods),
            "manners_of_death": dedupe(manners_of_death),
            "fields_of_work": dedupe(fields_of_work),
            "viaf": list(viaf_ids)[0] if viaf_ids else None,
            "sitelinks": sitelinks_count,
        }
    except Exception as e:
        print(f"  Error for {wiki_id}: {e}")
        return None


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    individuals_path = os.path.join(OUTPUT_DIR, "individuals.json")
    with open(individuals_path) as f:
        individuals = json.load(f)

    wiki_ids = [ind["wikidata_id"] for ind in individuals]
    print(f"Extracting info for {len(wiki_ids)} individuals...")

    with Pool(NUM_WORKERS) as p:
        results = list(
            tqdm(
                p.imap(get_info, wiki_ids),
                total=len(wiki_ids),
                desc="Individual info",
            )
        )

    results = [r for r in results if r is not None]

    output_path = os.path.join(OUTPUT_DIR, "individual_info.json")
    with open(output_path, "w") as f:
        json.dump(results, f)

    print(f"Saved info for {len(results)} individuals to {output_path}")


if __name__ == "__main__":
    main()
