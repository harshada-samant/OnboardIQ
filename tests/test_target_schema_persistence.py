"""
tests/test_target_schema_persistence.py
-----------------------------------------
Unit tests verifying SQLite target schema persistence, dynamic ID lookup,
schema file existence validations, and multi-user data isolation.
"""

import sys
import os
import sqlite3
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import (
    get_db_connection,
    update_user_target_schema,
    get_user_target_schema
)

# Global tracker for files created by this test
CREATED_FILES = []

def setup_temp_schema(filename: str):
    """Creates a temporary schema file if it doesn't already exist."""
    file_path = config.SCHEMAS_DIR / filename
    if not file_path.exists():
        config.SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
        file_path.write_text("{}", encoding="utf-8")
        CREATED_FILES.append(file_path)
        print(f"  [Setup] Created temp schema: {file_path}")

def cleanup_temp_schemas():
    """Removes only the schema files created during setup."""
    for file_path in CREATED_FILES:
        if file_path.exists():
            file_path.unlink()
            print(f"  [Teardown] Removed temp schema: {file_path}")
    CREATED_FILES.clear()

def get_user_id_by_username(username: str) -> int:
    """Queries the database to retrieve the ID dynamically before running tests."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Required seed user '{username}' not found in the users table.")
        return row["id"]

def run_tests():
    print("=== Testing Target Schema Persistence ===")
    
    # 1. Resolve user IDs dynamically
    user1_id = get_user_id_by_username("user1")
    user2_id = get_user_id_by_username("user2")
    print(f"Resolved database IDs dynamically: user1={user1_id}, user2={user2_id}")

    # Ensure clean database state for target_schema before test
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET target_schema = NULL WHERE id IN (?, ?)", (user1_id, user2_id))
        conn.commit()

    # Create temporary schemas for success cases
    setup_temp_schema("maximo.json")
    setup_temp_schema("sap.json")

    try:
        # A. Validation Checks
        print("\n[Running Validation Checks]")

        # - Empty string
        try:
            update_user_target_schema(user1_id, "")
            raise AssertionError("Failed to raise ValueError for empty schema name")
        except ValueError as e:
            print(f"  [OK] Empty string validation caught: {e}")

        # - Whitespace only
        try:
            update_user_target_schema(user1_id, "   ")
            raise AssertionError("Failed to raise ValueError for whitespace-only schema name")
        except ValueError as e:
            print(f"  [OK] Whitespace validation caught: {e}")

        # - Non-string values
        try:
            update_user_target_schema(user1_id, 123)  # type: ignore
            raise AssertionError("Failed to raise ValueError for non-string schema name")
        except ValueError as e:
            print(f"  [OK] Non-string validation caught: {e}")

        # - Invalid extension
        try:
            update_user_target_schema(user1_id, "maximo.txt")
            raise AssertionError("Failed to raise ValueError for invalid extension")
        except ValueError as e:
            print(f"  [OK] Invalid extension validation caught: {e}")

        # - Missing schema files (file does not exist on disk)
        try:
            update_user_target_schema(user1_id, "random.json")
            raise AssertionError("Failed to raise ValueError for missing schema file")
        except ValueError as e:
            print(f"  [OK] Missing schema file validation caught: {e}")

        # - Nonexistent user ID
        non_existent_id = 999999
        try:
            update_user_target_schema(non_existent_id, "maximo.json")
            raise AssertionError("Failed to raise ValueError for non-existent user ID")
        except ValueError as e:
            print(f"  [OK] Non-existent user ID validation caught: {e}")

        # B. Success Cases & Isolation
        print("\n[Running Success and Isolation Checks]")

        # Initial state checks
        assert get_user_target_schema(user1_id) is None
        assert get_user_target_schema(user2_id) is None
        print("  [OK] Initial schemas are NULL.")

        # Save maximo.json for user1
        print("Updating user1 schema to 'maximo.json'...")
        update_user_target_schema(user1_id, "maximo.json")
        
        # Verify isolation: user2 must still be None
        assert get_user_target_schema(user1_id) == "maximo.json", "user1 schema did not save correctly"
        assert get_user_target_schema(user2_id) is None, "Isolation violation: updating user1 affected user2"
        print("  [OK] user1 saved successfully. user2 is still isolated (NULL).")

        # Save sap.json for user2
        print("Updating user2 schema to 'sap.json'...")
        update_user_target_schema(user2_id, "sap.json")

        # Verify isolation: user1 must remain "maximo.json"
        assert get_user_target_schema(user1_id) == "maximo.json", "user1 schema was unexpectedly modified"
        assert get_user_target_schema(user2_id) == "sap.json", "user2 schema did not save correctly"
        print("  [OK] user2 saved successfully. user1 remains unaffected.")

        # C. Persistence Check (Close and Reopen)
        print("\n[Running Persistence Checks]")
        # We perform a new SELECT query to confirm data persists in SQLite
        schema_user1_persisted = get_user_target_schema(user1_id)
        schema_user2_persisted = get_user_target_schema(user2_id)
        assert schema_user1_persisted == "maximo.json", "user1 schema failed persistence check"
        assert schema_user2_persisted == "sap.json", "user2 schema failed persistence check"
        print("  [OK] Values successfully persisted and retrieved.")

        # D. Storage Verification (Assert NO prefix path or schema contents stored)
        print("\n[Running Storage Format Verification]")
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT target_schema FROM users WHERE id = ?", (user1_id,))
            row1 = cursor.fetchone()
            assert row1 is not None
            raw_val1 = row1["target_schema"]
            
            # Assert only the filename is in the database column
            assert raw_val1 == "maximo.json", f"Expected exact value 'maximo.json', found: {raw_val1}"
            assert "schemas/" not in raw_val1, "Invalid path prefix stored in database column"
            assert "/" not in raw_val1 and "\\" not in raw_val1, "Invalid directory separators in stored database value"
            print(f"  [OK] Database column value verified: exactly '{raw_val1}' (no prefix, no path).")

        print("\n=== All Target Schema Persistence Tests Passed! ===")

    finally:
        cleanup_temp_schemas()


if __name__ == "__main__":
    try:
        run_tests()
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
