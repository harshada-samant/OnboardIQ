"""
tests/test_schema_selection_service.py
----------------------------------------
Unit tests verifying the schema service layer orchestration, options listing,
selection updates, no-op cases, invalid ID propagation, logging verification,
refresh failure handling, switching, and corrupted database values.
"""

import sys
import os
import io
import shutil
import tempfile
from pathlib import Path
from contextlib import redirect_stdout

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import get_db_connection, update_user_target_schema
from backend.schema_service import (
    get_schema_options,
    get_user_schema_selection,
    update_user_schema_selection
)

def get_user_id(username: str) -> int:
    """Dynamically resolves database ID for seed user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]

def test_service_all():
    print("=== Testing Schema Selection Service Layer ===")

    # 1. Setup isolated schemas directory redirect
    original_schemas_dir = config.SCHEMAS_DIR
    temp_schemas_dir = Path(tempfile.mkdtemp())
    config.SCHEMAS_DIR = temp_schemas_dir
    print(f"Isolated SCHEMAS_DIR redirected to temp folder: {temp_schemas_dir}")

    # 2. Test isolation requirements: store original TARGET_SCHEMA_PATH
    original_target_schema_path = config.TARGET_SCHEMA_PATH

    # Resolve database IDs
    user1_id = get_user_id("user1")
    user2_id = get_user_id("user2")

    try:
        # -------------------------------------------------------------
        # A. SCHEMA OPTIONS
        # -------------------------------------------------------------
        print("\n[Testing Schema Options]")
        
        # Empty schemas directory
        assert get_schema_options() == []
        print("  [OK] Empty directory returns [].")

        # Single file
        (temp_schemas_dir / "maximo.json").write_text("{}", encoding="utf-8")
        assert get_schema_options() == ["maximo.json"]
        print("  [OK] Single schema options listed.")

        # Alphabetical sorting
        (temp_schemas_dir / "sap.json").write_text("{}", encoding="utf-8")
        (temp_schemas_dir / "oracle.json").write_text("{}", encoding="utf-8")
        (temp_schemas_dir / "not_json.txt").write_text("hello", encoding="utf-8")
        
        expected_options = ["maximo.json", "oracle.json", "sap.json"]
        assert get_schema_options() == expected_options
        print(f"  [OK] Sorted options: {get_schema_options()}")

        # -------------------------------------------------------------
        # B. CURRENT SELECTION
        # -------------------------------------------------------------
        print("\n[Testing Current Selection Retrieval]")
        
        # Reset DB values to NULL
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET target_schema = NULL WHERE id IN (?, ?)", (user1_id, user2_id))
            conn.commit()

        # User without schema
        assert get_user_schema_selection(user1_id) is None
        print("  [OK] get_user_schema_selection returns None for NULL selection.")

        # User with schema
        update_user_target_schema(user1_id, "maximo.json")
        assert get_user_schema_selection(user1_id) == "maximo.json"
        print("  [OK] get_user_schema_selection retrieves filename correctly.")

        # -------------------------------------------------------------
        # C. SUCCESSFUL & NO-OP UPDATES
        # -------------------------------------------------------------
        print("\n[Testing Successful and No-Op Updates]")
        
        # Set baseline target schema path
        config.TARGET_SCHEMA_PATH = Path("baseline_target.json")

        # Success case: Update to sap.json
        print("Updating user1 schema to 'sap.json'...")
        res_update = update_user_schema_selection(user1_id, "sap.json")
        assert res_update is True
        assert get_user_schema_selection(user1_id) == "sap.json"
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json"
        print("  [OK] Update returned True and config path updated.")

        # No-Op Case: Update to same sap.json
        print("Updating user1 schema to same 'sap.json' (No-Op)...")
        res_noop = update_user_schema_selection(user1_id, "sap.json")
        assert res_noop is True
        assert get_user_schema_selection(user1_id) == "sap.json"
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json"
        print("  [OK] No-Op Update succeeded with True, no config corruption.")

        # -------------------------------------------------------------
        # D. INVALID UPDATE & USER ID (VALUEERROR PROPAGATION)
        # -------------------------------------------------------------
        print("\n[Testing Invalid Updates & User ID Behavior]")

        # Invalid schema name validation error propagation
        try:
            update_user_schema_selection(user1_id, "missing_schema.json")
            raise AssertionError("Failed to raise ValueError for missing schema file")
        except ValueError as e:
            print(f"  [OK] Invalid schema name ValueError propagated: {e}")

        # Invalid user ID (Value Error propagation, no updates, no config change)
        invalid_user_id = 999999
        config.TARGET_SCHEMA_PATH = temp_schemas_dir / "sap.json"
        try:
            update_user_schema_selection(invalid_user_id, "sap.json")
            raise AssertionError("Failed to raise ValueError for invalid user ID")
        except ValueError as e:
            print(f"  [OK] Invalid user ID ValueError propagated: {e}")
            assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json", "Config was modified on failure"
            print("  [OK] Database and configuration remained unchanged.")

        # -------------------------------------------------------------
        # E. LOGGING VERIFICATION
        # -------------------------------------------------------------
        print("\n[Testing Logging Output Verification]")

        # Capture output for success log
        f = io.StringIO()
        with redirect_stdout(f):
            update_user_schema_selection(user1_id, "oracle.json")
        out = f.getvalue()
        expected_log = f"[SCHEMA] Updated schema selection for user1: oracle.json\n"
        assert expected_log in out, f"Expected log: {repr(expected_log)}, found: {repr(out)}"
        print("  [OK] Correct success log emitted on successful update.")

        # -------------------------------------------------------------
        # F. RUNTIME REFRESH FAILURE & LOGGING
        # -------------------------------------------------------------
        print("\n[Testing Runtime Refresh Failure and Logging]")
        
        # Setup: schema file exists, update succeeds
        (temp_schemas_dir / "temp_schema.json").write_text("{}", encoding="utf-8")
        update_user_schema_selection(user1_id, "temp_schema.json")
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "temp_schema.json"
        
        # Mock configure_user_schema to return False
        import unittest.mock
        f_fail = io.StringIO()
        with unittest.mock.patch("backend.schema_service.configure_user_schema", return_value=False):
            with redirect_stdout(f_fail):
                res_refresh_fail = update_user_schema_selection(user1_id, "temp_schema.json")
        out_fail = f_fail.getvalue()
        
        # Assert service returns False, DB is committed, but config is untouched (Option A)
        assert res_refresh_fail is False
        assert get_user_schema_selection(user1_id) == "temp_schema.json"
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "temp_schema.json" # remains unchanged
        
        expected_fail_log = f"[SCHEMA] Failed to configure runtime schema for user1: temp_schema.json\n"
        assert expected_fail_log in out_fail, f"Expected fail log: {repr(expected_fail_log)}, found: {repr(out_fail)}"
        print("  [OK] Service returned False on refresh failure, DB committed, config untouched, fail log emitted.")

        # -------------------------------------------------------------
        # G. USER SWITCHING RECONFIGURATION
        # -------------------------------------------------------------
        print("\n[Testing Service User Switching Reconfiguration]")
        
        update_user_schema_selection(user1_id, "oracle.json")
        update_user_schema_selection(user2_id, "sap.json")

        # Re-update User1
        update_user_schema_selection(user1_id, "oracle.json")
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "oracle.json"
        
        # Re-update User2
        update_user_schema_selection(user2_id, "sap.json")
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json"
        
        # Re-update User1 again
        update_user_schema_selection(user1_id, "oracle.json")
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "oracle.json"
        print("  [OK] Service switching updates config.TARGET_SCHEMA_PATH correctly each time.")

        # -------------------------------------------------------------
        # H. CORRUPTED / LEGACY DB RECORDS
        # -------------------------------------------------------------
        print("\n[Testing Corrupted and Legacy DB Records]")
        
        # Directly write corrupted values into the database to bypass validation checks
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET target_schema = '../secret.json' WHERE id = ?", (user1_id,))
            conn.commit()

        # get_user_schema_selection returns the raw value
        assert get_user_schema_selection(user1_id) == "../secret.json"
        print("  [OK] Raw corrupted database value returned correctly.")

        # resolve_user_schema_path and configure_user_schema fail safely
        from backend.schema_manager import configure_user_schema
        config.TARGET_SCHEMA_PATH = temp_schemas_dir / "sap.json"
        
        assert configure_user_schema(user1_id) is False
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json" # unchanged
        print("  [OK] Configuration manager fails safely on legacy corrupted values with no crashes.")

        print("\n=== All Schema Selection Service Layer Tests Passed! ===")

    finally:
        # Cleanup isolated schemas directory
        config.SCHEMAS_DIR = original_schemas_dir
        shutil.rmtree(temp_schemas_dir)
        print("Restored original SCHEMAS_DIR and cleaned up temp files.")

        # Restore original TARGET_SCHEMA_PATH (test isolation)
        config.TARGET_SCHEMA_PATH = original_target_schema_path
        print(f"Restored TARGET_SCHEMA_PATH to: {config.TARGET_SCHEMA_PATH}")

if __name__ == "__main__":
    try:
        test_service_all()
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
