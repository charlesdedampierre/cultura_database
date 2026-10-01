import json
import types
import typing
from datetime import date as date_type

from pydantic import BaseModel

SCALARS = {str: "VARCHAR", int: "BIGINT", float: "DOUBLE", bool: "BOOLEAN"}


def duck_type(annotation, seen=()):
    if annotation is date_type:
        return "DATE"
    if annotation in SCALARS:
        return SCALARS[annotation]
    origin = typing.get_origin(annotation)
    arguments = typing.get_args(annotation)
    if origin in (types.UnionType, typing.Union):
        return duck_type([a for a in arguments if a is not type(None)][0], seen)
    if origin is tuple:
        return f"{duck_type(arguments[0], seen)}[]"
    if origin is dict:
        return f"MAP(VARCHAR, {duck_type(arguments[1], seen)})"
    if origin is typing.Literal:
        return "VARCHAR"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        if annotation in seen:
            return "STRUCT(cliopatria_id BIGINT, name VARCHAR)"
        fields = ", ".join(f'"{name}" {duck_type(field.annotation, seen + (annotation,))}' for name, field in annotation.model_fields.items())
        return f"STRUCT({fields})"
    raise TypeError(annotation)


def columns_of(model):
    return {name: duck_type(field.annotation) for name, field in model.model_fields.items()}


def write_table(connection, name, model, records, scratch):
    columns = columns_of(model)
    if not records:
        declared = ", ".join(f'"{column}" {kind}' for column, kind in columns.items())
        connection.execute(f'CREATE OR REPLACE TABLE "{name}" ({declared})')
        return 0
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / f"{name}.jsonl"
    with path.open("w") as handle:
        for record in records:
            handle.write(json.dumps(record.model_dump(mode="json")) + "\n")
    connection.execute(
        f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM read_json(?, columns := {columns!r})',
        [str(path)],
    )
    return connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
