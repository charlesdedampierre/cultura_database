"""
Convert large single-line JSON files to TSV format for efficient streaming in Rust.
Uses ijson for streaming parsing to avoid loading the entire file into memory.
"""

import ijson
import gc

TASK_LOG = "task.log"

def log(msg):
    print(msg)
    with open(TASK_LOG, "a") as f:
        f.write(msg + "\n")


def clean_label(s):
    s = str(s).strip('"').strip()
    if s.endswith("@en"):
        s = s[:-3].strip('"')
    return s.strip('"')


def convert_genders():
    """Convert all_human_genders.json to TSV using streaming parser."""
    input_path = "data/all_humans/all_human_genders.json"
    output_path = "data/all_humans/all_human_genders.tsv"

    log(f"[PREPROCESS] Streaming {input_path} to TSV...")

    count = 0
    with open(input_path, "rb") as f, open(output_path, "w") as out:
        out.write("wikidata_id\tgender\n")

        # ijson.kvitems gives us top-level key-value pairs
        try:
            for wikidata_id, val in ijson.kvitems(f, ""):
                if isinstance(val, dict):
                    gender = clean_label(val.get("name", ""))
                elif isinstance(val, str):
                    gender = clean_label(val)
                else:
                    continue

                if gender and wikidata_id.startswith("Q"):
                    out.write(f"{wikidata_id}\t{gender}\n")
                    count += 1

                if count % 2_000_000 == 0 and count > 0:
                    log(f"[PREPROCESS]   Written {count:,} genders...")
        except ijson.common.IncompleteJSONError:
            log(f"[PREPROCESS] Warning: JSON file is truncated, recovered {count:,} entries")

    log(f"[PREPROCESS] Saved {count:,} genders to {output_path}")
    gc.collect()
    return count


if __name__ == "__main__":
    convert_genders()
