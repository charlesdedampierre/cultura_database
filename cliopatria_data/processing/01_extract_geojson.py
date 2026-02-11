"""
Step 1: Extract and parse the Cliopatria GeoJSON data.

Input: ../cliopatria.geojson.zip
Output: data/cliopatria_parsed.json
"""

import json
import zipfile
from pathlib import Path
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).parent
INPUT_ZIP = SCRIPT_DIR.parent / "cliopatria.geojson.zip"
OUTPUT_JSON = SCRIPT_DIR / "data" / "cliopatria_parsed.json"


def extract_and_parse():
    """Extract geojson from zip and parse into structured format."""

    print(f"Reading from: {INPUT_ZIP}")

    # Extract from zip
    with zipfile.ZipFile(INPUT_ZIP, 'r') as zf:
        geojson_name = zf.namelist()[0]
        print(f"Extracting: {geojson_name}")

        with zf.open(geojson_name) as f:
            data = json.load(f)

    print(f"Total features: {len(data['features'])}")

    # Group by polity name
    polities = {}

    for feature in tqdm(data['features'], desc="Parsing features"):
        props = feature['properties']
        name = props.get('Name', '')

        if not name:
            continue

        if name not in polities:
            polities[name] = {
                'name': name,
                'type': props.get('Type'),
                'wikipedia': props.get('Wikipedia'),
                'seshat_id': props.get('SeshatID'),
                'member_of': props.get('MemberOf'),
                'components': props.get('Components'),
                'periods': []
            }

        # Add period with geometry
        period = {
            'from_year': props.get('FromYear'),
            'to_year': props.get('ToYear'),
            'area': props.get('Area'),
            'geometry': feature.get('geometry')
        }
        polities[name]['periods'].append(period)

    # Sort periods by from_year
    for polity in polities.values():
        polity['periods'].sort(key=lambda x: x['from_year'] or 0)

    # Save
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(polities, f)

    print(f"\n{'='*60}")
    print(f"EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"Unique polities: {len(polities)}")
    print(f"Total periods: {sum(len(p['periods']) for p in polities.values())}")
    print(f"Output: {OUTPUT_JSON}")

    return polities


if __name__ == "__main__":
    extract_and_parse()
