"""Mark Wikipedia editions and present-day states as Western or not, give each state its continent and each polity its cultural world."""

import json
import time

from tqdm import tqdm

from common import Enrichment, R, ai_run, as_json, open_database, provenance_column

# The lists were drawn up by Claude, Anthropic's language model, for this project, and are saved with the model's name in data/ai_outputs/.
# They are decisions, not facts any source states.
ANSWERS, RUN = ai_run("western_continents_and_worlds", R.WesternAndWorldsRun)
WESTERN_WIKIPEDIA_LANGUAGES = RUN.western_wikipedia_languages
NON_WESTERN_WIKIPEDIA_LANGUAGES = RUN.non_western_wikipedia_languages
WESTERN_COUNTRIES = RUN.western_countries
LATIN_AMERICAN_COUNTRIES = RUN.latin_american_countries
MIDDLE_EAST_COUNTRIES = RUN.middle_east_countries
WORLDS = RUN.worlds

EDITION_CODE = r"^https://([^.]+)\.wikipedia\.org$"

SITELINK = Enrichment(
    reads=("Sitelink.url",),
    writes=("Sitelink.is_western",),
    rule="The language code of a Wikipedia edition read against WESTERN_WIKIPEDIA_LANGUAGES and NON_WESTERN_WIKIPEDIA_LANGUAGES, two lists Claude, Anthropic's language model, drew up for this project: True on the first, False on the second, empty for codes on neither list and for every edition that is not a Wikipedia.",
    answers=ANSWERS,
    model_name=RUN.model_name,
)

STATE = Enrichment(
    reads=("PresentDayState.name", "PresentDayState.continent"),
    writes=("PresentDayState.continent", "PresentDayState.is_western"),
    rule="The state's name read against three lists Claude, Anthropic's language model, drew up for this project: continent becomes 'Latin America' for a state in LATIN_AMERICAN_COUNTRIES and 'Middle East' for one in MIDDLE_EAST_COUNTRIES, and stays Wikidata's otherwise; is_western is True for a state in WESTERN_COUNTRIES, False for any other named state, empty where there is no name.",
    answers=ANSWERS,
    model_name=RUN.model_name,
)

WORLD = Enrichment(
    reads=("Polity.name",),
    writes=("Polity.world",),
    rule="The polity's name looked up in WORLDS, a grouping of polity names into cultural worlds Claude, Anthropic's language model, drew up for this project. Empty for a polity in no world; two entries for one in two, as the Mughal Empire is.",
    answers=ANSWERS,
    model_name=RUN.model_name,
)


def text(value):
    return "'" + value.replace("'", "''") + "'"


def text_in(values):
    return "(" + ", ".join(text(value) for value in values) + ")"


def provenance(enrichment):
    return f"{text(json.dumps(as_json(enrichment.provenance())))}::JSON::{provenance_column()}"


def worlds_of(column):
    parts = [f"CASE WHEN {column} IN {text_in(polities)} THEN [{text(world)}] ELSE []::VARCHAR[] END" for world, polities in WORLDS.items()]
    return "list_concat(" + ", ".join(parts) + ")"


def in_a_world(column):
    return f"coalesce({column} IN {text_in(sorted({name for polities in WORLDS.values() for name in polities}))}, false)"


MACROS = f"""
CREATE OR REPLACE TEMP MACRO state_fix(s) AS CASE WHEN s IS NULL THEN NULL ELSE struct_update(s,
    continent := CASE WHEN s.name IN {text_in(LATIN_AMERICAN_COUNTRIES)} THEN 'Latin America'
                      WHEN s.name IN {text_in(MIDDLE_EAST_COUNTRIES)} THEN 'Middle East'
                      ELSE s.continent END,
    is_western := CASE WHEN s.name IS NULL THEN NULL ELSE s.name IN {text_in(WESTERN_COUNTRIES)} END) END;

CREATE OR REPLACE TEMP MACRO place_fix(p) AS CASE WHEN p IS NULL THEN NULL ELSE struct_update(p,
    present_day_state := state_fix(p.present_day_state),
    field_provenance := CASE WHEN p.present_day_state IS NULL THEN p.field_provenance
                             ELSE map_concat(p.field_provenance, MAP {{'present_day_state': {provenance(STATE)}}}) END) END;

CREATE OR REPLACE TEMP MACRO territory_fix(t) AS struct_update(t,
    present_day_states := list_transform(t.present_day_states, s -> state_fix(s)));

CREATE OR REPLACE TEMP MACRO polity_fix(p) AS CASE WHEN p IS NULL THEN NULL ELSE struct_update(p,
    territories := list_transform(p.territories, t -> territory_fix(t)),
    world := {worlds_of('p.name')},
    field_provenance := CASE WHEN {in_a_world('p.name')} THEN map_concat(p.field_provenance, MAP {{'world': {provenance(WORLD)}}})
                             ELSE p.field_provenance END) END;
"""

