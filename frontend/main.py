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

from nicegui import ui

# Import middleware to register request handlers
import frontend.middleware

# Import pages package to register UI routes
import frontend.pages

# Run NiceGUI server
ui.run(
    title='OnboardIQ - Data Onboarding',
    port=8080,
    show=False,
    storage_secret='onboardiq_super_secret_key'
)
