"""
Step 4: Create hierarchy tables for polity relationships.

Creates:
- polity_hierarchy: parent-child relationships
- polity_hierarchy_levels: flattened multi-level view

Input/Output: data/cliopatria.db
"""

import sqlite3
from pathlib import Path
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).parent
DB_PATH = SCRIPT_DIR / "data" / "cliopatria.db"


def create_hierarchy_table(conn):
    """Create the hierarchy table."""
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS polity_hierarchy")
    cursor.execute("DROP TABLE IF EXISTS polity_hierarchy_levels")

    # Create parent-child relationship table
    cursor.execute("""
        CREATE TABLE polity_hierarchy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER NOT NULL,
            child_id INTEGER NOT NULL,
            parent_name TEXT,
            child_name TEXT,
            FOREIGN KEY (parent_id) REFERENCES polities(id),
            FOREIGN KEY (child_id) REFERENCES polities(id),
            UNIQUE(parent_id, child_id)
        )
    """)

    cursor.execute("CREATE INDEX idx_hierarchy_parent ON polity_hierarchy(parent_id)")
    cursor.execute("CREATE INDEX idx_hierarchy_child ON polity_hierarchy(child_id)")

    conn.commit()
    print("Created polity_hierarchy table")


def build_name_to_id_map(conn):
    """Build mapping from polity name to ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM polities")
    return {row[1]: row[0] for row in cursor.fetchall()}


def parse_and_insert_hierarchy(conn, name_to_id):
    """Parse member_of and components to build hierarchy."""
    cursor = conn.cursor()
    relationships = set()

    cursor.execute("""
        SELECT id, name, member_of, components
        FROM polities
        WHERE member_of IS NOT NULL OR components IS NOT NULL
    """)

    for polity_id, name, member_of, components in cursor.fetchall():
        # Parse member_of (this polity is a CHILD of listed polities)
        if member_of:
            parents = [p.strip() for p in member_of.split(";") if p.strip()]
            for parent_name in parents:
                parent_id = name_to_id.get(parent_name)
                if parent_id:
                    relationships.add((parent_id, polity_id, parent_name, name))

        # Parse components (this polity is a PARENT of listed polities)
        if components:
            children = [c.strip() for c in components.split(";") if c.strip()]
            for child_name in children:
                child_id = name_to_id.get(child_name)
                if child_id:
                    relationships.add((polity_id, child_id, name, child_name))

    # Insert relationships
    for parent_id, child_id, parent_name, child_name in tqdm(relationships, desc="Inserting relationships"):
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO polity_hierarchy (parent_id, child_id, parent_name, child_name)
                VALUES (?, ?, ?, ?)
            """, (parent_id, child_id, parent_name, child_name))
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    return len(relationships)


