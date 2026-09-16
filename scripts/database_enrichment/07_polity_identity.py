from urllib.parse import quote

from common import D, Enrichment, ROOT, as_json, open_database, stage

import to_duckdb as C
import to_raw as T
from write import columns_of

ENGLISH_WIKIPEDIA = "https://en.wikipedia.org/wiki/"

ENRICHMENT = Enrichment(
    reads=("PolityCliopatria.name", "PolityCliopatria.wikidata", "PolityCliopatria.type", "PolityCliopatria.wikipedia", "PolityCliopatria.from_year", "PolityCliopatria.to_year", "PolityCliopatria.area", "PolityCliopatria.geometry"),
    writes=("Polity.cliopatria_id", "Polity.name", "Polity.type", "Polity.entity", "Polity.sitelink", "Polity.territories"),
    rule="Cliopatria publishes one feature per polity per change of borders and numbers none of them, so the polities have to be told apart before anything can be counted. Two features are the same polity when they share a name and the Wikidata item Cliopatria resolved, a name it wraps in parentheses being the name inside them, and a feature with no name being no polity. The features of one polity become its territories, and cliopatria_id numbers the polities in the order the file first mentions them.",
    answers=ROOT / "cliopatria_data" / "cliopatria_V2" / "cliopatria_polities_only_v3.geojson",
)

STEPS = (
    "discard_the_nameless",
    "strip_enclosing_parentheses",
    "key_on_name_and_wikidata",
    "number_by_first_appearance",
)

IMPLEMENTATIONS = {}


def step(name):
    def keep(function):
        IMPLEMENTATIONS[name] = function
        return function
    return keep


@step("discard_the_nameless")
def discard_the_nameless(spans):
    """A feature with no name is no polity, since the name is the only identifier Cliopatria gives one."""
    return [span for span in spans if (span.name or "").strip()]


@step("strip_enclosing_parentheses")
def strip_enclosing_parentheses(spans):
    """A name Cliopatria wraps in parentheses, as it does for a polity named only as another's member, is the same polity as the name inside them."""
    for span in spans:
        name = span.name.strip()
        if name.startswith("(") and name.endswith(")"):
            span.name = name[1:-1]
        else:
            span.name = name
    return spans


@step("key_on_name_and_wikidata")
def key_on_name_and_wikidata(spans):
    """Two features are the same polity when they share both a name and a Wikidata item; a name alone keys those Cliopatria never resolved, so two unresolved polities of one name become one and two resolved ones stay apart."""
    grouped = {}
    for span in spans:
        grouped.setdefault((span.name, (span.wikidata or "").strip()), []).append(span)
    return grouped


@step("number_by_first_appearance")
def number_by_first_appearance(grouped):
    """cliopatria_id counts the polities in the order the file first mentions them, Cliopatria numbering nothing itself."""
    return {key: number for number, key in enumerate(grouped, start=1)}


assert tuple(IMPLEMENTATIONS) == STEPS, f"{tuple(IMPLEMENTATIONS)} is not {STEPS}"


def english_wikipedia(title):
    return ENGLISH_WIKIPEDIA + quote((title or "").replace(" ", "_")) if title else None


def a_polity(cliopatria_id, key, spans):
    name, wikidata = key
    first = spans[0]
    return D.Polity(
        cliopatria_id=cliopatria_id,
        name=name,
        type=first.type,
        entity=C.entity(wikidata) if wikidata else None,
        sitelink=D.Sitelink(url=english_wikipedia(first.wikipedia)) if first.wikipedia else None,
        territories=tuple(C.territory(span) for span in spans),
        field_provenance={
            "cliopatria_id": C.read_from("PolityCliopatria.name", "PolityCliopatria.wikidata"),
            "name": C.read_from("PolityCliopatria.name"),
            "type": C.read_from("PolityCliopatria.type"),
            "entity": C.read_from("PolityCliopatria.wikidata"),
            "sitelink": C.read_from("PolityCliopatria.wikipedia"),
            "territories": C.read_from(
                "PolityCliopatria.from_year", "PolityCliopatria.to_year",
                "PolityCliopatria.area", "PolityCliopatria.geometry",
            ),
        },
    )


def polities(spans):
    kept = discard_the_nameless(spans)
    named = strip_enclosing_parentheses(kept)
    grouped = key_on_name_and_wikidata(named)
    numbered = number_by_first_appearance(grouped)
    return [a_polity(numbered[key], key, group) for key, group in grouped.items()]


def main():
    ENRICHMENT.announce()
    print("polity identity, step by step:")
    for position, name in enumerate(STEPS, start=1):
        print(f"   {position}. {name}")
    print()

    spans = T.polities()
    built = polities(spans)
    resolved = sum(1 for polity in built if polity.entity)
    territories = sum(len(polity.territories) for polity in built)
    print(f"{len(spans):,} features become {len(built):,} polities carrying {territories:,} territories, {resolved:,} of them with a Wikidata item")

    connection = open_database()
    stage(connection, "assigned", columns_of(D.Polity), [as_json(polity) for polity in built])
    connection.execute("CREATE OR REPLACE TABLE polity AS SELECT * FROM assigned")
    print(f"\npolity holds {connection.execute('SELECT count(*) FROM polity').fetchone()[0]:,} rows")
    connection.close()


if __name__ == "__main__":
    main()
