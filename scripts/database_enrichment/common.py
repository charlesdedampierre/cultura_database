import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "datamodels"))
sys.path.insert(0, str(ROOT / "scripts" / "raw_to_db" / "helpers"))

import datamodel_in_duckdb as D
from pydantic_to_duckdb_schema import duck_type

DATABASE = Path(os.environ.get("CULTURA_DB", ROOT / "data" / "cultura_v2.duckdb"))
SCRATCH = Path(os.environ.get("SCRATCH", "/tmp")) / "database_enrichment"


@dataclass(frozen=True)
class Enrichment:
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    rule: str
    answers: Path
    prompt_id: str | None = None
    model_name: str | None = None
    inputs: tuple[str, ...] = ()

    def provenance(self):
        return D.Provenance(
            raw=self.reads if not self.inputs else (),
            inputs=self.inputs,
            rule=self.rule,
            ai_answer=D.AIAnswer(model_name=self.model_name, prompt_id=self.prompt_id) if self.prompt_id else None,
        )

    def announce(self):
        print(f"reads   {', '.join(self.reads)}")
        print(f"writes  {', '.join(self.writes)}")
        print(f"rule    {self.rule}")
        print(f"answers {self.answers}")
        if self.prompt_id:
            print(f"prompt  {self.prompt_id}")
        print()


def open_database(read_only=False):
    if not DATABASE.exists():
        raise SystemExit(f"{DATABASE} does not exist; build it with scripts/raw_to_db/build_database.py")
    return duckdb.connect(str(DATABASE), read_only=read_only)


def stage(connection, name, columns, rows):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    path = SCRATCH / f"{name}.jsonl"
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    connection.execute(
        f'CREATE OR REPLACE TEMP TABLE "{name}" AS SELECT * FROM read_json(?, columns := {columns!r})',
        [str(path)],
    )
    return connection.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]


def provenance_column():
    return duck_type(D.Provenance)


def as_json(model):
    return model.model_dump(mode="json")
