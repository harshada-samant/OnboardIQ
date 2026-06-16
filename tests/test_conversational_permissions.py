"""
tests/test_conversational_permissions.py
-----------------------------------------
Unit tests verifying permission boundaries and the twice-confirmation flow
for questionable modifications in OnboardIQ Conversational Assistant.
"""

import sys
import os
import json
import shutil
import tempfile
import pytest
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.workspace import ensure_user_workspace
from backend.database import get_db_connection, update_user_target_schema
from backend.agents.conversational_assistant import (
    is_safe_output_path,
    is_modification_questionable,
    check_pending_confirmation,
    _extract_and_process_mapping_action,
    _handle_mapping_action
)

def get_user_id(username: str) -> int:
    """Dynamically resolves database ID for seed user."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Seed user '{username}' not found.")
        return row["id"]


@pytest.fixture(autouse=True)
def setup_isolated_workspace():
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

    # Clear target schemas in DB and set up target schema file
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET target_schema = NULL WHERE id = ?", (user1_id,))
        conn.commit()

    ensure_user_workspace("user1")
    config.set_user_workspace("user1")
    
    # Write a dummy target schema
    dummy_schema = {
        "Asset": {
            "asset_id": {"type": "string", "required": True},
            "cost": {"type": "number", "required": False},
            "status": {"type": "string", "required": True}
        }
    }
    target_schema_file = config.SCHEMAS_DIR / "target_schema.json"
    target_schema_file.write_text(json.dumps(dummy_schema, indent=2), encoding="utf-8")
    update_user_target_schema(user1_id, "target_schema.json")
    config.TARGET_SCHEMA_PATH = target_schema_file

    yield

    # Restore configuration and clean temp directory
    config.WORKSPACES_DIR = original_workspaces_dir
    config.SCHEMAS_DIR = original_schemas_dir
    config.TARGET_SCHEMA_PATH = original_target_schema_path
    config.INPUT_DIR = original_input_dir
    config.OUTPUT_DIR = original_output_dir
    
    shutil.rmtree(temp_workspaces_dir)
    shutil.rmtree(temp_schemas_dir)


def test_permission_boundaries():
    # 1. Verify paths inside output directory are safe
    assert is_safe_output_path(config.OUTPUT_DIR / "user_mappings.json")
    assert is_safe_output_path(config.OUTPUT_DIR / "mapping_document.json")
    
    # 2. Verify paths outside output directory are rejected
    assert not is_safe_output_path(root_dir / "onboardiq.db")
    assert not is_safe_output_path(config.BASE_DIR / "data" / "onboardiq.db")
    assert not is_safe_output_path(config.WORKSPACES_DIR / "users" / "user2" / "outputs" / "user_mappings.json")

    # 3. Test _handle_mapping_action throws PermissionError for unsafe paths
    action = {"action": "add", "source_entity": "Assets", "source_field": "asset_no", "target_entity": "Asset", "target_field": "asset_id"}
    context = {"entity_catalog": {"entities": []}}
    
    # Temporarily corrupt MIGRATION_SPEC_PATH to an unsafe location
    original_spec_path = config.MIGRATION_SPEC_PATH
    try:
        config.MIGRATION_SPEC_PATH = root_dir / "migration_spec.json"
        with pytest.raises(PermissionError) as exc_info:
            _handle_mapping_action(action, context, verbose=False)
        assert "outside of user output directory is forbidden" in str(exc_info.value)
    finally:
        config.MIGRATION_SPEC_PATH = original_spec_path


def test_questionable_modification_rules():
    # Source entity catalog context
    context = {
        "entity_catalog": {
            "entities": [
                {
                    "entity_name": "Assets",
                    "fields": [
                        {"name": "asset_no", "dtype": "string"},
                        {"name": "purchase_cost", "dtype": "decimal"},
                        {"name": "status_code", "dtype": "integer"}
                    ]
                }
            ]
        }
    }
    
    # 1. Action is 'remove' (destructive)
    action_remove = {"action": "remove", "source_entity": "Assets", "source_field": "asset_no"}
    reasons = is_modification_questionable(action_remove, context)
    assert any("destructive" in r for r in reasons)
    
    # 2. Target Entity does not exist
    action_bad_entity = {
        "action": "add",
        "source_entity": "Assets",
        "source_field": "asset_no",
        "target_entity": "NonexistentEntity",
        "target_field": "asset_id"
    }
    reasons = is_modification_questionable(action_bad_entity, context)
    assert any("does not exist in the target schema" in r for r in reasons)

    # 3. Target Field does not exist
    action_bad_field = {
        "action": "add",
        "source_entity": "Assets",
        "source_field": "asset_no",
        "target_entity": "Asset",
        "target_field": "nonexistent_field"
    }
    reasons = is_modification_questionable(action_bad_field, context)
    assert any("does not exist in target entity" in r for r in reasons)

    # 4. Type mismatch: source field is decimal/number, target is string, OR source is integer, target is string
    # Let's check status_code (integer) -> status (string)
    # Target "status" in Asset schema has type: "string"
    action_mismatch = {
        "action": "add",
        "source_entity": "Assets",
        "source_field": "status_code",
        "target_entity": "Asset",
        "target_field": "cost"  # expected type in Asset is "number"
    }
    reasons = is_modification_questionable(action_mismatch, context)
    assert any("Type mismatch" in r for r in reasons)

    # 5. Non-questionable: Assets.asset_no (string) -> Asset.asset_id (string)
    action_good = {
        "action": "add",
        "source_entity": "Assets",
        "source_field": "asset_no",
        "target_entity": "Asset",
        "target_field": "asset_id"
    }
    assert not is_modification_questionable(action_good, context)


def test_double_confirmation_flow():
    context = {
        "entity_catalog": {
            "entities": [
                {
                    "entity_name": "Assets",
                    "fields": [
                        {"name": "asset_no", "dtype": "string"},
                        {"name": "status_code", "dtype": "integer"}
                    ]
                }
            ]
        }
    }
    
    # 1. Trigger questionable action
    # Mismatch mapping: status_code (integer) -> cost (number)
    reply_with_block = """
    <<MAPPING_ACTION>>
    {
      "action": "add",
      "source_entity": "Assets",
      "source_field": "status_code",
      "target_entity": "Asset",
      "target_field": "cost"
    }
    <</MAPPING_ACTION>>
    I will try to map status_code to cost.
    """
    
    # Process the first time - should return clean reply and confirmation 1/2 prompt
    clean, status_msg = _extract_and_process_mapping_action(reply_with_block, context, verbose=False)
    assert "I will try to map status_code to cost." in clean
    assert "CONFIRMATION 1/2" in status_msg
    
    pending_path = Path(config.OUTPUT_DIR) / "pending_mapping_action.json"
    assert pending_path.exists()
    
    # Check confirmation 1/2 user input: user says "yes"
    conf_resp1 = check_pending_confirmation("yes", context, verbose=False)
    assert "CONFIRMATION 2/2" in conf_resp1
    
    with open(pending_path, "r", encoding="utf-8") as f:
        pending_data = json.load(f)
    assert pending_data["confirmations_received"] == 2
    
    # Check confirmation 2/2 user input: user says "yes" again
    conf_resp2 = check_pending_confirmation("yes", context, verbose=False)
    assert "Mapping saved" in conf_resp2
    assert not pending_path.exists()
    
    # Verify mapping was actually written
    user_mappings_path = Path(config.OUTPUT_DIR) / "user_mappings.json"
    assert user_mappings_path.exists()
    with open(user_mappings_path, "r", encoding="utf-8") as f:
        written = json.load(f)
    assert len(written) == 1
    assert written[0]["source_field"] == "status_code"
    assert written[0]["target_field"] == "cost"


def test_confirmation_aborted():
    context = {
        "entity_catalog": {
            "entities": [
                {
                    "entity_name": "Assets",
                    "fields": [
                        {"name": "asset_no", "dtype": "string"},
                        {"name": "status_code", "dtype": "integer"}
                    ]
                }
            ]
        }
    }
    
    reply_with_block = """
    <<MAPPING_ACTION>>
    {
      "action": "add",
      "source_entity": "Assets",
      "source_field": "status_code",
      "target_entity": "Asset",
      "target_field": "cost"
    }
    <</MAPPING_ACTION>>
    """
    
    # Trigger questionable action
    _extract_and_process_mapping_action(reply_with_block, context, verbose=False)
    pending_path = Path(config.OUTPUT_DIR) / "pending_mapping_action.json"
    assert pending_path.exists()
    
    # User replies with something else (e.g. "no" or a new question)
    conf_resp = check_pending_confirmation("What is the cost?", context, verbose=False)
    assert conf_resp is None
    assert not pending_path.exists()  # Pending confirmation should be cleared/aborted


def test_robust_closing_tags():
    from backend.agents.conversational_assistant import _extract_mapping_action
    
    # 1. Double bracket closing tag
    reply_double = """
    Some explanation.
    <<MAPPING_ACTION>>
    {"action": "remove", "source_entity": "Assets", "source_field": "asset_no"}
    <</MAPPING_ACTION>>
    Closing note.
    """
    action_double, clean_double = _extract_mapping_action(reply_double)
    assert action_double is not None
    assert action_double["action"] == "remove"
    assert "Some explanation." in clean_double
    assert "Closing note." in clean_double
    
    # 2. Single bracket closing tag (common LLM behavior)
    reply_single = """
    Some explanation.
    <<MAPPING_ACTION>>
    {"action": "remove", "source_entity": "Assets", "source_field": "asset_no"}
    </MAPPING_ACTION>
    Closing note.
    """
    action_single, clean_single = _extract_mapping_action(reply_single)
    assert action_single is not None
    assert action_single["action"] == "remove"
    assert "Some explanation." in clean_single
    assert "Closing note." in clean_single

