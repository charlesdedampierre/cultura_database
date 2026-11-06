"""Shared helpers for the enrichment steps: the database path, the Enrichment contract and the staging of rows into DuckDB."""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
sys.path.insert(0, str(ROOT / "scripts" / "3-raw_to_db" / "helpers"))

import datamodel_in_duckdb as D
import datamodel_raw as R
from pydantic_to_duckdb_schema import duck_type

DATABASE = Path(os.environ.get("CULTURA_DB", ROOT / "data" / "cultura" / "cultura_enriched_v3.2.duckdb"))
BASE = ROOT / "data" / "cultura" / "humans_clean_non_enriched_v3.duckdb"
AI_OUTPUTS = ROOT / "data" / "ai_outputs"
SCRATCH = Path(os.environ.get("SCRATCH", "/tmp")) / "database_enrichment"
REWRITE_RANGES = 40  # qid ranges individual_enriched is rewritten in


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
            ai_answer=D.AIAnswer(model_name=self.model_name, prompt_id=self.prompt_id) if self.prompt_id or self.model_name else None,
        )

    def announce(self):
        print(f"reads   {', '.join(self.reads)}")
        print(f"writes  {', '.join(self.writes)}")
        print(f"rule    {self.rule}")
        print(f"answers {self.answers}")
        if self.prompt_id:
            print(f"prompt  {self.prompt_id}")
        print()


def ai_run(name, model):
    """The answers a language model gave, read back from data/ai_outputs/ and checked against their datamodel class."""
    path = AI_OUTPUTS / f"{name}.json"
    return path, model.model_validate_json(path.read_text())


def open_database(read_only=False):
    if not DATABASE.exists():
        raise SystemExit(f"{DATABASE} does not exist; build it with scripts/3-raw_to_db/build_database.py")
    connection = duckdb.connect(str(DATABASE), read_only=read_only)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit = '6GB'; SET temp_directory = '{SCRATCH}'")
    return connection


def qid_ranges(connection, table):
    """REWRITE_RANGES filters of about equal size on table.entity.qid, for statements that spill too much on the whole table."""
    cuts = connection.execute(f"SELECT quantile_disc(entity.qid, {[i / REWRITE_RANGES for i in range(1, REWRITE_RANGES)]}) FROM {table}").fetchone()[0]
    return [
        " AND ".join([f"{table}.entity.qid >= '{low}'"] * (low is not None) + [f"{table}.entity.qid < '{high}'"] * (high is not None))
        for low, high in zip([None, *cuts], [*cuts, None])
    ]


def rewrite_individual_enriched(connection, rows, parameters=()):
    """Rebuild individual_enriched from rows, a SELECT whose WHERE holds the placeholder {inside}, a filter on
    individual_enriched.entity.qid. It runs once per qid range, because the whole table at once spills more than the free disk."""
    connection.execute(f"SET preserve_insertion_order = false; SET temp_directory = '{SCRATCH}'")
    connection.execute("DROP TABLE IF EXISTS individual_enriched_new")
    for number, inside in enumerate(tqdm(qid_ranges(connection, "individual_enriched"), desc="individual_enriched qid ranges")):
        chunk = rows.replace("{inside}", inside + " ORDER BY individual_enriched.entity.qid")
        connection.execute(f"CREATE TABLE individual_enriched_new AS {chunk}" if number == 0 else f"INSERT INTO individual_enriched_new {chunk}", list(parameters))
    before, after = (connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("individual_enriched", "individual_enriched_new"))
    assert before == after, f"individual_enriched: {before:,} rows became {after:,}"
    connection.execute("DROP TABLE individual_enriched")
    connection.execute("ALTER TABLE individual_enriched_new RENAME TO individual_enriched")


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
