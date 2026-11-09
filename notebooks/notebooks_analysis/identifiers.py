"""Which external-identifier properties identify people.

A property is left out when Wikidata types it (P31) as an online-account handle (X, Instagram, YouTube...),
or only as an identifier of works, places, organizations, films, books, lexemes or news topics, with no
type about people. Classes come from scripts/2-wikidata_extraction_scripts/29_extract_identifier_property_types.py."""
import json
from pathlib import Path

TYPES_PATH = Path(__file__).resolve().parents[2] / 'data' / 'raw_data_from_wikidata' / 'wikidata_extraction_scripts_v2' / 'identifier_property_types.json'

ONLINE_ACCOUNT = {'Q105388954'}
NOT_A_PERSON = {
    'Q19833377',   # authority control for works
    'Q19829908',   # authority control for places
    'Q21745557',   # organizations
    'Q29542094',   # films
    'Q29547399',   # books
    'Q54254515',   # lexemes
    'Q56216056',   # lexicographical entities
    'Q106035765',  # businesses
    'Q105946994',  # news website topics
}
ABOUT_PEOPLE = {
    'Q19595382',   # authority control for people
    'Q93433126',   # politicians
    'Q55653847',   # artists
    'Q55650689',   # writers
    'Q66712599',   # musicians
    'Q22964274',   # film industry
    'Q93436926',   # sports people
    'Q107738583',  # sports athletes
    'Q107738007',  # association football players
    'Q107738607',  # basketball players
    'Q71866636',   # video game professionals
    'Q97584729',   # biographical dictionaries
    'Q55452870',   # encyclopedias
    'Q106646822',  # subject dictionaries
}


def identifies_people(classes):
    classes = set(classes)
    if classes & ONLINE_ACCOUNT:
        return False
    return not (classes & NOT_A_PERSON) or bool(classes & ABOUT_PEOPLE)


def person_identifier_pids():
    types = json.loads(TYPES_PATH.read_text())
    return sorted(pid for pid, classes in types.items() if identifies_people(classes))
