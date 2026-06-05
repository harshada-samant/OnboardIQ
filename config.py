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
SCHEMAS_DIR = BASE_DIR / "schemas"

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
