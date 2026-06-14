"""
tests/test_workspace_routing.py
-------------------------------
End-to-end test validating user workspace routing and isolation in the pipeline.
"""

import sys
import os
import shutil
import glob
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.workspace import ensure_user_workspace
from backend.pipeline import run_pipeline

def test_workspace_routing():
    print("=== Testing Dynamic Workspace Routing ===")

    # 1. Clean workspaces and root outputs for validation clarity
    workspaces_dir = config.WORKSPACES_DIR
    if workspaces_dir.exists():
        print(f"Cleaning up {workspaces_dir}...")
        shutil.rmtree(workspaces_dir)
        
    global_outputs_dir = config.BASE_DIR / "outputs"
    if global_outputs_dir.exists():
        print(f"Cleaning up global outputs directory {global_outputs_dir}...")
        # Clean files inside global outputs but keep the dir
        for f in global_outputs_dir.iterdir():
            if f.is_file():
                f.unlink()
            elif f.is_dir():
                shutil.rmtree(f)

    # 2. Setup user1 uploads
    print("\n[Step 2] Initializing workspace for user1...")
    ensure_user_workspace("user1")
    user1_uploads = workspaces_dir / "users" / "user1" / "uploads"
    user1_outputs = workspaces_dir / "users" / "user1" / "outputs"
    
    # Copy sample csv files into user1's uploads
    sample_files = glob.glob(str(config.BASE_DIR / "data" / "sample" / "*.csv"))
    assert sample_files, "No sample CSV files found in data/sample/ to copy!"
    for sf in sample_files:
        shutil.copy(sf, user1_uploads)
    print(f"  Copied {len(sample_files)} sample CSV files to {user1_uploads}")

    # 3. Configure workspace for user1 and run pipeline
    print("\n[Step 3] Configuring active workspace to user1...")
    config.set_user_workspace("user1")
    
    # Assert config paths were updated correctly
    assert config.INPUT_DIR == user1_uploads, f"Expected INPUT_DIR to be {user1_uploads}, got {config.INPUT_DIR}"
    assert config.OUTPUT_DIR == user1_outputs, f"Expected OUTPUT_DIR to be {user1_outputs}, got {config.OUTPUT_DIR}"
    
    print("Running pipeline for user1...")
    ctx_user1 = run_pipeline(verbose=True)
    print("Pipeline run completed for user1.")

    # 4. Validate user1 output files
    expected_outputs = [
        "file_registry.json",
        "context_snapshot.json",
        "entity_catalog.json",
        "quality_report.json",
        "mapping_document.json",
        "migration_spec.json",
        "migration_spec.md",
        "readiness_report.json",
        "readiness_report.md",
        "onboarding_plan.json",
        "onboarding_plan.md"
    ]
    
    print("\n[Step 4] Validating user1 output files...")
    for out_file in expected_outputs:
        fpath = user1_outputs / out_file
        assert fpath.exists(), f"Missing expected output file in user1 workspace: {fpath}"
        print(f"  [OK] Found: {out_file}")


    # 5. Assert no files written to root outputs/
    print("\n[Step 5] Checking if any files leaked to global outputs/...")
    if global_outputs_dir.exists():
        leaked_files = [f.name for f in global_outputs_dir.iterdir() if f.is_file() and f.name != ".gitkeep"]
        assert not leaked_files, f"Leaked files found in global outputs/ folder: {leaked_files}"
        print("  [OK] No leaked files in global outputs/ directory.")
    else:
        print("  [OK] Global outputs/ directory was not even created.")

    # 6. Setup user2 uploads and verify isolation
    print("\n[Step 6] Initializing workspace for user2...")
    ensure_user_workspace("user2")
    user2_uploads = workspaces_dir / "users" / "user2" / "uploads"
    user2_outputs = workspaces_dir / "users" / "user2" / "outputs"
    
    for sf in sample_files:
        shutil.copy(sf, user2_uploads)
        
    print("Configuring active workspace to user2...")
    config.set_user_workspace("user2")
    
    assert config.INPUT_DIR == user2_uploads
    assert config.OUTPUT_DIR == user2_outputs

    # To save time and API quota, we verify user2 workspace paths resolve isolatedly
    # and verify we can run a single agent (or subset) if needed, but let's run the payload builder
    # to confirm it registers user2 uploads correctly.
    from agents.payload_builder import build_context_payload
    print("Testing payload builder on user2 uploads...")
    payload_files = sorted(str(p) for p in user2_uploads.iterdir() if p.is_file())
    res = build_context_payload(payload_files)
    
    user2_registry = user2_outputs / "file_registry.json"
    assert user2_registry.exists(), f"user2 file_registry.json was not created at: {user2_registry}"
    assert not (user1_outputs / "file_registry.json").samefile(user2_registry), "user1 and user2 share the same file_registry.json!"
    print("  [OK] user2 outputs generated and verified isolated from user1.")

    print("\n=== All Workspace Routing and Isolation Tests Passed! ===")

if __name__ == "__main__":
    try:
        test_workspace_routing()
    except AssertionError as e:
        print(f"\nAssertion Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected Error: {e}")
        sys.exit(1)