def create_hierarchy_levels_table(conn):
    """Create hierarchy levels table with one row per polity."""
    cursor = conn.cursor()

    # Table structure: each polity gets one row showing its ancestry
    # level1 = direct parent, level2 = parent's parent, level3 = level2's parent
    cursor.execute("""
        CREATE TABLE polity_hierarchy_levels (
            polity_id INTEGER PRIMARY KEY,
            polity_name TEXT,
            level1_id INTEGER,
            level1 TEXT,
            level2_id INTEGER,
            level2 TEXT,
            level3_id INTEGER,
            level3 TEXT,
            depth INTEGER,
            is_parent INTEGER DEFAULT 0,
            is_child INTEGER DEFAULT 0,
            FOREIGN KEY (polity_id) REFERENCES polities(id),
            FOREIGN KEY (level1_id) REFERENCES polities(id),
            FOREIGN KEY (level2_id) REFERENCES polities(id),
            FOREIGN KEY (level3_id) REFERENCES polities(id)
        )
    """)

    # Insert ALL polities first with depth 0
    cursor.execute("""
        INSERT INTO polity_hierarchy_levels (polity_id, polity_name, depth)
        SELECT id, name, 0 FROM polities
    """)

    # Mark polities that are parents
    cursor.execute("""
        UPDATE polity_hierarchy_levels
        SET is_parent = 1
        WHERE polity_id IN (SELECT DISTINCT parent_id FROM polity_hierarchy)
    """)

    # Mark polities that are children
    cursor.execute("""
        UPDATE polity_hierarchy_levels
        SET is_child = 1
        WHERE polity_id IN (SELECT DISTINCT child_id FROM polity_hierarchy)
    """)

    # Update with level1 (direct parent) info
    cursor.execute("""
        UPDATE polity_hierarchy_levels
        SET level1_id = (
                SELECT h.parent_id FROM polity_hierarchy h
                WHERE h.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            level1 = (
                SELECT h.parent_name FROM polity_hierarchy h
                WHERE h.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            depth = 1
        WHERE polity_id IN (SELECT child_id FROM polity_hierarchy)
    """)

    # Update with level2 (parent's parent) info
    cursor.execute("""
        UPDATE polity_hierarchy_levels
        SET level2_id = (
                SELECT h2.parent_id FROM polity_hierarchy h1
                JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
                WHERE h1.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            level2 = (
                SELECT h2.parent_name FROM polity_hierarchy h1
                JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
                WHERE h1.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            depth = 2
        WHERE polity_id IN (
            SELECT h1.child_id FROM polity_hierarchy h1
            JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
        )
    """)

    # Update with level3 (level2's parent) info
    cursor.execute("""
        UPDATE polity_hierarchy_levels
        SET level3_id = (
                SELECT h3.parent_id FROM polity_hierarchy h1
                JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
                JOIN polity_hierarchy h3 ON h2.parent_id = h3.child_id
                WHERE h1.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            level3 = (
                SELECT h3.parent_name FROM polity_hierarchy h1
                JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
                JOIN polity_hierarchy h3 ON h2.parent_id = h3.child_id
                WHERE h1.child_id = polity_hierarchy_levels.polity_id
                LIMIT 1
            ),
            depth = 3
        WHERE polity_id IN (
            SELECT h1.child_id FROM polity_hierarchy h1
            JOIN polity_hierarchy h2 ON h1.parent_id = h2.child_id
            JOIN polity_hierarchy h3 ON h2.parent_id = h3.child_id
        )
    """)

    # Create index
    cursor.execute("CREATE INDEX idx_hierarchy_levels_depth ON polity_hierarchy_levels(depth)")

    # Remove pure parent polities (those that are parents but not children)
    # These are container polities that only exist to group other polities
    # They already appear in level1/level2/level3 columns of their children
    cursor.execute("""
        DELETE FROM polity_hierarchy_levels
        WHERE is_parent = 1 AND is_child = 0
    """)

    conn.commit()
    print("Created polity_hierarchy_levels table")


def drop_temp_hierarchy_table(conn):
    """Drop the temporary polity_hierarchy table."""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS polity_hierarchy")
    conn.commit()
    print("Dropped temporary polity_hierarchy table")


def print_summary(conn):
    """Print hierarchy summary."""
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM polity_hierarchy_levels")
    total_polities = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM polities")
    total_original = cursor.fetchone()[0]

    cursor.execute("SELECT depth, COUNT(*) FROM polity_hierarchy_levels GROUP BY depth ORDER BY depth")
    depth_counts = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM polity_hierarchy_levels WHERE is_parent = 1")
    is_parent_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM polity_hierarchy_levels WHERE is_child = 1")
    is_child_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM polity_hierarchy_levels WHERE is_parent = 0 AND is_child = 0")
    standalone_count = cursor.fetchone()[0]

    excluded_parents = total_original - total_polities

    print(f"\n{'='*60}")
    print("HIERARCHY TABLE CREATED")
    print(f"{'='*60}")
    print(f"Total polities in table: {total_polities}")
    print(f"  - Standalone (no hierarchy): {standalone_count}")
    print(f"  - Are parents: {is_parent_count}")
    print(f"  - Are children: {is_child_count}")
    print(f"  - Pure parents excluded (appear only in level columns): {excluded_parents}")
    print("\nPolity depth distribution (ancestry levels):")
    for depth, count in depth_counts:
        label = {0: "no parent", 1: "has level1", 2: "has level2", 3: "has level3"}.get(depth, f"depth {depth}")
        print(f"  Depth {depth} ({label}): {count} polities")

    # Show top parents from hierarchy_levels
    cursor.execute("""
        SELECT level1, COUNT(*) as children_count
        FROM polity_hierarchy_levels
        WHERE level1 IS NOT NULL
        GROUP BY level1
        ORDER BY children_count DESC
        LIMIT 5
    """)
    print("\nTop parent polities:")
    for name, count in cursor.fetchall():
        print(f"  {name}: {count} children")


if __name__ == "__main__":
    conn = sqlite3.connect(DB_PATH, timeout=30)

    # Create temporary hierarchy table for building relationships
    create_hierarchy_table(conn)
    name_to_id = build_name_to_id_map(conn)
    parse_and_insert_hierarchy(conn, name_to_id)

    # Create final hierarchy levels table
    create_hierarchy_levels_table(conn)

    # Drop temporary table
    drop_temp_hierarchy_table(conn)

    print_summary(conn)
    conn.close()
