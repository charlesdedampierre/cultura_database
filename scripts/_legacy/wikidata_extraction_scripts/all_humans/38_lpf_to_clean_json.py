"""
Convert the WHG Linked Places Format file (whg_dataset_1701.lpf) into a clean,
flat JSON with one object per polity.

Outputs:
  - data/cliopatria_V2/whg_dataset_1701.clean.json       (full, includes geometry)
  - data/cliopatria_V2/whg_dataset_1701.metadata.json    (no geometry, small)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

IN_PATH = Path("data/cliopatria_V2/whg_dataset_1701.lpf")
OUT_FULL = Path("data/cliopatria_V2/whg_dataset_1701.clean.json")
OUT_META = Path("data/cliopatria_V2/whg_dataset_1701.metadata.json")

WD_PAT = re.compile(r"^wd:(Q\d+)$")


def flatten_timespans(ts_list):
    """LPF timespans look like {"start": {"latest": "-3400"}, "end": {"earliest": "-3201"}}.
    Return [{"start": "-3400", "end": "-3201"}, ...] in plain string years.
    """
    out = []
    for t in ts_list or []:
        start = (
            (t.get("start") or {}).get("latest")
            or (t.get("start") or {}).get("earliest")
            or (t.get("start") or {}).get("in")
        )
        end = (
            (t.get("end") or {}).get("earliest")
            or (t.get("end") or {}).get("latest")
            or (t.get("end") or {}).get("in")
        )
        out.append({"start": start, "end": end})
    return out


def extract_timespans_from(obj):
    """Find nested {'timespans': [...]} anywhere in obj and flatten."""
    spans = (obj or {}).get("timespans") if isinstance(obj, dict) else None
    return flatten_timespans(spans) if spans else []


def build_record(feat: dict) -> dict:
    props = feat.get("properties", {}) or {}
    links = props.get("links", []) or []

    wikidata_qids: list[str] = []
    other_ids: dict[str, list[str]] = {}
    for lk in links:
        ident = (lk.get("identifier") or "").strip()
        if not ident or ":" not in ident:
            continue
        prefix, value = ident.split(":", 1)
        if prefix == "wd":
            if value != "None":
                wikidata_qids.append(value)
        else:
            other_ids.setdefault(prefix, []).append(value)

    # de-dup while preserving order
    wikidata_qids = list(dict.fromkeys(wikidata_qids))
    for k, v in other_ids.items():
        other_ids[k] = list(dict.fromkeys(v))

    types = []
    for t in props.get("types", []) or []:
        types.append(
            {
                "label": t.get("label"),
                "identifier": t.get("identifier"),
                "timespans": flatten_timespans((t.get("when") or {}).get("timespans")),
            }
        )

    names = []
    for n in props.get("names", []) or []:
        names.append(
            {
                "toponym": n.get("toponym"),
                "timespans": flatten_timespans((n.get("when") or {}).get("timespans")),
            }
        )

    geometry = feat.get("geometry") or {}
    geom_timespans = flatten_timespans(
        (geometry.get("when") or {}).get("timespans") if isinstance(geometry, dict) else None
    )

    return {
        "id": feat.get("id"),
        "name": props.get("title"),
        "ccodes": props.get("ccodes") or [],
        "names": names,
        "types": types,
        "timespans": geom_timespans,
        "wikidata_qids": wikidata_qids,
        "other_ids": other_ids,
        "description": props.get("description"),
        "geometry": geometry,
    }


def main() -> int:
    in_path = Path(sys.argv[1]) if len(sys.argv) > 1 else IN_PATH
    with open(in_path, encoding="utf-8") as f:
        lpf = json.load(f)

    records = [build_record(feat) for feat in lpf.get("features", [])]

    OUT_FULL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FULL, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)
    meta = [{k: v for k, v in r.items() if k != "geometry"} for r in records]
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    n_with_qid = sum(1 for r in records if r["wikidata_qids"])
    print(f"records                     : {len(records)}")
    print(f"records with wikidata Q-id  : {n_with_qid}")
    print(f"wrote {OUT_FULL}  ({OUT_FULL.stat().st_size/1024/1024:.1f} MB)")
    print(f"wrote {OUT_META}  ({OUT_META.stat().st_size/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
