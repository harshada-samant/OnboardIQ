"""
backend/execution_store.py
--------------------------
Thread-safe in-memory store for tracking active pipeline execution state.
Includes structured logging and progress updates.
"""

import threading
import copy
from datetime import datetime

# Global in-memory execution store and lock
execution_store = {}
store_lock = threading.Lock()

def start_execution(execution_id: str, user_id: int) -> None:
    """
    Initializes a new execution state tracking record in the store.
    """
    with store_lock:
        execution_store[execution_id] = {
            "user_id": user_id,
            "status": "running",
            "logs": [],
            "progress": 0,
            "current_step": "Init"
        }
    timestamp = datetime.utcnow().isoformat()
    print(f"[{timestamp}] [Init] [EXECUTION_START] Started execution tracking for ID: {execution_id}, User ID: {user_id}")

def transition_step(execution_id: str, step_name: str, progress: int, message: str) -> None:
    """
    Updates the execution step and progress, and appends a structured log entry.
    All state changes are performed as a single thread-safe lock-guarded action.
    """
    timestamp = datetime.utcnow().isoformat()
    formatted_console = f"[{timestamp}] [{step_name}] {message}"
    print(formatted_console)

    with store_lock:
        if execution_id not in execution_store:
            return
        
        record = execution_store[execution_id]
        record["progress"] = progress
        record["current_step"] = step_name
        record["logs"].append({
            "timestamp": timestamp,
            "message": message,
            "step": step_name
        })

def complete_execution(execution_id: str, status: str, error_message: str = None) -> None:
    """
    Sets the terminal state of the execution ("completed" or "failed").
    Adjusts progress to 100 on success, and logs the final outcome.
    """
    timestamp = datetime.utcnow().isoformat()
    
    if status == "completed":
        msg = "Pipeline execution completed successfully."
        step_name = "Completed"
        progress = 100
    else:
        msg = f"Pipeline execution failed. Error: {error_message}"
        step_name = "Failed"
        progress = None  # Leave progress unchanged or keep at current level

    formatted_console = f"[{timestamp}] [{step_name}] {msg}"
    print(formatted_console)

    with store_lock:
        if execution_id not in execution_store:
            return
        
        record = execution_store[execution_id]
        record["status"] = status
        if progress is not None:
            record["progress"] = progress
        record["current_step"] = step_name
        
        log_entry = {
            "timestamp": timestamp,
            "message": msg,
            "step": step_name
        }
        if error_message is not None:
            log_entry["error_message"] = error_message
            
        record["logs"].append(log_entry)

def get_execution(execution_id: str) -> dict:
    """
    Retrieves a deep copy of the execution record to prevent race conditions during reads.
    Returns None if the execution ID is not found.
    """
    with store_lock:
        record = execution_store.get(execution_id)
        if record is None:
            return None
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
