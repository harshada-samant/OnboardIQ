"""
backend/execution_store.py
--------------------------
Thread-safe in-memory store for tracking active pipeline execution state.
Includes structured logging and progress updates.
"""

import sys
import threading
import copy
import json
from datetime import datetime
from pathlib import Path

import config

# Global in-memory execution store and lock
execution_store = {}
store_lock = threading.Lock()


def _snapshot_dir() -> Path:
    """Return the durable on-disk mirror directory for execution state."""
    return Path(config.OUTPUT_DIR) / "_execution_state"


def _snapshot_path(execution_id: str) -> Path:
    """Return the JSON snapshot path for a specific execution."""
    return _snapshot_dir() / f"{execution_id}.json"


def _persist_execution_snapshot(execution_id: str) -> None:
    """
    Persist the current execution record to disk so UI polling can recover
    the latest state even if the in-memory store is unavailable.
    """
    with store_lock:
        record = execution_store.get(execution_id)
        if record is None:
            return
        snapshot = copy.deepcopy(record)

    snapshot_dir = _snapshot_dir()
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "execution_id": execution_id,
        "user_id": snapshot.get("user_id"),
        "status": snapshot.get("status"),
        "progress": snapshot.get("progress", 0),
        "current_step": snapshot.get("current_step", "Unknown"),
        "error_message": snapshot.get("error_message"),
        "updated_at": datetime.utcnow().isoformat(),
        "logs": snapshot.get("logs", []),
    }

    target_path = _snapshot_path(execution_id)
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as exc:
        sys.__stdout__.write(
            f"[{datetime.utcnow().isoformat()}] [Warning] Failed to persist execution snapshot "
            f"for {execution_id}: {exc}\n"
        )
        sys.__stdout__.flush()


def _load_execution_snapshot(execution_id: str) -> dict | None:
    """Load the last durable snapshot for an execution, if it exists."""
    snapshot_file = _snapshot_path(execution_id)
    if not snapshot_file.exists():
        return None
    try:
        with open(snapshot_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def start_execution(execution_id: str, user_id: int, status: str = "running") -> None:
    """
    Initializes a new execution state tracking record in the store.
    """
    with store_lock:
        execution_store[execution_id] = {
            "user_id": user_id,
            "status": status,
            "logs": [],
            "progress": 0,
            "current_step": "Init",
            "error_message": None,
        }
    _persist_execution_snapshot(execution_id)
    timestamp = datetime.utcnow().isoformat()
    msg = f"[{timestamp}] [Init] [EXECUTION_START] Started execution tracking for ID: {execution_id}, User ID: {user_id}\n"
    sys.__stdout__.write(msg)
    sys.__stdout__.flush()

def transition_step(execution_id: str, step_name: str, progress: int, message: str) -> None:
    """
    Updates the execution step and progress, and appends a structured log entry.
    All state changes are performed as a single thread-safe lock-guarded action.
    """
    timestamp = datetime.utcnow().isoformat()
    formatted_console = f"[{timestamp}] [{step_name}] {message}\n"
    sys.__stdout__.write(formatted_console)
    sys.__stdout__.flush()

    with store_lock:
        if execution_id not in execution_store:
            return
        
        record = execution_store[execution_id]
        record["progress"] = progress
        record["current_step"] = step_name
        record["error_message"] = None
        record["logs"].append({
            "timestamp": timestamp,
            "message": message,
            "step": step_name,
            "is_raw": False
        })
    _persist_execution_snapshot(execution_id)

def append_stdout_line(execution_id: str, message: str) -> None:
    """
    Appends a raw stdout print message to the execution store logs.
    """
    with store_lock:
        if execution_id not in execution_store:
            return
        record = execution_store[execution_id]
        record["logs"].append({
            "timestamp": datetime.utcnow().isoformat(),
            "message": message,
            "step": record.get("current_step", "Pipeline"),
            "is_raw": True
        })

def complete_execution(execution_id: str, status: str, error_message: str = None) -> None:
    """
    Sets the terminal state of the execution ("completed", "skipped", or "failed").
    Adjusts progress to 100 on terminal success-like states, and logs the final outcome.
    """
    timestamp = datetime.utcnow().isoformat()
    
    if status == "completed":
        msg = "Pipeline execution completed successfully."
        step_name = "Completed"
        progress = 100
    elif status == "skipped":
        msg = "Pipeline execution completed with downstream steps skipped."
        step_name = "Skipped"
        progress = 100
    else:
        msg = f"Pipeline execution failed. Error: {error_message}"
        step_name = "Failed"
        progress = None  # Leave progress unchanged or keep at current level

    formatted_console = f"[{timestamp}] [{step_name}] {msg}\n"
    sys.__stdout__.write(formatted_console)
    sys.__stdout__.flush()

    with store_lock:
        if execution_id not in execution_store:
            return
        
        record = execution_store[execution_id]
        record["status"] = status
        if progress is not None:
            record["progress"] = progress
        record["current_step"] = step_name
        record["error_message"] = error_message
        
        log_entry = {
            "timestamp": timestamp,
            "message": msg,
            "step": step_name,
            "is_raw": False
        }
        if error_message is not None:
            log_entry["error_message"] = error_message
            
        record["logs"].append(log_entry)
    _persist_execution_snapshot(execution_id)

def get_execution(execution_id: str) -> dict:
    """
    Retrieves a deep copy of the execution record to prevent race conditions during reads.
    Returns None if the execution ID is not found.
    """
    with store_lock:
        record = execution_store.get(execution_id)
        if record is None:
            snapshot = _load_execution_snapshot(execution_id)
            return copy.deepcopy(snapshot) if snapshot is not None else None
        return copy.deepcopy(record)

def is_user_running(user_id: int) -> bool:
    """
    Checks if there is any execution record in the store for the given user ID
    that is currently in the "running" state.
    """
    with store_lock:
        for record in execution_store.values():
            if record.get("user_id") == user_id and record.get("status") == "running":
                return True
    return False


def claim_execution(execution_id: str, user_id: int) -> bool:
    """
    Atomically promote a queued/starting execution to running if no other
    execution for the same user is currently active.

    This lets the service pre-create a record for polling without causing the
    worker thread to reject its own execution as a duplicate.
    """
    with store_lock:
        record = execution_store.get(execution_id)
        if record is None or record.get("user_id") != user_id:
            return False

        for other_execution_id, other_record in execution_store.items():
            if other_execution_id == execution_id:
                continue
            if other_record.get("user_id") == user_id and other_record.get("status") == "running":
                return False

        record["status"] = "running"
        return True
