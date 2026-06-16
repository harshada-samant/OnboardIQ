"""
backend/schema_manager.py
--------------------------
Runtime configuration and path resolution for user-specific target schemas.
"""

from pathlib import Path
import config
from backend.database import get_user_target_schema, get_username_by_id

def get_available_schemas() -> list[str]:
    """
    Scans config.SCHEMAS_DIR, filters for .json files,
    returns alphabetically sorted filenames only.
    Returns an empty list if directory is empty or does not exist.
    """
    schemas_dir = config.SCHEMAS_DIR
    if not schemas_dir.exists() or not schemas_dir.is_dir():
        return []
    
    schema_files = [
        p.name for p in schemas_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".json"
    ]
    return sorted(schema_files)

def resolve_user_schema_path(user_id: int) -> Path | None:
    """
    Resolves the schema filename for the specified user ID to a full Path.
    Protects against path traversal attacks.
    Logs diagnostics appropriately.
    """
    try:
        username = get_username_by_id(user_id)
    except ValueError:
        print(f"[SCHEMA] Unknown user ID: {user_id}")
        return None

    schema_name = get_user_target_schema(user_id)
    if not schema_name:
        print(f"[SCHEMA] No schema selected for {username}")
        return None

    # Path traversal protection: filename only
    if Path(schema_name).name != schema_name:
        print(f"[SCHEMA] Invalid/traversal schema name stored for {username}: {schema_name}")
        return None

    resolved_path = config.SCHEMAS_DIR / schema_name
    if not resolved_path.is_file():
        print(f"[SCHEMA] Stored schema missing for {username}: {schema_name}")
        return None

    print(f"[SCHEMA] Loaded schema for {username}: {schema_name}")
    return resolved_path

def configure_user_schema(user_id: int) -> bool:
    """
    Resolves the user's schema path. If a valid schema path is resolved,
    updates config.TARGET_SCHEMA_PATH and returns True.
    Otherwise, leaves config.TARGET_SCHEMA_PATH unmodified and returns False (Option A).
    """
    resolved_schema_path = resolve_user_schema_path(user_id)
    if resolved_schema_path:
        config.TARGET_SCHEMA_PATH = resolved_schema_path
        return True
    return False
