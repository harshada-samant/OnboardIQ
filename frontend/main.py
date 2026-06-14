"""
frontend/main.py
----------------
Frontend entry point for the OnboardIQ NiceGUI web application.
Loads modular components: middleware, logo, and page views.
"""

import sys
from pathlib import Path

# Add root workspace and backend directories to python path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))
sys.path.insert(0, str(root_dir / "frontend"))

# Load environment variables from .env
from config import load_and_validate_env
load_and_validate_env()

from nicegui import ui

# Import middleware to register request handlers
import frontend.middleware

# Import pages package to register UI routes
import frontend.pages

# Import pipeline service to register API endpoints
import backend.pipeline_service

# Run NiceGUI server
ui.run(
    title='OnboardIQ - Data Onboarding',
    port=8080,
    show=False,
    reload=False,
    storage_secret='onboardiq_super_secret_key',
    session_middleware_kwargs={'max_age': None}
)
