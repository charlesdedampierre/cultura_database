"""Write a clean UTF-8 copy of cross-verified-database.csv.gz.

The source file is mostly UTF-8 but contains a small number of stray
non-UTF-8 bytes that crash strict UTF-8 parsing. We:
  - decode each line as UTF-8 first (preserves valid multi-byte chars)
  - on failure, fall back to cp1252 then latin-1 (Pantheon's source
    encoding for the malformed bytes), so accented characters are
    recovered as the intended Unicode codepoint instead of mojibake.

The original file is NOT overwritten; a sibling `.utf8.csv.gz` is
written.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from tqdm import tqdm

ROOT = Path("/Users/charlesdedampierre/Desktop/Rsearch Folder/cultura_database")
SRC = (ROOT / "data/similar_databases/cross-verified-database/"
       "cross-verified-database.csv.gz")
DST = (ROOT / "data/similar_databases/cross-verified-database/"
       "cross-verified-database.utf8.csv.gz")

print(f"Re-encoding {SRC.name} -> {DST.name}")
n_lines = 0
n_recovered = 0
with gzip.open(SRC, "rb") as fin, gzip.open(DST, "wb") as fout:
    pbar = tqdm(unit=" lines", desc="re-encoding")
    for raw in fin:
        n_lines += 1
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            n_recovered += 1
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
        fout.write(text.encode("utf-8"))
        pbar.update(1)
    pbar.close()

print(f"  lines processed:        {n_lines:,}")
print(f"  lines recovered (had bad UTF-8): {n_recovered:,}")
print(f"  wrote {DST}")
