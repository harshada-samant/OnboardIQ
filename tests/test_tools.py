"""
tests/test_tools.py
--------------------
Run this to verify all tools work correctly before building the agent.
"""

import sys
import json
from pathlib import Path

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from tools.file_tools import read_file
from tools.stats_tools import get_column_stats, get_all_column_stats
from tools.relationship_tools import detect_potential_keys, find_relationships
from tools.output_tools import save_output, load_output


def print_section(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_result(result):
    print(json.dumps(result, indent=2, default=str))


# -------------------------------------------------------
# TEST 1: read_file
# -------------------------------------------------------
print_section("TEST 1: read_file — assets.csv")
result = read_file("data/assets.csv")
print(f"File: {result['file_name']}")
print(f"Rows: {result['row_count']}, Columns: {result['column_count']}")
print(f"Columns found: {[c['name'] for c in result['columns']]}")
print(f"Sample row: {result['sample_rows'][0]}")


# -------------------------------------------------------
# TEST 2: read_file on workorders
# -------------------------------------------------------
print_section("TEST 2: read_file — workorders.csv")
result = read_file("data/workorders.csv")
print(f"File: {result['file_name']}")
print(f"Rows: {result['row_count']}, Columns: {result['column_count']}")
print(f"Columns found: {[c['name'] for c in result['columns']]}")


# -------------------------------------------------------
# TEST 3: get_column_stats on a specific column
# -------------------------------------------------------
print_section("TEST 3: get_column_stats — assets.csv → asset_no")
result = get_column_stats("data/assets.csv", "asset_no")
print(f"Column: {result['column_name']}")
print(f"Unique: {result['unique_count']} / {result['total_rows']} ({result['uniqueness_pct']}%)")
print(f"Nulls: {result['null_count']} ({result['null_pct']}%)")
print(f"Is likely ID: {result['is_likely_id']}")


# -------------------------------------------------------
# TEST 4: get_column_stats on a column with nulls
# -------------------------------------------------------
print_section("TEST 4: get_column_stats — workorders.csv → assigned_to (has nulls)")
result = get_column_stats("data/workorders.csv", "assigned_to")
print(f"Column: {result['column_name']}")
print(f"Null %: {result['null_pct']}%")
print(f"Is likely FK: {result['is_likely_foreign_key']}")


# -------------------------------------------------------
# TEST 5: detect_potential_keys
# -------------------------------------------------------
print_section("TEST 5: detect_potential_keys — assets.csv")
result = detect_potential_keys("data/assets.csv")
print("Primary key candidates:")
for k in result["primary_key_candidates"]:
    print(f"  → {k['column']} (uniqueness: {k['uniqueness_pct']}%, confidence: {k['confidence']})")
print("Foreign key candidates:")
for k in result["foreign_key_candidates"]:
    print(f"  → {k['column']} (uniqueness: {k['uniqueness_pct']}%, confidence: {k['confidence']})")


print_section("TEST 5b: detect_potential_keys — workorders.csv")
result = detect_potential_keys("data/workorders.csv")
print("Primary key candidates:")
for k in result["primary_key_candidates"]:
    print(f"  → {k['column']} (uniqueness: {k['uniqueness_pct']}%, confidence: {k['confidence']})")
print("Foreign key candidates:")
for k in result["foreign_key_candidates"]:
    print(f"  → {k['column']} (uniqueness: {k['uniqueness_pct']}%, confidence: {k['confidence']})")


# -------------------------------------------------------
# TEST 6: find_relationships between two files
# -------------------------------------------------------
print_section("TEST 6: find_relationships — assets.csv ↔ workorders.csv")
result = find_relationships("data/assets.csv", "data/workorders.csv")
print(f"Relationships found: {result['relationships_found']}")
for rel in result["relationships"]:
    print(f"  → {rel['likely_relationship']}")
    print(f"     Match rate: {rel['pct_of_file1_matched']}% | Confidence: {rel['confidence']}")


# -------------------------------------------------------
# TEST 7: save and reload output
# -------------------------------------------------------
print_section("TEST 7: save_output and load_output")
sample_catalog = {
    "entities": [
        {"name": "Assets", "primary_key": "asset_no", "row_count": 10},
        {"name": "WorkOrders", "primary_key": "wo_id", "row_count": 10}
    ]
}
save_result = save_output(sample_catalog, "entity_catalog.json")
print(f"Saved to: {save_result['saved_to']}")

loaded = load_output("entity_catalog.json")
print(f"Loaded back: {len(loaded['entities'])} entities")
print(f"First entity: {loaded['entities'][0]['name']}")


print_section("ALL TESTS PASSED ✓")
