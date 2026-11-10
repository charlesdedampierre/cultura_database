"""Write the field documentation of the released files from the datamodels: docs/database.md for the tables of
cultura_database_V4.duckdb (datamodel_in_duckdb.TABLES) and docs/csv.md for the columns of cultura_database_V4.csv
(datamodel_export.ExportedIndividualCSV). Rerun after any change to the datamodels."""

import types
import typing
from pathlib import Path

from pydantic import BaseModel

import datamodel_export
import datamodel_in_duckdb

DOCS = Path(__file__).resolve().parents[2] / "docs"


def nested_models(annotation):
    """The BaseModel classes inside a field annotation (through lists, tuples and optionals)."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return [model for argument in typing.get_args(annotation) for model in nested_models(argument)]


def type_name(annotation):
    if isinstance(annotation, type):
        return annotation.__name__
    origin = typing.get_origin(annotation)
    arguments = [argument for argument in typing.get_args(annotation) if argument is not type(None) and argument is not Ellipsis]
    if origin in (typing.Union, types.UnionType):
        return " or ".join(type_name(argument) for argument in arguments)
    if origin in (tuple, list):
        return f"list of {type_name(arguments[0])}"
    if origin is typing.Literal:
        return "text: " + ", ".join(f"'{argument}'" for argument in typing.get_args(annotation))
    return str(annotation).replace("typing.", "")


def field_table(model):
    rows = ["| Field | Type | Description |", "| --- | --- | --- |"]
    for name, field in model.model_fields.items():
        description = (field.description or "").replace("|", "\\|").replace("\n", " ")
        rows.append(f"| `{name}` | {type_name(field.annotation).replace('|', 'or')} | {description} |")
    return "\n".join(rows)


def database_page():
    sections = ["# Tables of cultura_database_V4.duckdb", "",
                "One DuckDB file, opened read-only with `duckdb.connect('cultura_database_V4.duckdb', read_only=True)`. "
                "Individuals are joined across tables on their Wikidata identifier (`entity.qid`, or `qid` in the link tables). "
                "Nested types used by several tables are described once, under Nested types.", ""]
    nested = {}
    for table, model in datamodel_in_duckdb.TABLES.items():
        sections += [f"## `{table}`", ""] + ([model.__doc__.strip(), ""] if model.__doc__ else []) + [field_table(model), ""]
        todo = [inner for field in model.model_fields.values() for inner in nested_models(field.annotation)]
        while todo:
            inner = todo.pop()
            if inner.__name__ not in nested and inner not in datamodel_in_duckdb.TABLES.values():
                nested[inner.__name__] = inner
                todo += [deeper for field in inner.model_fields.values() for deeper in nested_models(field.annotation)]
    sections += ["## Nested types", ""]
    for name in sorted(nested):
        sections += [f"### {name}", "", field_table(nested[name]), ""]
    return "\n".join(sections)


def csv_page():
    return "\n".join([
        "# Columns of cultura_database_V4.csv", "",
        "One row per individual, comma-separated with a header. Lists are separated by ' | '. "
        "Years before the common era are negative; a date known only to the century or millennium is written as its label ('4th BC').", "",
        field_table(datamodel_export.ExportedIndividualCSV), "",
    ])


def main():
    DOCS.mkdir(exist_ok=True)
    (DOCS / "database.md").write_text(database_page())
    (DOCS / "csv.md").write_text(csv_page())
    print(f"wrote {DOCS / 'database.md'} and {DOCS / 'csv.md'}")


if __name__ == "__main__":
    main()
