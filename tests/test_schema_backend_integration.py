"""
tests/test_schema_backend_integration.py
-----------------------------------------
Integration tests validating target schema backend integration, discovery,
resolution, traversal protection, user switching, deleted schema recovery,
first login, and middleware reconfiguration.
"""

import sys
import os
import shutil
import tempfile
import asyncio
from pathlib import Path
from fastapi import Request
import nicegui
mock_user_storage = {}
nicegui.storage.Storage.user = property(lambda self: mock_user_storage)
from nicegui import app

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import (
    get_db_connection,
    get_username_by_id,
    get_user_target_schema,
    update_user_target_schema,
    authenticate_user
)
from backend.schema_manager import (
    get_available_schemas,
    resolve_user_schema_path,
    configure_user_schema
)
from frontend.middleware import auth_middleware

# Helper to dynamically retrieve user IDs
def get_user_id(username: str) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]

async def run_middleware_simulation(user_id: int, username: str):
    """Simulates request-time middleware execution for a user."""
    # Mock NiceGUI session storage
    mock_user_storage.clear()
    mock_user_storage.update({
        "authenticated": True,
        "user_id": user_id,
        "username": username
    })
    
    # Simple Mock Request
    class MockRequest:
        def __init__(self):
            self.url = type('URL', (), {'path': '/'})()
            
    class MockResponse:
        def __init__(self):
            self.status_code = 200

    async def mock_call_next(request):
        return MockResponse()

    # Preserve current config.SCHEMAS_DIR (temp_schemas_dir)
    target_schemas_dir = config.SCHEMAS_DIR

    import unittest.mock
    def mock_set_user_workspace(uname):
        config.SCHEMAS_DIR = target_schemas_dir
        config.OUTPUT_DIR = config.WORKSPACES_DIR / "users" / uname / "outputs"

    with unittest.mock.patch("config.set_user_workspace", side_effect=mock_set_user_workspace):
        await auth_middleware(MockRequest(), mock_call_next)

