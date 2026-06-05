"""
frontend/middleware.py
----------------------
Authentication and Isolated Workspace Middleware.
"""

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app
import config

EXEMPT_PATHS = {'/login', '/_nicegui/client.js'}

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Enforce authentication except for login and internal NiceGUI files
    if not app.storage.user.get('authenticated', False):
        path = request.url.path
        if path not in EXEMPT_PATHS and not path.startswith('/_nicegui'):
            return RedirectResponse('/login')

    # Dynamically map the outputs directory relative to user workspace isolation
    if app.storage.user.get('authenticated', False):
        username = app.storage.user.get('username', 'default')
        user_output_dir = config.BASE_DIR / "outputs" / "users" / username
        if config.OUTPUT_DIR != user_output_dir:
            config.OUTPUT_DIR = user_output_dir
            config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            config.FILE_REGISTRY_PATH = config.OUTPUT_DIR / "file_registry.json"
            config.CONTEXT_SNAPSHOT_PATH = config.OUTPUT_DIR / "context_snapshot.json"
            config.QUALITY_REPORT_PATH = config.OUTPUT_DIR / "quality_report.json"
            config.MAPPING_DOCUMENT_PATH = config.OUTPUT_DIR / "mapping_document.json"
            config.MIGRATION_SPEC_PATH = config.OUTPUT_DIR / "migration_spec.json"
            config.MIGRATION_SPEC_MD_PATH = config.OUTPUT_DIR / "migration_spec.md"
            config.READINESS_REPORT_PATH = config.OUTPUT_DIR / "readiness_report.json"
            config.READINESS_REPORT_MD_PATH = config.OUTPUT_DIR / "readiness_report.md"
            config.ONBOARDING_PLAN_PATH = config.OUTPUT_DIR / "onboarding_plan.json"
            config.ONBOARDING_PLAN_MD_PATH = config.OUTPUT_DIR / "onboarding_plan.md"

    return await call_next(request)
