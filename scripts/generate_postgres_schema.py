"""Generate the PostgreSQL schema from datamodel.py.

The model is nested; PostgreSQL is relational. One rule per construct:

    Information[T]      two columns — the value, and a foreign key to `source`
    Source + its four   one `source` table, deduplicated, with a `kind` column
    a nested model      its own table, once, reached by a foreign key
    tuple[X, ...]       a join table, with an `ordinal` so the order survives

Every model becomes exactly one table, so a place is a `location` row whether it
is a birthplace, a deathplace or a citizenship — which is what makes the result
navigable: a tool that follows foreign keys can walk the whole model.

    python scripts/generate_postgres_schema.py > schema.sql
"""

import sys
import types
from pathlib import Path
from typing import Literal, Union, get_args, get_origin

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datamodel as dm
from pydantic import BaseModel

SOURCES = (dm.Wikidata, dm.Derived, dm.AIAnswer)

SQL_TYPE = {str: "text", int: "bigint", float: "double precision", bool: "boolean", dm.date: "date"}

# a table may only reference one already created, so the order is the dependency order
MODELS = [dm.Date, dm.DateRange, dm.WikipediaLink, dm.Polity, dm.Location, dm.Occupation, dm.Identifier, dm.Notability, dm.Floruit, dm.Individual, dm.Work]


def table_name(model: type[BaseModel]) -> str:
    return "".join(("_" if ch.isupper() and i else "") + ch.lower() for i, ch in enumerate(model.__name__))


def unwrap(annotation) -> tuple[object, bool]:
    """Strip `| None`; return (inner type, whether it was a tuple)."""
    if get_origin(annotation) in (Union, types.UnionType):
        annotation = [a for a in get_args(annotation) if a is not type(None)][0]
    if get_origin(annotation) is tuple:
        return get_args(annotation)[0], True
    return annotation, False


def is_model(t) -> bool:
    return isinstance(t, type) and issubclass(t, BaseModel)


def value_type(_information: type[BaseModel]) -> str:
    """An Information holds any scalar, so the column takes the widest of them."""
    return "text"


def ddl() -> str:
    # public, because several tools assume it and a second schema buys nothing here
    out = ["-- Generated from datamodel.py by scripts/generate_postgres_schema.py — do not edit by hand.", "",
           "drop schema if exists public cascade;", "create schema public;", "set search_path to public;", ""]

    # where every value in the database points
    cols = {"name": "text not null", "date_of_extraction": "date not null"}  # `name` is the model's own discriminator
    for src in SOURCES:
        for name, field in src.model_fields.items():
            if name in ("name", "date_of_extraction"):  # already seeded, and `name` must stay not null
                continue
            inner, is_tuple = unwrap(field.annotation)
            cols[name] = "text[]" if is_tuple else SQL_TYPE.get(inner, "text")
    out += ["create table source (", "    id bigserial primary key,"]
    out += [f"    {n} {t}," for n, t in cols.items()]
    out += [f"    constraint source_is_one_of_the_three check (name in ({', '.join(repr(s.__name__) for s in SOURCES)})),",
            "    -- and each shape must carry what that shape requires",
            "    constraint wikidata_names_an_item_or_a_property check (name <> 'Wikidata' or entity_qid is not null or property_id is not null),",
            "    constraint derived_names_its_inputs_and_rule check (name <> 'Derived' or (derived_from is not null and rule is not null)),",
            "    constraint ai_names_its_model_and_prompt check (name <> 'AIAnswer' or (model is not null and prompt is not null))",
            ");", ""]

    joins = []
    for model in MODELS:
        body, table = ["    pk bigserial primary key"], table_name(model)
        for name, field in model.model_fields.items():
            inner, is_tuple = unwrap(field.annotation)
            if is_model(inner) and issubclass(inner, dm.Information):
                body.append(f"    {name} {value_type(inner)}")
                body.append(f"    {name}_source bigint references source(id)")
            elif is_model(inner) and issubclass(inner, dm.Source):
                # a field typed as a source — a row's Wikidata identity — is a source row
                body.append(f"    {name} bigint references source(id)")
            elif is_model(inner) and is_tuple:
                joins.append((table, name, table_name(inner)))
            elif is_model(inner):
                body.append(f"    {name}_pk bigint references {table_name(inner)}(pk)")
            else:
                body.append(f"    {name} {SQL_TYPE.get(inner, 'text')}")
        out += [f"create table {table} (", ",\n".join(body), ");", ""]

    for parent, name, child in joins:
        out += [f"-- {parent}.{name}: one row per entry, ordinal keeps the order",
                f"create table {parent}_{name} (",
                f"    {parent}_pk bigint not null references {parent}(pk) on delete cascade,",
                "    ordinal integer not null,",
                f"    {child}_pk bigint not null references {child}(pk),",
                f"    primary key ({parent}_pk, ordinal)",
                ");", ""]

    out += ["create index on source (name);", "create index on source (property);",
            "create index on individual (id);", "create index on location (id);", ""]
    return "\n".join(out)


def demo() -> None:
    sql = ddl()
    assert "create table source (" in sql, "every value needs somewhere to point"
    assert "create table individual (" in sql and "create table work (" in sql, "the two roots are tables"
    assert "    id text,\n    id_source bigint references source(id)" in sql, "an Information is a value and a source"
    assert "birthplace_pk bigint references location(pk)" in sql, "a nested model is reached by a foreign key"
    assert sql.count("create table location (") == 1, "a place is one table, whatever role it plays"
    assert "create table individual_birthdates (" in sql and "ordinal integer not null" in sql, "a tuple is a join table, in order"
    assert "derived_names_its_inputs_and_rule" in sql, "what Pydantic demands, the database demands"
    assert "wikidata_entity bigint references source(id)" in sql, "a field typed as a source is a source row"
    print(sql)
    print(f"-- {sql.count('create table ')} tables, {sql.count('references ')} foreign keys", file=sys.stderr)


if __name__ == "__main__":
    demo()