PRESENT_DAY_STATES = (
    ("place", "present_day_state", "state_fix(present_day_state)"),
    ("polity", "territories", "list_transform(territories, t -> territory_fix(t))"),
    ("individual", "place_of_birth", "place_fix(place_of_birth)"),
    ("individual", "place_of_death", "place_fix(place_of_death)"),
    ("individual", "country_of_citizenship", "list_transform(country_of_citizenship, c -> place_fix(c))"),
)


def fill_sitelink(connection):
    connection.execute(f"""
        CREATE OR REPLACE TABLE sitelink AS
        SELECT sitelink.* REPLACE (
            CASE WHEN regexp_extract(url, '{EDITION_CODE}', 1) IN {text_in(WESTERN_WIKIPEDIA_LANGUAGES)} THEN true
                 WHEN regexp_extract(url, '{EDITION_CODE}', 1) IN {text_in(NON_WESTERN_WIKIPEDIA_LANGUAGES)} THEN false END AS is_western,
            map_concat(field_provenance, MAP {{'is_western': {provenance(SITELINK)}}}) AS field_provenance
        )
        FROM sitelink
    """)


def fill_polity_world(connection):
    connection.execute("ALTER TABLE polity ADD COLUMN IF NOT EXISTS world VARCHAR[]")
    connection.execute(f"""
        UPDATE polity SET
            world = {worlds_of('name')},
            field_provenance = CASE WHEN {in_a_world('name')} THEN map_concat(field_provenance, MAP {{'world': {provenance(WORLD)}}})
                                    ELSE field_provenance END
    """)


def fill_present_day_states(connection):
    """ALTER ... TYPE, so that a database built before is_western existed gains it as well."""
    for table, column, expression in tqdm(PRESENT_DAY_STATES, desc="present-day states", unit=" column"):
        new_type = connection.execute(f'SELECT typeof({expression}) FROM "{table}" LIMIT 1').fetchone()[0]
        connection.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE {new_type} USING {expression}')


def fill_nested_polities(connection):
    """The polities already matched to individuals, for a database whose 08 ran before this step. The table is
    rewritten rather than altered, because ALTER ... USING cannot bind the nested lambdas."""
    connection.execute("""CREATE TABLE individual_enriched_new AS SELECT * REPLACE (
        list_transform(polity, m -> struct_update(m, polity := polity_fix(m.polity))) AS polity) FROM individual_enriched""")
    before, after = (connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("individual_enriched", "individual_enriched_new"))
    assert before == after, f"individual_enriched: {before:,} rows became {after:,}"
    connection.execute("DROP TABLE individual_enriched")
    connection.execute("ALTER TABLE individual_enriched_new RENAME TO individual_enriched")


def report(connection):
    print("\neditions by is_western:")
    print(connection.sql("SELECT is_western, count(*) AS editions FROM sitelink GROUP BY 1 ORDER BY 1"))
    print("present-day states of places, by continent and is_western:")
    print(connection.sql("SELECT present_day_state.continent, present_day_state.is_western, count(*) AS places FROM place WHERE present_day_state IS NOT NULL GROUP BY ALL ORDER BY 3 DESC"))
    print("polities by world:")
    print(connection.sql("SELECT world, count(*) AS polities FROM (SELECT unnest(world) AS world FROM polity) GROUP BY 1 ORDER BY 2 DESC"))
    missing = [name for polities in WORLDS.values() for name in polities if not connection.execute("SELECT count(*) FROM polity WHERE name = ?", [name]).fetchone()[0]]
    print(f"names in WORLDS that match no polity: {missing or 'none'}")


def main():
    for enrichment in (SITELINK, STATE, WORLD):
        enrichment.announce()
    connection = open_database()
    connection.execute("SET enable_progress_bar = true")
    connection.execute(MACROS)
    for step in tqdm((fill_sitelink, fill_polity_world, fill_present_day_states, fill_nested_polities), desc="western, continents and worlds", unit=" step"):
        started = time.time()
        connection.execute("BEGIN")
        step(connection)
        connection.execute("COMMIT")
        print(f"   {step.__name__} done in {time.time() - started:.0f} s")
    connection.execute("CHECKPOINT")
    report(connection)
    connection.close()


if __name__ == "__main__":
    main()
