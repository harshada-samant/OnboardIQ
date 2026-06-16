"""
tests/test_pipeline_service.py
-------------------------------
Unit tests verifying the pipeline service layer, background execution,
missing execution ID handling, plain uploads directory listing, and FastAPI endpoints.
"""

import sys
import os
import json
import shutil
import tempfile
import time
import unittest.mock
from pathlib import Path
from fastapi.testclient import TestClient

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import get_db_connection, update_user_target_schema
from backend.workspace import ensure_user_workspace
from backend.execution_store import execution_store, store_lock, get_execution
from backend.pipeline_service import (
    start_pipeline,
    get_execution_status,
    get_execution_logs,
    get_user_source_files
)
from nicegui import app

client = TestClient(app)

def get_user_id(username: str) -> int:
    """Dynamically resolves database ID for seed user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]


def test_service_polling_and_threading():
    print("\n[Testing Background Execution & Polling]")
    
    # Reset store
    with store_lock:
        execution_store.clear()

    user1_id = get_user_id("user1")

    # Setup isolated directories
    original_workspaces_dir = config.WORKSPACES_DIR
    original_schemas_dir = config.SCHEMAS_DIR
    original_target_schema_path = config.TARGET_SCHEMA_PATH
    original_input_dir = config.INPUT_DIR
    original_output_dir = config.OUTPUT_DIR

    temp_workspaces_dir = Path(tempfile.mkdtemp())
    temp_schemas_dir = Path(tempfile.mkdtemp())
    
    config.WORKSPACES_DIR = temp_workspaces_dir
    config.SCHEMAS_DIR = temp_schemas_dir

    # Setup temp schemas and uploads
    (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")
    update_user_target_schema(user1_id, "target_schema.json")

    ensure_user_workspace("user1")
    uploads_dir = temp_workspaces_dir / "users" / "user1" / "uploads"
    (uploads_dir / "assets.csv").write_text("asset_no,asset_name\nA01,Pump", encoding="utf-8")

    # Setup active configuration paths
    config.set_user_workspace("user1")
    config.TARGET_SCHEMA_PATH = temp_schemas_dir / "target_schema.json"

    # Mock all agents to ensure fast background run
    with unittest.mock.patch("backend.pipeline_executor.run_discovery_agent") as mock_disc, \
         unittest.mock.patch("backend.pipeline_executor.run_profiling_agent") as mock_prof, \
         unittest.mock.patch("backend.pipeline_executor.run_mapping_agent") as mock_map, \
         unittest.mock.patch("backend.pipeline_executor.run_specification_agent") as mock_spec, \
         unittest.mock.patch("backend.pipeline_executor.run_readiness_agent") as mock_read, \
         unittest.mock.patch("backend.pipeline_executor.run_planning_agent") as mock_plan, \
         unittest.mock.patch("backend.pipeline_executor.run_migration_generator_agent"), \
         unittest.mock.patch("backend.pipeline_executor.run_migration_reviewer_agent"), \
         unittest.mock.patch("backend.pipeline_executor.run_migration_repair_agent"), \
         unittest.mock.patch("backend.pipeline_executor.run_migration_execution_agent"), \
         unittest.mock.patch("backend.pipeline_executor.run_migration_validation_agent"), \
         unittest.mock.patch("backend.pipeline_executor.run_migration_approval_agent"):

        exec_id = start_pipeline(user1_id)
        
        # Verify execution_id is returned immediately
        assert exec_id is not None
        assert isinstance(exec_id, str)
        
        # Poll status until completed (since it runs in background thread)
        max_retries = 20
        status_data = None
        for _ in range(max_retries):
            status_data = get_execution_status(exec_id)
            if status_data["status"] == "completed":
                break
            time.sleep(0.1)

        assert status_data["status"] == "completed"
        assert status_data["progress"] == 100
        assert status_data["current_step"] == "Completed"
        
        # Get logs
        logs = get_execution_logs(exec_id)
        assert len(logs) > 0
        assert logs[-1]["step"] == "Completed"
        print("  [OK] start_pipeline runs asynchronously. Status and logs polled successfully.")

    # Cleanup temp paths
    config.WORKSPACES_DIR = original_workspaces_dir
    config.SCHEMAS_DIR = original_schemas_dir
    config.TARGET_SCHEMA_PATH = original_target_schema_path
    config.INPUT_DIR = original_input_dir
    config.OUTPUT_DIR = original_output_dir
    shutil.rmtree(temp_workspaces_dir)
    shutil.rmtree(temp_schemas_dir)


def test_missing_id_handling():
    print("\n[Testing Missing ID Handling]")
    
    # Reset store
    with store_lock:
        execution_store.clear()

    unknown_id = "non-existent-uuid"
    
    # Assert get_execution_status returns default failed dict
    status = get_execution_status(unknown_id)
    assert status["status"] == "failed"
    assert status["progress"] == 0
    assert status["current_step"] == "Unknown"
    assert "not found in memory" in status["error_message"]
    
    # Assert get_execution_logs returns empty list
    logs = get_execution_logs(unknown_id)
    assert logs == []
    print("  [OK] Missing execution ID returns safe failed/empty response.")


def test_get_user_source_files():
    print("\n[Testing Plain Source File Listing]")
    
    # Setup isolated directories
    original_workspaces_dir = config.WORKSPACES_DIR
    temp_workspaces_dir = Path(tempfile.mkdtemp())
    config.WORKSPACES_DIR = temp_workspaces_dir

    user1_id = get_user_id("user1")
    ensure_user_workspace("user1")
    uploads_dir = temp_workspaces_dir / "users" / "user1" / "uploads"
    
    # Create test uploads
    (uploads_dir / "assets.csv").write_text("col1,col2\nval1,val2", encoding="utf-8")
    (uploads_dir / "locations.json").write_text("{}", encoding="utf-8")
    
    # Call list API
    files = get_user_source_files(user1_id)
    assert len(files) == 2
    assert files[0]["name"] == "assets.csv"
    assert files[0]["size"] == len((uploads_dir / "assets.csv").read_bytes())
    assert "modified" in files[0]
    
    assert files[1]["name"] == "locations.json"
    assert files[1]["size"] == len((uploads_dir / "locations.json").read_bytes())
    
    # Verify non-existent user error propagation
    try:
        get_user_source_files(999999)
        raise AssertionError("Failed to raise error for unknown user ID")
    except ValueError as e:
        print(f"  [OK] Correctly raised ValueError on unknown user: {e}")

    # Cleanup
    config.WORKSPACES_DIR = original_workspaces_dir
    shutil.rmtree(temp_workspaces_dir)
    print("  [OK] Plain uploads directory contents listed correctly.")


def test_fastapi_rest_endpoints():
    print("\n[Testing FastAPI Thin Route Wrappers]")
    
    # Reset store
    with store_lock:
        execution_store.clear()
        
    user1_id = get_user_id("user1")
    
    # Mock start_pipeline function
    with unittest.mock.patch("backend.pipeline_service.start_pipeline", return_value="mock-uuid-123") as mock_start:
        response = client.post(f"/api/pipeline/start/{user1_id}")
        assert response.status_code == 200
        assert response.json() == {"execution_id": "mock-uuid-123"}
        mock_start.assert_called_once_with(user1_id)

    # Test status endpoint
    with unittest.mock.patch("backend.pipeline_service.get_execution_status", return_value={"status": "completed", "progress": 100, "current_step": "Completed"}) as mock_status:
        response = client.get("/api/pipeline/status/mock-uuid-123")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        mock_status.assert_called_once_with("mock-uuid-123")

    # Test logs endpoint
    with unittest.mock.patch("backend.pipeline_service.get_execution_logs", return_value=[{"step": "Discovery", "message": "Triggered"}]) as mock_logs:
        response = client.get("/api/pipeline/logs/mock-uuid-123")
        assert response.status_code == 200
        assert response.json()[0]["step"] == "Discovery"
        mock_logs.assert_called_once_with("mock-uuid-123")

    # Test files endpoint
    with unittest.mock.patch("backend.pipeline_service.get_user_source_files", return_value=[{"name": "test.csv"}]) as mock_files:
        response = client.get(f"/api/pipeline/files/{user1_id}")
        assert response.status_code == 200
        assert response.json()[0]["name"] == "test.csv"
        mock_files.assert_called_once_with(user1_id)
        
    print("  [OK] All FastAPI endpoints wrap the Python service functions correctly.")


if __name__ == "__main__":
    try:
        print("=== Running Pipeline Service Layer Unit Tests ===")
        test_service_polling_and_threading()
        test_missing_id_handling()
        test_get_user_source_files()
        test_fastapi_rest_endpoints()
        print("\n=== All pipeline_service Tests Passed! ===")
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
