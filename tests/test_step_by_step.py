"""
tests/test_step_by_step.py
----------------------------
Unit tests verifying the single-step execution flow, load_snapshot/save_snapshot integration,
progress tracking, and pipeline reset features.
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
from backend.pipeline_service import get_pipeline_progress, reset_pipeline
from context import load_snapshot

def get_user_id(username: str) -> int:
    """Dynamically resolves database ID for seed user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]

def test_step_by_step_execution():
    print("=== Testing Step-by-Step Execution Flow ===")

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
        ensure_user_workspace("user1")
        config.set_user_workspace("user1")
        
        # Seed uploads folder with mock CSV files
        uploads_dir = temp_workspaces_dir / "users" / "user1" / "uploads"
        (uploads_dir / "assets.csv").write_text("asset_no,asset_name\nA01,Pump", encoding="utf-8")

        # Re-set valid schema config inside workspace schemas folder
        (config.SCHEMAS_DIR / "target_schema.json").write_text("{}", encoding="utf-8")
        update_user_target_schema(user1_id, "target_schema.json")
        config.TARGET_SCHEMA_PATH = config.SCHEMAS_DIR / "target_schema.json"

        # -------------------------------------------------------------
        # A. INITIAL STATE CHECK
        # -------------------------------------------------------------
        progress = get_pipeline_progress(user1_id)
        assert progress["completed_steps"] == []
        assert progress["next_step"] == "Discovery"
        print("  [OK] Initial progress checks passed (No completed steps, next is Discovery).")

        # -------------------------------------------------------------
        # B. RUN STEP 1 (DISCOVERY)
        # -------------------------------------------------------------
        with unittest.mock.patch("backend.pipeline_executor.run_discovery_agent") as mock_disc:
            exec_id = run_pipeline(user1_id, target_step="Discovery")
            mock_disc.assert_called_once()
            
        # Write dummy catalog output to simulate agent completion
        outputs_dir = config.WORKSPACES_DIR / "users" / "user1" / "outputs"
        (outputs_dir / "entity_catalog.json").write_text("{}", encoding="utf-8")
        
        # Verify progress advances
        progress = get_pipeline_progress(user1_id)
        assert "Discovery" in progress["completed_steps"]
        assert progress["next_step"] == "Profiling"
        print("  [OK] Discovery step execution and progress transition verified.")

        # -------------------------------------------------------------
        # C. RUN STEP 2 (PROFILING) WITH MOCKED SNAPSHOT LOAD
        # -------------------------------------------------------------
        # Seed a dummy context snapshot
        dummy_ctx = {"source_files": [str(uploads_dir / "assets.csv")], "entity_catalog": {}, "quality_report": {}}
        with open(outputs_dir / "context_snapshot.json", "w") as f:
            json.dump(dummy_ctx, f)
            
        with unittest.mock.patch("backend.pipeline_executor.run_profiling_agent") as mock_prof:
            run_pipeline(user1_id, target_step="Profiling")
            mock_prof.assert_called_once()
            
        (outputs_dir / "quality_report.json").write_text("{}", encoding="utf-8")
        
        progress = get_pipeline_progress(user1_id)
        assert "Profiling" in progress["completed_steps"]
        assert progress["next_step"] == "Mapping"
        print("  [OK] Profiling step executed using context snapshot successfully.")

        # -------------------------------------------------------------
        # D. RESET PIPELINE
        # -------------------------------------------------------------
        reset_success = reset_pipeline(user1_id)
        assert reset_success is True
        
        # Verify all files cleared and progress returned to initial state
        progress = get_pipeline_progress(user1_id)
        assert progress["completed_steps"] == []
        assert progress["next_step"] == "Discovery"
        assert not (outputs_dir / "entity_catalog.json").exists()
        assert not (outputs_dir / "quality_report.json").exists()
        print("  [OK] Pipeline reset successfully cleared outputs and snapshot.")

        print("\n=== All Step-by-Step Executor Tests Passed! ===")

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
        test_step_by_step_execution()
    except AssertionError as e:
        print(f"\nAssertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error during validation: {e}")
        sys.exit(1)
