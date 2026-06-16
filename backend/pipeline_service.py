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
from backend.adapters.s3_source_adapter import S3SourceAdapter
from backend.adapters.storage_interface import LocalStorageBackend, S3StorageBackend

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
    """List the user source files from either local workspace uploads or configured S3 source."""
    try:
        username = get_username_by_id(user_id)
    except ValueError as e:
        raise ValueError(f"Failed to resolve user: {e}")

    if config.USE_S3_SOURCE:
        backend = S3StorageBackend(S3SourceAdapter(config.S3_BUCKET, config.s3_input_prefix(username)))
        files_list = []
        for item in backend.list_files():
            files_list.append({
                "name": item.get("name"),
                "size": item.get("size", 0),
                "modified": item.get("modified") or item.get("last_modified") or "",
                "key": item.get("key"),
                "extension": item.get("extension"),
            })
        return sorted(files_list, key=lambda x: (x.get("name") or "").lower())

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
                "modified": modified_time,
                "key": str(p),
                "extension": p.suffix.lower(),
            })

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
        _handle_mapping_action,
        check_pending_confirmation,
        _extract_and_process_mapping_action
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

    # Check for pending confirmations
    conf_response = check_pending_confirmation(message, ctx, verbose=False)
    if conf_response is not None:
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": conf_response})
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
        except Exception as save_err:
            print(f"Error persisting chat history: {save_err}")
        return {"response": conf_response}

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
    try:
        clean_reply, status_msg = _extract_and_process_mapping_action(reply, ctx, verbose=False)
    except Exception as mapping_err:
        clean_reply, status_msg = reply, f"\n⚠️ Failed to execute mapping action: {mapping_err}"

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


# -------------------------------------------------------------
# 4. STEP-BY-STEP EXECUTION SERVICE FUNCTIONS AND ENDPOINTS
# -------------------------------------------------------------

def start_pipeline_step(user_id: int, step_name: str) -> str:
    """
    Generates a unique execution ID and spawns the pipeline runner for a single step in a background daemon thread.
    Returns the execution ID immediately. Strips spaces from step_name for backward compatibility.
    """
    normalized_step = step_name.replace(" ", "")
    execution_id = str(uuid.uuid4())
    thread = threading.Thread(
        target=run_pipeline,
        args=(user_id, execution_id, normalized_step),
        daemon=True
    )
    thread.start()
    return execution_id


def get_pipeline_progress(user_id: int) -> dict:
    """
    Inspects outputs of user workspace to check which files exist and determine completed steps.
    """
    try:
        username = get_username_by_id(user_id)
    except Exception:
        return {"completed_steps": [], "next_step": "Discovery"}

    outputs_dir = config.WORKSPACES_DIR / "users" / username / "outputs"
    
    steps = [
        ("Discovery", outputs_dir / "entity_catalog.json"),
        ("Profiling", outputs_dir / "quality_report.json"),
        ("Mapping", outputs_dir / "mapping_document.json"),
        ("Specification", outputs_dir / "migration_spec.json"),
        ("Readiness", outputs_dir / "readiness_report.json"),
        ("Planning", outputs_dir / "onboarding_plan.json"),
        ("Migration Agent", outputs_dir / "migration_validation.json")
    ]
    
    completed_steps = []
    for step_name, file_path in steps:
        if file_path.is_file():
            completed_steps.append(step_name)
            
    # Find next step
    next_step = None
    all_steps = [s[0] for s in steps]
    for step_name in all_steps:
        if step_name not in completed_steps:
            next_step = step_name
            break
            
    return {
        "completed_steps": completed_steps,
        "next_step": next_step
    }


def reset_pipeline(user_id: int) -> bool:
    """
    Clears all output files and snapshot to reset pipeline progress back to Step 1.
    """
    try:
        username = get_username_by_id(user_id)
    except Exception:
        return False
        
    outputs_dir = config.WORKSPACES_DIR / "users" / username / "outputs"
    if outputs_dir.exists() and outputs_dir.is_dir():
        import shutil
        for item in outputs_dir.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            except Exception as e:
                print(f"[pipeline_service] Error clearing output item {item.name}: {e}")
        return True
    return False


@app.post("/api/pipeline/start_step/{user_id}/{step_name}")
def api_start_pipeline_step(user_id: int, step_name: str):
    try:
        exec_id = start_pipeline_step(user_id, step_name)
        return {"execution_id": exec_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/pipeline/progress/{user_id}")
def api_get_pipeline_progress(user_id: int):
    try:
        return get_pipeline_progress(user_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/pipeline/reset/{user_id}")
def api_reset_pipeline(user_id: int):
    try:
        success = reset_pipeline(user_id)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

