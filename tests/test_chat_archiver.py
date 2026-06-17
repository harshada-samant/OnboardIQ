import json
import os
import shutil
from pathlib import Path
import sys

# Ensure backend and root are in the python path
sys.path.insert(0, os.getcwd())

import config
from backend.workspace import ensure_user_workspace, get_user_workspace, archive_chat_history

def test_chat_archiving():
    username = "test_archive_user"
    print(f"\nRunning chat archiving test for user: {username}...")
    
    # 1. Ensure fresh workspace
    paths = ensure_user_workspace(username)
    chat_file = paths["chat_history"]
    archive_file = paths["root"] / "chat_history_backend.json"
    
    # Clean up any leftover files first
    if archive_file.exists():
        archive_file.unlink()
        
    # Write initial mock chat history
    mock_history = [
        {"role": "user", "content": "Hello chatbot!"},
        {"role": "assistant", "content": "Hello user, how can I help you today?"}
    ]
    with open(chat_file, "w", encoding="utf-8") as f:
        json.dump(mock_history, f, indent=2)
        
    print("  Initial mock chat history written.")
    
    # 2. Trigger archiving
    archive_chat_history(username)
    
    # 3. Assert active history is empty
    with open(chat_file, "r", encoding="utf-8") as f:
        active_content = json.load(f)
    assert active_content == [], f"Expected active chat history to be empty, got: {active_content}"
    print("  Assertion passed: active chat history is cleared (empty).")
    
    # 4. Assert backend archive has the messages
    assert archive_file.exists(), "Expected archive file chat_history_backend.json to exist."
    with open(archive_file, "r", encoding="utf-8") as f:
        archive_content = json.load(f)
        
    assert len(archive_content) == 1, f"Expected 1 session in archive, got: {len(archive_content)}"
    session = archive_content[0]
    assert "session_end_time" in session, "Expected timestamp key in session"
    assert session["messages"] == mock_history, f"Archived messages mismatch. Got: {session['messages']}"
    print("  Assertion passed: archive file correctly formatted and preserved mock history.")
    
    # 5. Test double-archiving (subsequent session)
    mock_history_2 = [
        {"role": "user", "content": "Second session message."}
    ]
    with open(chat_file, "w", encoding="utf-8") as f:
        json.dump(mock_history_2, f, indent=2)
        
    archive_chat_history(username)
    
    # Assert active history is cleared again
    with open(chat_file, "r", encoding="utf-8") as f:
        active_content_2 = json.load(f)
    assert active_content_2 == []
    
    # Assert archive has both sessions
    with open(archive_file, "r", encoding="utf-8") as f:
        archive_content_2 = json.load(f)
    assert len(archive_content_2) == 2, f"Expected 2 sessions in archive, got: {len(archive_content_2)}"
    assert archive_content_2[1]["messages"] == mock_history_2
    print("  Assertion passed: multiple session archives successfully appended.")
    
    # Cleanup workspace files created for the test
    shutil.rmtree(paths["root"])
    print("  Test workspace cleaned up.")
    print("All chat archiver assertions passed successfully!")

if __name__ == "__main__":
    try:
        test_chat_archiving()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
