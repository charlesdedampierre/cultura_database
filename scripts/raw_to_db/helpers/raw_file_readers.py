from pathlib import Path

import ijson

ROOT = Path(__file__).resolve().parents[3]
WIKIDATA = ROOT / "data" / "raw_data_from_wikidata"
EXTRACTION_V2 = WIKIDATA / "wikidata_extraction_scripts_v2"

INDIVIDUAL_IDS = WIKIDATA / "all_human_ids.json"
LABEL = WIKIDATA / "all_human_names.json"
DESCRIPTION = WIKIDATA / "all_human_descriptions.json"
DATE_OF_BIRTH = WIKIDATA / "all_human_birthdates.json"
DATE_OF_BIRTH_PRECISION = WIKIDATA / "all_human_birthdate_precision.json"
DATE_OF_DEATH = WIKIDATA / "all_human_deathdates.json"
DATE_OF_DEATH_PRECISION = WIKIDATA / "all_human_deathdate_precision.json"
FLORUIT = WIKIDATA / "all_human_floruit_raw_dates.json"
FLORUIT_PRECISION = WIKIDATA / "all_human_floruit_raw_precision.json"
PLACE_OF_BIRTH = WIKIDATA / "all_human_birthplaces.json"
PLACE_OF_DEATH = WIKIDATA / "all_human_deathplaces.json"
SEX_OR_GENDER = WIKIDATA / "all_human_genders.json"
OCCUPATION = WIKIDATA / "all_human_occupations.json"
COUNTRY_OF_CITIZENSHIP = WIKIDATA / "all_human_nationalities.json"
WRITING_LANGUAGE = WIKIDATA / "all_human_writing_languages.json"
EXTERNAL_ID = WIKIDATA / "all_human_identifiers.json"
SITELINK = WIKIDATA / "all_human_sitelinks.json"
WORK = WIKIDATA / "all_human_works.json"

PLACE_LOCATION = WIKIDATA / "place_locations.json"
PLACE_INSTANCE_OF = WIKIDATA / "city_entity_types.json"
PLACE_INCEPTION = EXTRACTION_V2 / "place_inception.json"
PLACE_DISSOLUTION = EXTRACTION_V2 / "place_dissolution.json"

COUNTRY_LOCATION = WIKIDATA / "nationality_locations.json"
COUNTRY_OF_PLACE = WIKIDATA / "nationality_countries.json"
COUNTRY_MODERN = WIKIDATA / "modern_countries.json"
COUNTRY_SITELINK = WIKIDATA / "nationality_sitelinks.json"

OCCUPATION_LABEL = WIKIDATA / "occupation_labels.json"

WORK_LABEL = WIKIDATA / "work_labels.json"
WORK_INSTANCE_OF = EXTRACTION_V2 / "work_instance_of.json"
WORK_INCEPTION = EXTRACTION_V2 / "work_inception.json"
WORK_PUBLICATION_DATE = EXTRACTION_V2 / "work_publication.json"

EXTERNAL_ID_PROPERTY = WIKIDATA / "all_external_id_properties.json"
EXTERNAL_ID_PROPERTY_METADATA = WIKIDATA / "identifier_types_backup_20260502_135617.json"

PROPERTY = ROOT / "scripts" / "_one_off" / "properties.json"
POLITY = ROOT / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson"


def pairs(path):
    with open(path, "rb") as handle:
        yield from ijson.kvitems(handle, "", use_float=True)


def items(path, prefix):
    with open(path, "rb") as handle:
        yield from ijson.items(handle, prefix, use_float=True)


def pairs_until_truncated(path):
    try:
        yield from pairs(path)
    except ijson.common.IncompleteJSONError:
        return


def subset(path, keys, reader=pairs):
    wanted = set(keys)
    found = {}
    for key, value in reader(path):
        if key in wanted:
            found[key] = value
            if len(found) == len(wanted):
                break
    return found


def whole(path):
    return dict(pairs(path))


def literal(value):
    if value is None:
        return None
    text = str(value)
    if text.startswith('"') and '"@' in text:
        return text[1 : text.rindex('"@')]
    return text
