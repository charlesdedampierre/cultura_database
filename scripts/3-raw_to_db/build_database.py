import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "helpers"))

import build_helpers

HERE = Path(__file__).resolve().parent

PARTS = (
    "01_add_wikidata_properties.py",
    "02_add_cliopatria_polities.py",
    "03_add_places_and_countries.py",
    "04_add_occupations.py",
    "05_add_identifier_types.py",
    "06_add_works.py",
    "07_add_individuals.py",
)


def main():
    if build_helpers.DATABASE.exists():
        build_helpers.DATABASE.unlink()
    build_helpers.TASK_LOG.unlink(missing_ok=True)
    build_helpers.report("build", f"{build_helpers.DATABASE}   {build_helpers.free_gb():.0f} GB free")

    started = time.time()
    for part in PARTS:
        build_helpers.check_disk()
        finished = subprocess.run([sys.executable, str(HERE / part)])
        if finished.returncode:
            build_helpers.report("build", f"{part} failed with {finished.returncode}")
            raise SystemExit(finished.returncode)

    connection = build_helpers.open_database()
    for (name,) in connection.execute("select table_name from information_schema.tables order by table_name").fetchall():
        count = connection.execute(f'select count(*) from "{name}"').fetchone()[0]
        build_helpers.report("build", f"   {name:24} {count:>12,}")
    connection.close()

    size = build_helpers.DATABASE.stat().st_size / 1e9
    build_helpers.report("build", f"done in {(time.time() - started) / 60:.0f} min   {build_helpers.DATABASE}   {size:.1f} GB")


if __name__ == "__main__":
    main()
