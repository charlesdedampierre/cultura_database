import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers
import datamodel_in_duckdb
import json_to_raw_models
import raw_to_duckdb_models
from duckdb_table_writer import Table

STEP = "02 polities"
ENGLISH_WIKIPEDIA = "https://en.wikipedia.org/wiki/"

STEPS = (
    "discard_the_nameless",
    "strip_enclosing_parentheses",
    "key_on_name_and_wikidata",
    "number_by_first_appearance",
)


def discard_the_nameless(spans):
    return [span for span in spans if (span.name or "").strip()]


def strip_enclosing_parentheses(spans):
    for span in spans:
        name = span.name.strip()
        if name.startswith("(") and name.endswith(")"):
            span.name = name[1:-1]
        else:
            span.name = name
    return spans


def key_on_name_and_wikidata(spans):
    grouped = {}
    for span in spans:
        grouped.setdefault((span.name, (span.wikidata or "").strip()), []).append(span)
    return grouped


def number_by_first_appearance(grouped):
    return {key: number for number, key in enumerate(grouped, start=1)}


def english_wikipedia(title):
    return ENGLISH_WIKIPEDIA + quote((title or "").replace(" ", "_")) if title else None


def existence_wikidata(found):
    date = raw_to_duckdb_models.date
    return datamodel_in_duckdb.ExistencePeriod(
        inception=date(found.inception, found.inception_precision, "PolityWikidata.inception", "PolityWikidata.inception_precision"),
        dissolution=date(found.dissolution, found.dissolution_precision, "PolityWikidata.dissolution", "PolityWikidata.dissolution_precision"),
    )


def a_polity(cliopatria_id, key, spans, existence):
    name, wikidata = key
    first = spans[0]
    read_from = raw_to_duckdb_models.read_from
    return datamodel_in_duckdb.Polity(
        cliopatria_id=cliopatria_id,
        name=name,
        entity=raw_to_duckdb_models.entity(wikidata) if wikidata else None,
        existence_wikidata=existence_wikidata(existence[wikidata]) if wikidata in existence else None,
        sitelink=datamodel_in_duckdb.Sitelink(url=english_wikipedia(first.wikipedia)) if first.wikipedia else None,
        territories=tuple(raw_to_duckdb_models.territory(span) for span in spans),
        field_provenance={
            "cliopatria_id": read_from("PolityCliopatria.name", "PolityCliopatria.wikidata"),
            "name": read_from("PolityCliopatria.name"),
            "entity": read_from("PolityCliopatria.wikidata"),
            "existence_wikidata": read_from("PolityWikidata.inception", "PolityWikidata.dissolution"),
            "sitelink": read_from("PolityCliopatria.wikipedia"),
            "territories": read_from(
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
    existence = json_to_raw_models.polity_existence({wikidata for _, wikidata in grouped if wikidata})
    return [a_polity(numbered[key], key, group, existence) for key, group in grouped.items()]


def announce(spans, built):
    print("polity identity, step by step:")
    for position, name in enumerate(STEPS, start=1):
        print(f"   {position}. {name}")
    resolved = sum(1 for polity in built if polity.entity)
    territories = sum(len(polity.territories) for polity in built)
    print(f"\n{len(spans):,} features become {len(built):,} polities carrying {territories:,} territories, {resolved:,} of them with a Wikidata item")


def main():
    connection = build_helpers.open_database()
    spans = json_to_raw_models.polities()
    build_helpers.report(STEP, f"{len(spans):,} Cliopatria features")

    built = build_helpers.limited(polities(spans))
    announce(spans, built)

    with Table(connection, "polity", datamodel_in_duckdb.Polity, batch=200) as table:
        table.extend(built)

    build_helpers.done(STEP, [table])
    connection.close()


if __name__ == "__main__":
    main()
