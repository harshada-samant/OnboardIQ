"""
backend/schema_service.py
--------------------------
Service layer orchestration for listing, displaying, and updating user target schemas.
"""

from backend.database import get_user_target_schema, update_user_target_schema, get_username_by_id
from backend.schema_manager import get_available_schemas, configure_user_schema

def get_schema_options() -> list[str]:
    """
    Retrieves all available target schemas.
    Returns alphabetically sorted filenames.
    """
    return get_available_schemas()

def get_user_schema_selection(user_id: int) -> str | None:
    """
    Retrieves the currently selected schema filename for the specified user.
    Returns None if no schema is selected.
    """
    return get_user_target_schema(user_id)

def update_user_schema_selection(user_id: int, schema_name: str) -> bool:
    """
    Updates the user's selected schema, persists it in the database,
    and refreshes the runtime configuration path.
    Propagates ValueError for invalid user IDs or invalid schema names.
    """
    # 1. Resolve username to verify user ID exists (raises ValueError if missing)
    username = get_username_by_id(user_id)
    
    # 2. Persist selection (raises ValueError if schema_name fails validation)
    update_user_target_schema(user_id, schema_name)
    
    # 3. Configure/refresh runtime configuration
    success = configure_user_schema(user_id)
    if not success:
        print(f"[SCHEMA] Failed to configure runtime schema for {username}: {schema_name}")
        return False
        
    print(f"[SCHEMA] Updated schema selection for {username}: {schema_name}")
    return True
