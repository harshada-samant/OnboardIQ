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
    path = request.url.path
    print(f"[MIDDLEWARE_DEBUG] Request path: {path}")
    
    # Enforce authentication except for login and internal NiceGUI files
    if not app.storage.user.get('authenticated', False):
        if path not in EXEMPT_PATHS and not path.startswith('/_nicegui') and not path.startswith('/socket.io'):
            print(f"[MIDDLEWARE_DEBUG] REDIRECTING path {path} to /login")
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
    print(f"[MIDDLEWARE_DEBUG] Path {path} response status: {response.status_code}")
    return response