def test_all():
    print("=== Testing Target Schema Backend Integration ===")
    
    # 1. Setup temporary isolated schemas directory
    original_schemas_dir = config.SCHEMAS_DIR
    temp_schemas_dir = Path(tempfile.mkdtemp())
    config.SCHEMAS_DIR = temp_schemas_dir
    print(f"Isolated SCHEMAS_DIR redirected to temp folder: {temp_schemas_dir}")

    # Resolve database IDs dynamically
    user1_id = get_user_id("user1")
    user2_id = get_user_id("user2")
    print(f"Dynamically resolved IDs: user1={user1_id}, user2={user2_id}")

    try:
        # -------------------------------------------------------------
        # A. SCHEMA DISCOVERY TESTS
        # -------------------------------------------------------------
        print("\n[Testing Schema Discovery]")
        
        # Scenario: Empty schemas directory
        assert get_available_schemas() == []
        print("  [OK] Empty schemas directory returns [].")

        # Scenario: One schema file
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")
        assert get_available_schemas() == ["target_schema.json"]
        print("  [OK] Single schema file detected correctly.")

        # Scenario: Multiple schema files + alphabetical sorting
        (temp_schemas_dir / "sap.json").write_text("{}", encoding="utf-8")
        (temp_schemas_dir / "oracle.json").write_text("{}", encoding="utf-8")
        (temp_schemas_dir / "not_a_schema.txt").write_text("hello", encoding="utf-8") # non-json file
        
        expected_schemas = ["oracle.json", "sap.json", "target_schema.json"]
        assert get_available_schemas() == expected_schemas
        print(f"  [OK] Multiple schema files returned sorted: {get_available_schemas()}")

        # -------------------------------------------------------------
        # B. SCHEMA RESOLUTION & TRAVERSAL PROTECTION TESTS
        # -------------------------------------------------------------
        print("\n[Testing Active Schema Resolution]")
        
        # Setup: Clear users schemas in database first
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET target_schema = NULL WHERE id IN (?, ?)", (user1_id, user2_id))
            conn.commit()

        # Scenario: User without schema selected
        assert resolve_user_schema_path(user1_id) is None
        print("  [OK] NULL schema resolved to None.")

        # Scenario: User with schema selected
        update_user_target_schema(user1_id, "target_schema.json")
        resolved = resolve_user_schema_path(user1_id)
        assert resolved == temp_schemas_dir / "target_schema.json"
        print(f"  [OK] Valid schema resolved to: {resolved}")

        # Scenario: User pointing to deleted schema file
        os.remove(temp_schemas_dir / "target_schema.json")
        assert resolve_user_schema_path(user1_id) is None
        print("  [OK] Missing schema file resolved to None safely.")

        # Recreate target_schema.json for subsequent tests
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")

        # Scenario: Path Traversal Protection
        # Bypass update validator via direct DB insert to test resolution guard
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # Test traversal name
            cursor.execute("UPDATE users SET target_schema = '../target_schema.json' WHERE id = ?", (user1_id,))
            conn.commit()
        
        # Verify resolution rejects traversal name
        assert resolve_user_schema_path(user1_id) is None
        print("  [OK] Traversal value '../target_schema.json' rejected correctly.")

        # Test absolute path name
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET target_schema = 'C:\\temp\\schema.json' WHERE id = ?", (user1_id,))
            conn.commit()
        assert resolve_user_schema_path(user1_id) is None
        print("  [OK] Absolute path traversal value rejected correctly.")

        # Restore valid target_schema.json schema mapping
        update_user_target_schema(user1_id, "target_schema.json")

        # -------------------------------------------------------------
        # C. RUNTIME CONFIGURATION TESTS
        # -------------------------------------------------------------
        print("\n[Testing Runtime Configuration]")
        
        # Baseline target schema path
        config.TARGET_SCHEMA_PATH = Path("baseline_target.json")

        # Case: User with NULL schema
        config.TARGET_SCHEMA_PATH = Path("baseline_target.json")
        assert configure_user_schema(user2_id) is False
        assert config.TARGET_SCHEMA_PATH == Path("baseline_target.json"), "Path should not be overwritten"
        print("  [OK] configure_user_schema returns False on NULL schema, leaving baseline intact.")

        # Case: User with valid schema
        assert configure_user_schema(user1_id) is True
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "target_schema.json"
        print("  [OK] configure_user_schema returns True on valid schema, updating config.")

        # Case: User with deleted schema (Option A behavior check)
        os.remove(temp_schemas_dir / "target_schema.json")
        # configure_user_schema should return False and config.TARGET_SCHEMA_PATH should NOT be modified
        last_valid_path = config.TARGET_SCHEMA_PATH
        assert configure_user_schema(user1_id) is False
        assert config.TARGET_SCHEMA_PATH == last_valid_path, "Option A violation: config path modified on failure"
        print("  [OK] Option A verified: configure_user_schema returns False on deleted schema, target path remains unchanged.")

        # Recreate target_schema.json
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")

        # -------------------------------------------------------------
        # D. USER SWITCHING RECONFIGURATION TESTS
        # -------------------------------------------------------------
        print("\n[Testing Runtime Path Reconfiguration on User Switching]")
        
        update_user_target_schema(user1_id, "target_schema.json")
        update_user_target_schema(user2_id, "sap.json")

        # Switch User1
        assert configure_user_schema(user1_id) is True
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "target_schema.json"
        
        # Switch User2
        assert configure_user_schema(user2_id) is True
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json"
        
        # Switch User1 again
        assert configure_user_schema(user1_id) is True
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "target_schema.json"
        print("  [OK] Sequential configuration updates target path correctly with no stale states.")

        # -------------------------------------------------------------
        # E. AUTHENTICATION & LOGIN COMPATIBILITY TESTS
        # -------------------------------------------------------------
        print("\n[Testing Authentication Compatibility]")
        
        # Login with valid schema
        res_valid = authenticate_user("user1", "password123")
        assert res_valid is not None
        assert res_valid["target_schema"] == "target_schema.json"
        print("  [OK] authenticate_user succeeds with valid schema.")

        # Login with NULL schema
        res_null = authenticate_user("user2", "password123")
        assert res_null is not None
        assert res_null["target_schema"] == "sap.json"
        print("  [OK] authenticate_user succeeds with NULL/other schema.")

        # Login with deleted schema
        os.remove(temp_schemas_dir / "target_schema.json")
        res_deleted = authenticate_user("user1", "password123")
        assert res_deleted is not None
        print("  [OK] authenticate_user succeeds even if schema file is deleted.")
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")

        # -------------------------------------------------------------
        # F. FIRST LOGIN / NO SCHEMA SCENARIO
        # -------------------------------------------------------------
        print("\n[Testing First Login Scenario]")
        
        # Setup: Create new user with target_schema = NULL directly
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = 'new_user_1'")
            conn.commit()
            
            from backend.database import hash_password
            pwd_hash = hash_password("password123")
            cursor.execute("INSERT INTO users (username, password_hash) VALUES ('new_user_1', ?)", (pwd_hash,))
            conn.commit()

        new_user_id = get_user_id("new_user_1")

        # Verify authentication compatibility and session keys presence
        user_auth = authenticate_user("new_user_1", "password123")
        assert user_auth is not None
        assert user_auth["username"] == "new_user_1"
        assert user_auth["target_schema"] is None
        print("  [OK] New user authenticated successfully with NULL schema.")

        # Verify configure_user_schema returns False safely on first login
        config.TARGET_SCHEMA_PATH = Path("baseline_target.json")
        res_conf = configure_user_schema(new_user_id)
        assert res_conf is False
        assert config.TARGET_SCHEMA_PATH == Path("baseline_target.json")
        print("  [OK] configure_user_schema returns False on first login without exceptions or modifying baseline.")

        # Clean up new_user_1
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE username = 'new_user_1'")
            conn.commit()

        # -------------------------------------------------------------
        # G. MIDDLEWARE RECONFIGURATION SIMULATION
        # -------------------------------------------------------------
        print("\n[Testing Middleware Reconfiguration Simulation]")
        
        # Test baseline
        config.TARGET_SCHEMA_PATH = Path("baseline_target.json")

        # 1. User1 requests
        asyncio.run(run_middleware_simulation(user1_id, "user1"))
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "target_schema.json"
        assert config.OUTPUT_DIR == config.WORKSPACES_DIR / "users" / "user1" / "outputs"
        print("  [OK] Middleware executed: User1 workspace and target schema loaded.")

        # 2. User2 requests
        asyncio.run(run_middleware_simulation(user2_id, "user2"))
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "sap.json"
        assert config.OUTPUT_DIR == config.WORKSPACES_DIR / "users" / "user2" / "outputs"
        print("  [OK] Middleware executed: User2 workspace and target schema switched correctly.")

        # 3. User1 requests again
        asyncio.run(run_middleware_simulation(user1_id, "user1"))
        assert config.TARGET_SCHEMA_PATH == temp_schemas_dir / "target_schema.json"
        assert config.OUTPUT_DIR == config.WORKSPACES_DIR / "users" / "user1" / "outputs"
        print("  [OK] Middleware executed: User1 workspace and target schema switched back successfully.")

        # -------------------------------------------------------------
        # H. INVALID USER ID ERROR HANDLING
        # -------------------------------------------------------------
        print("\n[Testing Invalid User ID Error Handling]")
        assert configure_user_schema(999999) is False
        print("  [OK] Unknown user ID configure_user_schema call handled gracefully, returned False.")

        print("\n=== All Target Schema Backend Integration Tests Passed! ===")

    finally:
        # Restore configuration and clean temp directory
        config.SCHEMAS_DIR = original_schemas_dir
        shutil.rmtree(temp_schemas_dir)
        print("Restored original SCHEMAS_DIR and cleaned up temp files.")

if __name__ == "__main__":
    try:
        test_all()
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
