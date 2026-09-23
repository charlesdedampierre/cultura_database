import os
import sys
from pathlib import Path

import pyarrow

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pydantic_to_duckdb_schema import columns_of

BATCH = int(os.environ.get("BATCH", "20000"))


def declaration(model):
    return ", ".join(f'"{column}" {kind}' for column, kind in columns_of(model).items())


def create_table(connection, name, model):
    connection.execute(f'CREATE OR REPLACE TABLE "{name}" ({declaration(model)})')


class Table:

    def __init__(self, connection, name, model, batch=BATCH):
        self.connection = connection
        self.name = name
        self.struct = f"STRUCT({declaration(model)})"
        self.batch = batch
        self.pending = []
        self.count = 0
        create_table(connection, name, model)

    def add(self, record):
        self.pending.append(record.model_dump_json())
        if len(self.pending) >= self.batch:
            self.flush()

    def extend(self, records):
        for record in records:
            self.add(record)

    def flush(self):
        if not self.pending:
            return
        self.connection.register("incoming", pyarrow.table({"json": pyarrow.array(self.pending, type=pyarrow.string())}))
        self.connection.execute(
            f'INSERT INTO "{self.name}" SELECT UNNEST(CAST(CAST(json AS JSON) AS {self.struct})) FROM incoming'
        )
        self.connection.unregister("incoming")
        self.count += len(self.pending)
        self.pending = []

    def __enter__(self):
        return self

    def __exit__(self, *failure):
        if failure == (None, None, None):
            self.flush()
