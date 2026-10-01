"""Load a comparison dataset's CSV into a DuckDB table typed by its class in datamodel_raw.py."""

import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[3]
SIMILAR = ROOT / "data" / "similar_databases"
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
sys.path.insert(0, str(ROOT / "scripts" / "3-raw_to_db" / "helpers"))

import datamodel_raw as R
from pydantic_to_duckdb_schema import columns_of


def build(source, model, database, table="individuals", **read_options):
    """Every column is read as text and cast to the type the model gives it, so a value that does not fit stops the build."""
    database = Path(os.environ.get("OUT", database))
    columns = columns_of(model)
    casts = ", ".join(f'CAST("{column}" AS {kind}) AS "{column}"' for column, kind in columns.items())
    options = "".join(f", {key} = {value!r}" for key, value in read_options.items())
    connection = duckdb.connect(str(database))
    connection.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT {casts} FROM read_csv(?, all_varchar = true, header = true{options})', [str(source)])
    rows = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
    connection.close()
    print(f"{database.relative_to(ROOT) if database.is_relative_to(ROOT) else database}  {table}: {rows:,} rows, {len(columns)} columns typed by {model.__name__}")
