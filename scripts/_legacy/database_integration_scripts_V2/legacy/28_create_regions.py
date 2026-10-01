"""28 — Create the `regions` table mapping countries to (region, macro_region)
with optional date constraints (Cliopatria classification).

Mirrors `enhance_db/src/bin/28_create_regions.rs`.

  Inputs : (none — hard-coded list)
  Output : regions (id PK, macro_region, region, iso_country_name, iso_a3,
                    start_year, end_year)
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

from common import DB_PATH, log, open_db, parse_run_mode, transaction


# (macro_region, region, iso_country_name, iso_a3, start_year, end_year)
REGION_DATA: list[tuple[str, str, str, str, int, int | None]] = [
    # Eastern Europe / Balkans
    ("Eastern Europe", "Balkans", "Bulgaria", "BGR", 500, None),
    ("Eastern Europe", "Balkans", "Greece", "GRC", 500, None),
    ("Eastern Europe", "Balkans", "Albania", "ALB", 500, None),
    ("Eastern Europe", "Balkans", "Montenegro", "MNE", 500, None),
    ("Eastern Europe", "Balkans", "Serbia", "SRB", 500, None),
    ("Eastern Europe", "Balkans", "Bosnia and Herzegovina", "BIH", 500, None),
    ("Eastern Europe", "Balkans", "Croatia", "HRV", 500, None),
    ("Eastern Europe", "Balkans", "North Macedonia", "MKD", 500, None),
    # Eastern Europe / Central Europe
    ("Eastern Europe", "Central Europe", "Latvia", "LVA", 500, None),
    ("Eastern Europe", "Central Europe", "Estonia", "EST", 500, None),
    ("Eastern Europe", "Central Europe", "Slovakia", "SVK", 500, None),
    ("Eastern Europe", "Central Europe", "Lithuania", "LTU", 500, None),
    ("Eastern Europe", "Central Europe", "Czech Republic", "CZE", 500, None),
    ("Eastern Europe", "Central Europe", "Poland", "POL", 500, None),
    ("Eastern Europe", "Central Europe", "Hungary", "HUN", 500, None),
    # Eastern Europe / East Slavic
    ("Eastern Europe", "East Slavic", "Belarus", "BLR", 500, None),
    ("Eastern Europe", "East Slavic", "Russia", "RUS", 500, None),
    ("Eastern Europe", "East Slavic", "Ukraine", "UKR", 500, None),
    # Western Europe
    ("Western Europe", "British Islands", "Ireland", "IRL", 500, None),
    ("Western Europe", "British Islands", "United Kingdom", "GBR", 500, None),
    ("Western Europe", "France", "France", "FRA", 500, None),
    ("Western Europe", "German world", "Germany", "DEU", 500, None),
    ("Western Europe", "German world", "Switzerland", "CHE", 500, None),
    ("Western Europe", "German world", "Austria", "AUT", 500, None),
    ("Western Europe", "Portugal", "Portugal", "PRT", 500, None),
    ("Western Europe", "Spain", "Spain", "ESP", 500, None),
    ("Western Europe", "Italy", "Italy", "ITA", 500, None),
    ("Western Europe", "Low countries", "Kingdom of the Netherlands", "NLD", 500, None),
    ("Western Europe", "Low countries", "Belgium", "BEL", 500, None),
    ("Western Europe", "Nordic countries", "Denmark", "DNK", 500, None),
    ("Western Europe", "Nordic countries", "Norway", "NOR", 500, None),
    ("Western Europe", "Nordic countries", "Sweden", "SWE", 500, None),
    ("Western Europe", "Nordic countries", "Finland", "FIN", 500, None),
    ("Western Europe", "Nordic countries", "Iceland", "ISL", 500, None),
    # MENA / Arabic world
    ("Middle-East and Africa (MENA)", "Arabic world", "Tunisia", "TUN", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Algeria", "DZA", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Morocco", "MAR", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Libya", "LBY", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Egypt", "EGY", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Palestine", "PSE", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Israel", "ISR", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Lebanon", "LBN", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Syria", "SYR", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Jordan", "JOR", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Iraq", "IRQ", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Kuwait", "KWT", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Oman", "OMN", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "United Arab Emirates", "ARE", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Saudi Arabia", "SAU", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Bahrain", "BHR", -10000, None),
    ("Middle-East and Africa (MENA)", "Arabic world", "Yemen", "YEM", -10000, None),
    # MENA / Persian World
    ("Middle-East and Africa (MENA)", "Persian World", "Iran", "IRN", -10000, None),
    ("Middle-East and Africa (MENA)", "Persian World", "Afghanistan", "AFG", -10000, None),
    ("Middle-East and Africa (MENA)", "Persian World", "Kyrgyzstan", "KGZ", -10000, None),
    ("Middle-East and Africa (MENA)", "Persian World", "Uzbekistan", "UZB", -10000, None),
    ("Middle-East and Africa (MENA)", "Persian World", "Turkmenistan", "TKM", -10000, None),
    ("Middle-East and Africa (MENA)", "Persian World", "Azerbaijan", "AZE", -10000, None),
    # Asia
    ("Asia", "Chinese World", "People's Republic of China", "CHN", -10000, None),
    ("Asia", "Chinese World", "Mongolia", "MNG", -10000, None),
    ("Asia", "Chinese World", "Taiwan", "TWN", -10000, None),
    ("Asia", "Indian World", "India", "IND", -10000, None),
    ("Asia", "Indian World", "Pakistan", "PAK", -10000, None),
    ("Asia", "Indian World", "Bangladesh", "BGD", -10000, None),
    ("Asia", "Indian World", "Sri Lanka", "LKA", -10000, None),
    ("Asia", "Indian World", "Nepal", "NPL", -10000, None),
    ("Asia", "Japan", "Japan", "JPN", -10000, None),
    ("Asia", "Korea", "South Korea", "KOR", -10000, None),
    ("Asia", "Korea", "North Korea", "PRK", -10000, None),
    # Ancient Mediterranean / Greek World (-800 to 500)
    ("Ancient Mediterranean", "Greek World", "Ukraine", "UKR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Albania", "ALB", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Montenegro", "MNE", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Turkey", "TUR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Greece", "GRC", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Bulgaria", "BGR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Romania", "ROU", -800, 500),
    ("Ancient Mediterranean", "Greek World", "France", "FRA", -800, -300),
    ("Ancient Mediterranean", "Greek World", "Italy", "ITA", -800, -300),
    ("Ancient Mediterranean", "Greek World", "Spain", "ESP", -800, -300),
    ("Ancient Mediterranean", "Greek World", "Libya", "LBY", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Egypt", "EGY", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Israel", "ISR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Palestine", "PSE", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Lebanon", "LBN", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Syria", "SYR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Jordan", "JOR", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Cyprus", "CYP", -800, 500),
    ("Ancient Mediterranean", "Greek World", "Iraq", "IRQ", -800, 500),
    # Ancient Mediterranean / Latin World (-300 to 500)
    ("Ancient Mediterranean", "Latin World", "Tunisia", "TUN", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Algeria", "DZA", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Morocco", "MAR", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Romania", "ROU", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Croatia", "HRV", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Serbia", "SRB", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Bosnia and Herzegovina", "BIH", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Slovenia", "SVN", -300, 500),
    ("Ancient Mediterranean", "Latin World", "France", "FRA", -300, 500),
    ("Ancient Mediterranean", "Latin World", "United Kingdom", "GBR", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Germany", "DEU", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Switzerland", "CHE", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Austria", "AUT", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Spain", "ESP", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Portugal", "PRT", -300, 500),
    ("Ancient Mediterranean", "Latin World", "Italy", "ITA", -300, 500),
]


def run(conn: sqlite3.Connection) -> None:
    log("[DB] 28: Creating regions table...")
    conn.execute("DROP TABLE IF EXISTS regions")
    conn.execute(
        """
        CREATE TABLE regions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            macro_region TEXT NOT NULL,
            region TEXT NOT NULL,
            iso_country_name TEXT NOT NULL,
            iso_a3 TEXT NOT NULL,
            start_year INTEGER NOT NULL,
            end_year INTEGER
        )
        """
    )
    with transaction(conn):
        conn.executemany(
            "INSERT INTO regions (macro_region, region, iso_country_name, iso_a3, "
            "start_year, end_year) VALUES (?, ?, ?, ?, ?, ?)",
            REGION_DATA,
        )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_regions_iso ON regions(iso_a3)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_regions_macro ON regions(macro_region)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_regions_region ON regions(region)")
    conn.commit()
    n = conn.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
    log(f"[28] Inserted {n} region-country mappings")


def _sample_main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "sample.sqlite3"
        with open_db(db) as conn:
            run(conn)
            log(f"[sample] total rows: {conn.execute('SELECT COUNT(*) FROM regions').fetchone()[0]}")
            for row in conn.execute(
                "SELECT macro_region, COUNT(*) FROM regions GROUP BY macro_region ORDER BY macro_region"
            ):
                log(f"  {row}")


if __name__ == "__main__":
    if parse_run_mode() == "full":
        with open_db(DB_PATH) as conn:
            run(conn)
    else:
        _sample_main()
