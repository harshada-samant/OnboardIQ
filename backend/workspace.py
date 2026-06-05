"""
backend/workspace.py
--------------------
Utility module to create and manage user-isolated workspaces.
"""

import json
from pathlib import Path
import config

def get_user_workspace(username: str) -> dict:
    """
    Returns a dictionary of paths for the user's workspace.
    """
    user_dir = config.WORKSPACES_DIR / "users" / username
    return {
        "root": user_dir,
        "uploads": user_dir / "uploads",
        "outputs": user_dir / "outputs",
        "chat_history": user_dir / "chat_history.json"
    }

def create_user_workspace(username: str) -> dict:
    """
    Creates the directory structure and files for the user's workspace if missing.
    Safe to call multiple times.
    """
    paths = get_user_workspace(username)
    
    # Create directories
    paths["uploads"].mkdir(parents=True, exist_ok=True)
    paths["outputs"].mkdir(parents=True, exist_ok=True)
    
    # Create empty chat_history.json if missing
    chat_file = paths["chat_history"]
    if not chat_file.exists():
        with open(chat_file, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
            
    return paths

def ensure_user_workspace(username: str) -> dict:
    """
    Ensures that a user's workspace exists. Safe to call multiple times.
    """
    return create_user_workspace(username)
