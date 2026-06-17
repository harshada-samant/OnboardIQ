"""
tests/test_workspace_isolation.py
----------------------------------
Test script to validate user workspace creation, isolation, and idempotency.
"""

import sys
import os
import json
import shutil
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

from backend.workspace import ensure_user_workspace, get_user_workspace
import config

def test_workspace_isolation():
    print("=== Testing Workspace Isolation ===")
    
    # 1. Clean up workspaces folder if exists for a fresh test run
    workspaces_dir = config.WORKSPACES_DIR
    if workspaces_dir.exists():
        print(f"Cleaning up existing workspaces directory for test: {workspaces_dir}")
        shutil.rmtree(workspaces_dir)

    # 2. Ensure workspaces for user1 and user2
    print("Creating workspace for user1...")
    paths_user1 = ensure_user_workspace("user1")
    
    print("Creating workspace for user2...")
    paths_user2 = ensure_user_workspace("user2")
    
    # 3. Assert directories and files exist for user1
    assert paths_user1["root"].exists(), "user1 root directory does not exist"
    assert paths_user1["uploads"].exists(), "user1 uploads directory does not exist"
    assert paths_user1["outputs"].exists(), "user1 outputs directory does not exist"
    assert paths_user1["chat_history"].exists(), "user1 chat_history.json file does not exist"
    print("  [OK] user1 directory structure verified.")

    # 4. Assert directories and files exist for user2
    assert paths_user2["root"].exists(), "user2 root directory does not exist"
    assert paths_user2["uploads"].exists(), "user2 uploads directory does not exist"
    assert paths_user2["outputs"].exists(), "user2 outputs directory does not exist"
    assert paths_user2["chat_history"].exists(), "user2 chat_history.json file does not exist"
    print("  [OK] user2 directory structure verified.")

    # 5. Assert isolation (user1 and user2 must receive separate folders)
    assert paths_user1["root"] != paths_user2["root"], "user1 and user2 root workspaces are identical!"
    assert not os.path.samefile(paths_user1["root"], paths_user2["root"]), "user1 and user2 point to the same directory location!"
    print("  [OK] user1 and user2 workspaces are isolated and separate.")

    # 6. Test Idempotency (repeated calls must not overwrite files)
    print("Writing dummy message to user1's chat history...")
    dummy_message = [{"role": "user", "content": "Hello !!!"}]
    with open(paths_user1["chat_history"], "w") as f:
        json.dump(dummy_message, f, indent=2)
        
    print("Calling ensure_user_workspace('user1') again...")
    paths_user1_again = ensure_user_workspace("user1")
    
    # Load chat history and assert it was not overwritten
    with open(paths_user1_again["chat_history"], "r") as f:
        loaded_history = json.load(f)
        
    assert loaded_history == dummy_message, "Error: repeated workspace initialization overwrote chat_history.json!"
    print("  [OK] Repeated calls do not recreate or overwrite files (idempotency verified).")


    print("\n=== All Workspace Validation Tests Passed! ===")

if __name__ == "__main__":
    try:
        test_workspace_isolation()
    except AssertionError as e:
        print(f"Assertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error during validation: {e}")
        sys.exit(1)
