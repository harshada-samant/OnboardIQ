"""
frontend/middleware.py
----------------------
Authentication and Isolated Workspace Middleware.
"""

import logging

from fastapi import Request
from fastapi.responses import RedirectResponse
from nicegui import app
import config

EXEMPT_PATHS = {'/login', '/_nicegui/client.js'}
logger = logging.getLogger(__name__)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    logger.debug("Middleware request path: %s", path)
    
    # Enforce authentication except for login and internal NiceGUI files
    if not app.storage.user.get('authenticated', False):
        if path not in EXEMPT_PATHS and not path.startswith('/_nicegui') and not path.startswith('/socket.io'):
            logger.debug("Redirecting unauthenticated path %s to /login", path)
            return RedirectResponse('/login')

    # Dynamically map the outputs directory relative to user workspace isolation
    if app.storage.user.get('authenticated', False):
        username = app.storage.user.get('username', 'default')
        config.set_user_workspace(username)
        
        user_id = app.storage.user.get('user_id')
        if user_id is not None:
            from backend.schema_manager import configure_user_schema
            configure_user_schema(user_id)

    response = await call_next(request)
    logger.debug("Middleware response status for %s: %s", path, response.status_code)
    return response
