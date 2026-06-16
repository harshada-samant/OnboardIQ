"""
tests/test_pipeline_executor.py
---------------------------------
Unit tests verifying the pipeline executor module, controlled failure states,
log milestone tracking, and dynamic user path validations under test isolation.
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

def test_executor_all():
    print("=== Testing Pipeline Executor ===")

    # 1. Setup isolated directories
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

    # Clear target schemas in DB
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET target_schema = NULL WHERE id = ?", (user1_id,))
        conn.commit()

    try:
        # -------------------------------------------------------------
        # A. SUCCESS RUN (MOCKED BASE RUN)
        # -------------------------------------------------------------
        print("\n[Testing Success Pipeline Run]")
        
        # Setup temp schemas and uploads
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")
        update_user_target_schema(user1_id, "target_schema.json")

        ensure_user_workspace("user1")
        
        # Seed uploads folder with mock CSV files
        uploads_dir = temp_workspaces_dir / "users" / "user1" / "uploads"
        (uploads_dir / "assets.csv").write_text("asset_no,asset_name\nA01,Pump", encoding="utf-8")

        # Simulate caller/middleware setting the user active workspace paths and schemas first
        config.set_user_workspace("user1")
        config.TARGET_SCHEMA_PATH = temp_schemas_dir / "target_schema.json"

        # Capture baseline config paths to check for mutation
        baseline_input = config.INPUT_DIR
        baseline_output = config.OUTPUT_DIR
        baseline_schema = config.TARGET_SCHEMA_PATH

        # Mock the heavy agents to avoid live Bedrock calls in unit tests
        with unittest.mock.patch("backend.pipeline_executor.run_discovery_agent") as mock_disc, \
             unittest.mock.patch("backend.pipeline_executor.run_profiling_agent") as mock_prof, \
             unittest.mock.patch("backend.pipeline_executor.run_mapping_agent") as mock_map, \
             unittest.mock.patch("backend.pipeline_executor.run_specification_agent") as mock_spec, \
             unittest.mock.patch("backend.pipeline_executor.run_readiness_agent") as mock_read, \
             unittest.mock.patch("backend.pipeline_executor.run_planning_agent") as mock_plan:
             
            exec_id = run_pipeline(user1_id)
            
            # Assert agents were triggered in sequence
            mock_disc.assert_called_once()
            mock_prof.assert_called_once()
            mock_map.assert_called_once()
            mock_spec.assert_called_once()
            mock_read.assert_called_once()
            mock_plan.assert_called_once()

        # Verify execution results JSON output
        expected_json_path = Path(config.OUTPUT_DIR) / f"execution_{exec_id}.json"
        assert expected_json_path.is_file(), f"Missing execution JSON file at: {expected_json_path}"
        
        with open(expected_json_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        assert metadata["execution_id"] == exec_id
        assert metadata["user_id"] == user1_id
        assert metadata["username"] == "user1"
        assert metadata["status"] == "success"
        assert metadata["error_message"] is None
        assert len(metadata["log_milestones"]) > 0
        assert "completed successfully" in metadata["log_milestones"][-1].lower()
        
        # Assert global config variables were not mutated inside the executor
        assert config.INPUT_DIR == baseline_input
        assert config.OUTPUT_DIR == baseline_output
        assert config.TARGET_SCHEMA_PATH == baseline_schema
        print("  [OK] Success run verified. Metadata stored correctly, config paths remained un-mutated.")

        # -------------------------------------------------------------
        # B. MISSING SCHEMA FAILURE (CONTROLLED FAILURE STATE)
        # -------------------------------------------------------------
        print("\n[Testing Missing Schema Controlled Failure]")
        
        # Clear schema config to trigger missing schema failure
        config.TARGET_SCHEMA_PATH = None
        
        # Reset DB values to NULL
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET target_schema = NULL WHERE id = ?", (user1_id,))
            conn.commit()

        # Call run_pipeline, should return exec_id safely without raising exception
        exec_id_fail = run_pipeline(user1_id)
        
        # Verify failure JSON metadata
        fail_json_path = Path(config.OUTPUT_DIR) / f"execution_{exec_id_fail}.json"
        assert fail_json_path.is_file()
        
        with open(fail_json_path, "r", encoding="utf-8") as f:
            metadata_fail = json.load(f)

        assert metadata_fail["status"] == "failed"
        assert "schema" in metadata_fail["error_message"].lower()
        print(f"  [OK] Missing schema failed safely. Error recorded: {metadata_fail['error_message']}")

        # -------------------------------------------------------------
        # C. EMPTY UPLOADS FOLDER FAILURE (CONTROLLED FAILURE STATE)
        # -------------------------------------------------------------
        print("\n[Testing Empty Uploads Folder Controlled Failure]")
        
        # Re-set valid schema config
        (temp_schemas_dir / "target_schema.json").write_text("{}", encoding="utf-8")
        (config.SCHEMAS_DIR / "target_schema.json").write_text("{}", encoding="utf-8")
        update_user_target_schema(user1_id, "target_schema.json")
        config.TARGET_SCHEMA_PATH = config.SCHEMAS_DIR / "target_schema.json"

        # Clear files in uploads directory
        for f in uploads_dir.iterdir():
            if f.is_file():
                f.unlink()

        # Call run_pipeline, should return exec_id safely
        exec_id_fail_empty = run_pipeline(user1_id)
        
        # Verify failure JSON metadata
        fail_empty_json_path = Path(config.OUTPUT_DIR) / f"execution_{exec_id_fail_empty}.json"
        assert fail_empty_json_path.is_file()
        
        with open(fail_empty_json_path, "r", encoding="utf-8") as f:
            metadata_fail_empty = json.load(f)

        assert metadata_fail_empty["status"] == "failed"
        assert "no supported files" in metadata_fail_empty["error_message"].lower()
        print(f"  [OK] Empty uploads failed safely. Error recorded: {metadata_fail_empty['error_message']}")

        # -------------------------------------------------------------
        # D. ACTIVE WORKSPACE MISMATCH GUARD
        # -------------------------------------------------------------
        print("\n[Testing Active Workspace Mismatch Guard]")
        
        # Set config workspace output directory to a mismatched path
        config.OUTPUT_DIR = Path("mismatched_outputs")
        
        # Call run_pipeline, should fail due to workspace mismatch guard
        exec_id_mismatch = run_pipeline(user1_id)
        
        # Since config.OUTPUT_DIR was "mismatched_outputs", the results JSON will be written there
        mismatch_json_path = Path("mismatched_outputs") / f"execution_{exec_id_mismatch}.json"
        assert mismatch_json_path.is_file()
        
        with open(mismatch_json_path, "r", encoding="utf-8") as f:
            metadata_mismatch = json.load(f)

        assert metadata_mismatch["status"] == "failed"
        assert "workspace output path" in metadata_mismatch["error_message"].lower()
        print(f"  [OK] Workspace mismatch guard blocked run successfully. Error: {metadata_mismatch['error_message']}")

        # Cleanup the mismatched output directory
        if Path("mismatched_outputs").exists():
            shutil.rmtree("mismatched_outputs")

        print("\n=== All Pipeline Executor Tests Passed! ===")

    finally:
        # Restore configuration and clean temp directory (test isolation)
        config.WORKSPACES_DIR = original_workspaces_dir
        config.SCHEMAS_DIR = original_schemas_dir
        config.TARGET_SCHEMA_PATH = original_target_schema_path
        config.INPUT_DIR = original_input_dir
        config.OUTPUT_DIR = original_output_dir
        
        shutil.rmtree(temp_workspaces_dir)
        shutil.rmtree(temp_schemas_dir)
        print("Restored original config variables and cleaned up temporary folders.")

if __name__ == "__main__":
    try:
        test_executor_all()
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
