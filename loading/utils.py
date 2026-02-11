"""Shared utilities for loading scripts."""

import os
import re
import sqlite3

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "cultura.db")
EXTRACTED_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "extracted")


def get_db_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def split_wiki(url: str) -> str | None:
    """Extract Q-ID from a Wikidata URL."""
    if not url:
        return None
    try:
        return url.split("www.wikidata.org/entity/")[1]
    except (IndexError, AttributeError):
        return None


def clean_date(raw_date: str) -> int | None:
    """Parse a date string to extract the year as integer.

    Handles ISO dates like '1749-08-28T00:00:00Z' and negative years like '-0500-01-01'.
    """
    if not raw_date:
        return None
    try:
        raw_date = str(raw_date).strip()
        if raw_date.startswith("-"):
            return int(raw_date[:5])
        else:
            return int(raw_date[:4])
    except (ValueError, IndexError):
        return None


def point_to_coordinates(wkt: str) -> tuple[float, float] | None:
    """Parse WKT point string 'Point(lon lat)' to (longitude, latitude)."""
    if not wkt:
        return None
    try:
        match = re.match(r"Point\(([-\d.]+)\s+([-\d.]+)\)", wkt)
        if match:
            lon = float(match.group(1))
            lat = float(match.group(2))
            return (lon, lat)
        return None
    except (ValueError, AttributeError):
        return None
