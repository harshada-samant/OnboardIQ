"""
tests/test_execution_store.py
------------------------------
Unit tests verifying the thread-safe execution store, step transition API,
structured log formatting, concurrency locks, and detailed failure handling.
"""

import sys
import os
import json
import shutil
import tempfile
import unittest.mock
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import get_db_connection, update_user_target_schema
from backend.workspace import ensure_user_workspace
from backend.execution_store import (
    execution_store,
    start_execution,
    transition_step,
    complete_execution,
    get_execution,
    is_user_running,
    store_lock
)
from backend.pipeline_executor import run_pipeline

def get_user_id(username: str) -> int:
    """Dynamically resolves database ID for seed user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]


def test_store_operations():
    print("\n[Testing Store Operations]")
    
    # Reset store
    with store_lock:
        execution_store.clear()

    exec_id = "test-exec-1"
    user_id = 42
    
    # Start execution
    start_execution(exec_id, user_id)
    record = get_execution(exec_id)
    assert record is not None
    assert record["user_id"] == user_id
    assert record["status"] == "running"
    assert record["progress"] == 0
    assert record["current_step"] == "Init"
    assert len(record["logs"]) == 0
    
    # Transition steps
    transition_step(exec_id, "Discovery", 10, "Discovery agent trigger")
    record = get_execution(exec_id)
    assert record["progress"] == 10
    assert record["current_step"] == "Discovery"
    assert len(record["logs"]) == 1
    assert record["logs"][0]["step"] == "Discovery"
    assert record["logs"][0]["message"] == "Discovery agent trigger"
    assert "timestamp" in record["logs"][0]
    
    # Transition again
    transition_step(exec_id, "Profiling", 30, "Profiling agent trigger")
    record = get_execution(exec_id)
    assert record["progress"] == 30
    assert record["current_step"] == "Profiling"
    assert len(record["logs"]) == 2
    
    # Complete execution
    complete_execution(exec_id, "completed")
    record = get_execution(exec_id)
    assert record["status"] == "completed"
    assert record["progress"] == 100
    assert record["current_step"] == "Completed"
    assert len(record["logs"]) == 3
    assert "Pipeline execution completed" in record["logs"][-1]["message"]
    print("  [OK] Store operations verified (start, transition, get, complete).")


def test_concurrency_lock():
    print("\n[Testing Concurrency Locks]")
    
    # Reset store
    with store_lock:
        execution_store.clear()

    user1_id = get_user_id("user1")
    user2_id = get_user_id("user2")

    # Manually start run for user1
    exec1_id = "user1-running"
    start_execution(exec1_id, user1_id)
    
    # Verify user1 is marked as running, user2 is not
    assert is_user_running(user1_id) is True
    assert is_user_running(user2_id) is False
    
    # Try calling run_pipeline for user1: should fail immediately due to lock
    exec_reject_id = run_pipeline(user1_id)
    record_reject = get_execution(exec_reject_id)
    assert record_reject is not None
    assert record_reject["status"] == "failed"
    assert "already has an active pipeline execution running" in record_reject["logs"][-1]["message"]
    print("  [OK] Concurrency lock correctly rejected duplicate run for User 1.")

    # complete user1 execution
    complete_execution(exec1_id, "completed")
    assert is_user_running(user1_id) is False
    print("  [OK] Lock released after execution completed.")


def test_step_by_step_failure_handling():
    print("\n[Testing Step-by-Step Failure Handling]")

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

    user1_id = get_user_id("user1")

    # Setup temp schemas and uploads
    (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")
    update_user_target_schema(user1_id, "target_schema.json")

    ensure_user_workspace("user1")
    
    # Seed uploads folder
    uploads_dir = temp_workspaces_dir / "users" / "user1" / "uploads"
    (uploads_dir / "assets.csv").write_text("asset_no,asset_name\nA01,Pump", encoding="utf-8")

    # Setup active configuration paths
    config.set_user_workspace("user1")
    config.TARGET_SCHEMA_PATH = temp_schemas_dir / "target_schema.json"

    # Reset store
    with store_lock:
        execution_store.clear()

    # Mock Profiling Agent to raise a simulated exception
    with unittest.mock.patch("backend.pipeline_executor.run_discovery_agent") as mock_disc, \
         unittest.mock.patch("backend.pipeline_executor.run_profiling_agent", side_effect=RuntimeError("Simulated profiling crash")) as mock_prof:
        
        exec_id = run_pipeline(user1_id)
        
        # Verify profiler was called and exception triggered
        mock_disc.assert_called_once()
        mock_prof.assert_called_once()

    # Verify execution store status is failed
    record = get_execution(exec_id)
    assert record is not None
    assert record["status"] == "failed"
    assert record["current_step"] == "Failed"
    
    # Assert error detail recorded in terminal log entry
    assert "Simulated profiling crash" in record["logs"][-1]["message"]
    
    # Verify partial progress context snapshot exists in workspace
    expected_snapshot = Path(config.OUTPUT_DIR) / "context_snapshot.json"
    assert expected_snapshot.is_file(), f"Missing failure progress context snapshot at {expected_snapshot}"

    # Verify results JSON log was written
    expected_json_path = Path(config.OUTPUT_DIR) / f"execution_{exec_id}.json"
    assert expected_json_path.is_file(), f"Missing failure results JSON log at {expected_json_path}"
    
    with open(expected_json_path, "r", encoding="utf-8") as f:
        export_data = json.load(f)
        
    assert export_data["execution_id"] == exec_id
    assert export_data["status"] == "failed"
    assert "Simulated profiling crash" in export_data["error_message"]
    assert len(export_data["log_milestones"]) > 0
    print("  [OK] Failure handled step-by-step: terminal status, logs, context snapshot, and export JSON verified.")

    # Cleanup temp paths
    config.WORKSPACES_DIR = original_workspaces_dir
    config.SCHEMAS_DIR = original_schemas_dir
    config.TARGET_SCHEMA_PATH = original_target_schema_path
    config.INPUT_DIR = original_input_dir
    config.OUTPUT_DIR = original_output_dir
    
    shutil.rmtree(temp_workspaces_dir)
    shutil.rmtree(temp_schemas_dir)


if __name__ == "__main__":
    try:
        print("=== Running Execution Store & Orchestrator Unit Tests ===")
        test_store_operations()
        test_concurrency_lock()
        test_step_by_step_failure_handling()
        print("\n=== All execution_store Tests Passed! ===")
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
