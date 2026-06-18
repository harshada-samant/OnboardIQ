"""
frontend/main.py
----------------
Frontend entry point for the OnboardIQ NiceGUI web application.
Loads modular components: middleware, logo, and page views.
"""

import os
import socket
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

from frontend.logo import LOGO_32


def _port_is_available(port: int) -> bool:
    """Return True when the given TCP port can be bound locally."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _select_port(start_port: int, max_tries: int = 25) -> int:
    """Pick the first available port at or above the requested port."""
    for offset in range(max_tries):
        port = start_port + offset
        if _port_is_available(port):
            return port
    raise RuntimeError(
        f"Could not find a free port starting from {start_port} "
        f"after {max_tries} attempts."
    )


requested_port = int(os.getenv("FRONTEND_PORT") or os.getenv("PORT") or "8081")
selected_port = _select_port(requested_port)

# Run NiceGUI server
ui.run(
    title='OnboardIQ - Data Onboarding',
    port=selected_port,
    favicon=LOGO_32,
    show=False,
    reload=False,
    storage_secret='onboardiq_super_secret_key',
    session_middleware_kwargs={'max_age': None}
)
