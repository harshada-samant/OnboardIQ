"""
backend/pipeline_service.py
----------------------------
API and service layer exposing pipeline execution status, logging, and uploaded files.
Registered directly on NiceGUI's FastAPI application context.
"""

import uuid
import threading
import json
import boto3
from datetime import datetime
from pathlib import Path
from nicegui import app
from fastapi import HTTPException
from pydantic import BaseModel
from typing import Optional

import config
import backend.workspace as workspace
from backend.database import get_username_by_id
from backend.execution_store import get_execution
from backend.pipeline_executor import run_pipeline

class ChatSendRequest(BaseModel):
    message: str
    execution_id: Optional[str] = None

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


def get_chat_history(user_id: int) -> list:
    """
    Retrieves the persistent chat history for the user from workspaces/users/{username}/chat_history.json.
    """
    try:
        username = get_username_by_id(user_id)
    except Exception as e:
        raise ValueError(f"User ID {user_id} not found: {e}")

    paths = workspace.ensure_user_workspace(username)
    history_file = paths["chat_history"]
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def send_chat_message(user_id: int, message: str, execution_id: str = None) -> dict:
    """
    Processes a user message, passes it to the Bedrock conversational assistant with context,
    persists history, and returns the response.
    """
    import os
    import json
    from context import fresh_context
    from backend.agents.conversational_assistant import (
        SYSTEM_PROMPT,
        _build_context_summary,
        _extract_mapping_action,
        _handle_mapping_action
    )
    
    try:
        username = get_username_by_id(user_id)
    except Exception as e:
        raise ValueError(f"User ID {user_id} not found: {e}")

    # Set user workspace so config paths resolve correctly to user outputs
    config.set_user_workspace(username)
    
    # 1. Load context snapshot (latest outputs)
    snapshot_path = config.OUTPUT_DIR / "context_snapshot.json"
    ctx = None
    if snapshot_path.exists():
        try:
            with open(snapshot_path, "r", encoding="utf-8") as f:
                ctx = json.load(f)
        except Exception:
            pass
            
    if ctx is None:
        ctx = fresh_context([])
        # Load whatever outputs exist in output dir as a fallback
        from tools.output_tools import load_output
        for fname, key in [
            ("entity_catalog.json",   "entity_catalog"),
            ("quality_report.json",   "quality_report"),
            ("mapping_document.json", "mappings"),
        ]:
            res = load_output(fname)
            if "error" not in res:
                ctx[key] = res

    # 2. Get persistent chat history
    paths = workspace.ensure_user_workspace(username)
    history_file = paths["chat_history"]
    history = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass

    # Ensure ctx["mappings"] is formatted as a dict (conversational_assistant expects {"mappings": [...]})
    if isinstance(ctx.get("mappings"), list):
        ctx["mappings"] = {"mappings": ctx["mappings"]}

    # Append new user message to history
    history.append({"role": "user", "content": message})

    # 3. Build Bedrock system prompt and summary
    context_summary = _build_context_summary(ctx)
    system_content = SYSTEM_PROMPT + "\n\n" + context_summary

    if not ctx.get("entity_catalog"):
        system_content += "\n\nFAILSAFE NOTICE: The onboarding pipeline context is currently empty. " \
                          "Please politely inform the user that you don't have schema details yet, " \
                          "and prompt them to run the pipeline first using the 'START PIPELINE' button to analyze their data."

    # 4. Attach pipeline execution context if a run is provided
    if execution_id:
        record = get_execution(execution_id)
        if record:
            system_content += f"\n\nCURRENT PIPELINE RUN CONTEXT:\n" \
                              f"Execution ID: {execution_id}\n" \
                              f"Status: {record['status']}\n" \
                              f"Progress: {record['progress']}%\n" \
                              f"Current Step: {record['current_step']}\n"

    # 5. Call Bedrock
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    
    try:
        client = config.get_bedrock_client()
        
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "system": system_content,
            "messages": history,
            "temperature": 0.3
        }
        
        response = client.invoke_model(
            modelId=model_id,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json",
        )
        
        body = json.loads(response["body"].read())
        reply = body["content"][0]["text"].strip()
    except Exception as e:
        reply = f"I encountered an error communicating with {config.get_provider_name()}: {e}"

    # 6. Parse and execute mapping overrides
    action, clean_reply = _extract_mapping_action(reply)
    status_msg = ""
    if action:
        try:
            status_msg = _handle_mapping_action(action, ctx, verbose=False)
        except Exception as mapping_err:
            status_msg = f"\n⚠️ Failed to execute mapping action: {mapping_err}"

    # Append assistant response to history
    final_reply = clean_reply
    if status_msg:
        final_reply += f"\n\n{status_msg}"
        
    history.append({"role": "assistant", "content": final_reply})

    # 7. Persist history back to file
    try:
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as save_err:
        print(f"Error persisting chat history: {save_err}")

    return {"response": final_reply}



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


@app.get("/api/chat/history/{user_id}")
def api_get_chat_history(user_id: int):
    try:
        return get_chat_history(user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/chat/send/{user_id}")
def api_send_chat_message(user_id: int, req: ChatSendRequest):
    try:
        return send_chat_message(user_id, req.message, req.execution_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
