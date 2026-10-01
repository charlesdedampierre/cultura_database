"""Build data/similar_databases/pantheon.duckdb, the table individuals, from the Pantheon 2.0 person CSV."""

from csv_to_duckdb import R, SIMILAR, build

SOURCE = SIMILAR / "pantheon 2.0" / "person_2025_update.csv"

if __name__ == "__main__":
    build(SOURCE, R.PantheonPerson, SIMILAR / "pantheon.duckdb")
