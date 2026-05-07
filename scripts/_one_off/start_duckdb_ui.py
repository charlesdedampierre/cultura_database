"""Start the DuckDB web UI on data/humans_clean.duckdb and keep it alive.

The DuckDB UI is served by an HTTP extension started inside a connection.
The server stays up only while the process holding the connection is alive,
so this script just opens the connection, calls start_ui, and sleeps.
"""

from __future__ import annotations

import signal
import time
from pathlib import Path

import duckdb

DB = Path(__file__).resolve().parent.parent / "data" / "humans_clean.duckdb"


def main() -> None:
    con = duckdb.connect(str(DB))
    con.execute("INSTALL ui")
    con.execute("LOAD ui")
    res = con.execute("CALL start_ui()").fetchone()
    print(f"DuckDB UI: {res[0] if res else 'started'}")
    print(f"DB       : {DB}")
    print("Ctrl-C or kill this process to stop.")

    stop = False

    def _handle(signum, frame):  # noqa: ARG001
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    while not stop:
        time.sleep(1)

    con.close()


if __name__ == "__main__":
    main()
