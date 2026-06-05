"""
backend/pipeline_service.py
----------------------------
API and service layer exposing pipeline execution status, logging, and uploaded files.
Registered directly on NiceGUI's FastAPI application context.
"""

import uuid
import threading
from datetime import datetime
from pathlib import Path
from nicegui import app
from fastapi import HTTPException

import config
from backend.database import get_username_by_id
from backend.execution_store import get_execution
from backend.pipeline_executor import run_pipeline

# -------------------------------------------------------------
# 1. PYTHON SERVICE FUNCTIONS
# -------------------------------------------------------------

def start_pipeline(user_id: int) -> str:
    """
    Generates a unique execution ID and spawns the pipeline runner in a background daemon thread.
    Returns the execution ID immediately.
    """
    execution_id = str(uuid.uuid4())
    thread = threading.Thread(
        target=run_pipeline,
        args=(user_id, execution_id),
        daemon=True
    )
    thread.start()
    return execution_id


def get_execution_status(execution_id: str) -> dict:
    """
    Retrieves the execution status, progress, and current step from the execution store.
    Returns a default failed state if the execution record is not found in memory.
    """
    record = get_execution(execution_id)
    if record is not None:
        return {
            "status": record["status"],
            "progress": record["progress"],
            "current_step": record["current_step"]
        }
    
    return {
        "status": "failed",
        "progress": 0,
        "current_step": "Unknown",
        "error_message": "Execution ID not found in memory."
    }


def get_execution_logs(execution_id: str) -> list:
    """
    Retrieves the structured log list for the specified execution ID from the execution store.
    Returns an empty list if the execution record is not found in memory.
    """
    record = get_execution(execution_id)
    if record is not None:
        return record["logs"]
    return []


def get_user_source_files(user_id: int) -> list:
    """
    Lists the plain contents of the user's isolated uploads directory.
    Returns a list of dictionaries with name, size (in bytes), and modified ISO timestamp.
    """
    try:
        username = get_username_by_id(user_id)
    except ValueError as e:
        raise ValueError(f"Failed to resolve user: {e}")
        
    uploads_dir = config.WORKSPACES_DIR / "users" / username / "uploads"
    if not uploads_dir.exists() or not uploads_dir.is_dir():
        return []
    
    files_list = []
    for p in uploads_dir.iterdir():
        if p.is_file():
            stat_info = p.stat()
            modified_time = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
            files_list.append({
                "name": p.name,
                "size": stat_info.st_size,
                "modified": modified_time
            })
            
    # Sort files alphabetically by name
    return sorted(files_list, key=lambda x: x["name"])


# -------------------------------------------------------------
# 2. FASTAPI ENDPOINT WRAPPERS
# -------------------------------------------------------------

@app.post("/api/pipeline/start/{user_id}")
def api_start_pipeline(user_id: int):
    try:
        exec_id = start_pipeline(user_id)
        return {"execution_id": exec_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/pipeline/status/{execution_id}")
def api_get_execution_status(execution_id: str):
    return get_execution_status(execution_id)


@app.get("/api/pipeline/logs/{execution_id}")
def api_get_execution_logs(execution_id: str):
    return get_execution_logs(execution_id)


@app.get("/api/pipeline/files/{user_id}")
def api_get_user_source_files(user_id: int):
    try:
        return get_user_source_files(user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
