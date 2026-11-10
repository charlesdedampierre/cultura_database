"""Export every individual of the Cultura database to one CSV, cultura_database_V4.csv: one row per individual, the 28 columns
of ExportedIndividualCSV (dates and their sources, active life, occupations and the Seshat polities of each life stage).
The columns are those of the researcher sample (export_researcher_sample.py), computed here for all individuals."""

import argparse
import sys
import tempfile
from pathlib import Path

import duckdb
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "1-datamodels"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from datamodel_export import ExportedIndividualCSV
from export_researcher_sample import COLUMNS, LABELS

DATABASE = ROOT / "data" / "cultura" / "cultura_database_V4.duckdb"
OUTPUT = ROOT / "data" / "exports" / "cultura_database_V4.csv"
VALIDATION_BATCH = 100_000
RANGES = 40  # qid ranges written one after the other: the whole join at once does not fit in memory

INDIVIDUALS = """
SELECT
{columns}FROM sample
JOIN individual ON individual.entity.qid = sample.entity.qid
CROSS JOIN label
WHERE {inside}
ORDER BY sample.entity.qid
"""


def qid_ranges(connection):
    cuts = connection.execute(f"SELECT quantile_disc(entity.qid, {[i / RANGES for i in range(1, RANGES)]}) FROM individual_enriched").fetchone()[0]
    return [" AND ".join([f"sample.entity.qid >= '{low}'"] * (low is not None) + [f"sample.entity.qid < '{high}'"] * (high is not None))
            for low, high in zip([None, *cuts], [*cuts, None])]


def write(connection, output):
    """One CSV part per qid range, in qid order, then concatenated under a single header."""
    parts = []
    for number, inside in enumerate(tqdm(qid_ranges(connection), desc="qid ranges")):
        part = output.with_name(f"{output.stem}.part{number:02d}.csv")
        query = INDIVIDUALS.replace("{columns}", COLUMNS).replace("{inside}", inside)
        connection.execute(f"COPY ({query}) TO '{part}' (HEADER {'true' if number == 0 else 'false'}, DELIMITER ',')")
        parts.append(part)
    with output.open("wb") as joined:
        for part in parts:
            joined.write(part.read_bytes())
            part.unlink()


def validate(connection, path):
    """Every row of the written CSV against ExportedIndividualCSV, streamed in batches."""
    total = connection.execute("SELECT count(*) FROM individual_enriched").fetchone()[0]
    rows = connection.execute(f"SELECT * FROM read_csv('{path}', all_varchar = true)")
    columns = [column[0] for column in rows.description]
    assert columns == list(ExportedIndividualCSV.model_fields), "the CSV's columns are not those of ExportedIndividualCSV"
    checked = 0
    with tqdm(total=total, desc="validate", unit=" rows") as progress:
        while batch := rows.fetchmany(VALIDATION_BATCH):
            for row in batch:
                ExportedIndividualCSV(**dict(zip(columns, row)))
            checked += len(batch)
            progress.update(len(batch))
    assert checked == total, f"{checked:,} rows written for {total:,} individuals"
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(args.database), read_only=True)
    connection.execute(f"SET memory_limit = '6GB'; SET threads = 4; SET temp_directory = '{tempfile.mkdtemp()}'")
    connection.execute(LABELS)
    connection.execute("CREATE TEMP VIEW sample AS SELECT individual_enriched.* FROM individual_enriched")
    print(f"writing {args.output}")
    write(connection, args.output)
    checked = validate(connection, args.output)
    print(f"{checked:,} individuals written to {args.output}, all valid ExportedIndividualCSV rows")
    connection.close()


if __name__ == "__main__":
    main()
