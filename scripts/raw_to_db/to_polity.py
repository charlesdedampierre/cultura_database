import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "datamodels"))

import datamodel_in_duckdb as D
import to_duckdb as C

ENGLISH_WIKIPEDIA = "https://en.wikipedia.org/wiki/"

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


def announce(spans, built):
    print("polity identity, step by step:")
    for position, name in enumerate(STEPS, start=1):
        print(f"   {position}. {name}")
    resolved = sum(1 for polity in built if polity.entity)
    territories = sum(len(polity.territories) for polity in built)
    print(f"\n{len(spans):,} features become {len(built):,} polities carrying {territories:,} territories, {resolved:,} of them with a Wikidata item")
