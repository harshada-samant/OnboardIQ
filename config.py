"""
config.py
---------
Centralized configuration, paths, and environment management for OnboardIQ.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base project paths (absolute)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
INPUT_DIR = DATA_DIR / "sample"
SCHEMAS_DIR = BASE_DIR / "schemas"
DB_PATH = DATA_DIR / "onboardiq.db"
WORKSPACES_DIR = BASE_DIR / "workspaces"

# Specific file paths
TARGET_SCHEMA_PATH = SCHEMAS_DIR / "target_schema.json"
FILE_REGISTRY_PATH = OUTPUT_DIR / "file_registry.json"
CONTEXT_SNAPSHOT_PATH = OUTPUT_DIR / "context_snapshot.json"
QUALITY_REPORT_PATH = OUTPUT_DIR / "quality_report.json"
MAPPING_DOCUMENT_PATH = OUTPUT_DIR / "mapping_document.json"
MIGRATION_SPEC_PATH = OUTPUT_DIR / "migration_spec.json"
MIGRATION_SPEC_MD_PATH = OUTPUT_DIR / "migration_spec.md"
READINESS_REPORT_PATH = OUTPUT_DIR / "readiness_report.json"
READINESS_REPORT_MD_PATH = OUTPUT_DIR / "readiness_report.md"
ONBOARDING_PLAN_PATH = OUTPUT_DIR / "onboarding_plan.json"
ONBOARDING_PLAN_MD_PATH = OUTPUT_DIR / "onboarding_plan.md"

def set_user_workspace(username: str) -> None:
    """
    Dynamically configures active paths (INPUT_DIR, OUTPUT_DIR, and all specific report paths)
    for the specified user's workspace.
    """
    global INPUT_DIR, OUTPUT_DIR, FILE_REGISTRY_PATH, CONTEXT_SNAPSHOT_PATH
    global QUALITY_REPORT_PATH, MAPPING_DOCUMENT_PATH, MIGRATION_SPEC_PATH
    global MIGRATION_SPEC_MD_PATH, READINESS_REPORT_PATH, READINESS_REPORT_MD_PATH
    global ONBOARDING_PLAN_PATH, ONBOARDING_PLAN_MD_PATH
    
    user_workspace_dir = WORKSPACES_DIR / "users" / username
    INPUT_DIR = user_workspace_dir / "uploads"
    OUTPUT_DIR = user_workspace_dir / "outputs"
    
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    FILE_REGISTRY_PATH = OUTPUT_DIR / "file_registry.json"
    CONTEXT_SNAPSHOT_PATH = OUTPUT_DIR / "context_snapshot.json"
    QUALITY_REPORT_PATH = OUTPUT_DIR / "quality_report.json"
    MAPPING_DOCUMENT_PATH = OUTPUT_DIR / "mapping_document.json"
    MIGRATION_SPEC_PATH = OUTPUT_DIR / "migration_spec.json"
    MIGRATION_SPEC_MD_PATH = OUTPUT_DIR / "migration_spec.md"
    READINESS_REPORT_PATH = OUTPUT_DIR / "readiness_report.json"
    READINESS_REPORT_MD_PATH = OUTPUT_DIR / "readiness_report.md"
    ONBOARDING_PLAN_PATH = OUTPUT_DIR / "onboarding_plan.json"
    ONBOARDING_PLAN_MD_PATH = OUTPUT_DIR / "onboarding_plan.md"


def load_and_validate_env(verbose: bool = False) -> None:
    """
    Loads environment variables from .env and validates required AWS/Bedrock credentials.
    """
    env_path = BASE_DIR / ".env"
    loaded = load_dotenv(dotenv_path=env_path)
    if not loaded and verbose:
        print(f"[Warning] .env file not found at: {env_path}")
        
    missing = [k for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not os.getenv(k)]
    if missing:
        raise EnvironmentError(f"AWS credentials missing in environment/.env: {', '.join(missing)}")
