import sys
import threading
import uuid
import json
from datetime import datetime
from pathlib import Path
import config
from backend.database import get_username_by_id
from pipeline import list_files
from context import fresh_context, save_snapshot, load_snapshot

# Import agent runner functions directly
from agents.discovery_agent import run_discovery_agent
from agents.profiling_agent import run_profiling_agent
from agents.mapping_agent import run_mapping_agent
from agents.specification_agent import run_specification_agent
from agents.readiness_agent import run_readiness_agent
from agents.planning_agent import run_planning_agent

# Import execution store helpers
from backend.execution_store import (
    start_execution,
    transition_step,
    complete_execution,
    get_execution,
    is_user_running,
    append_stdout_line
)

class LogRedirector:
    """
    Intercepts sys.stdout write calls and appends complete lines to the execution store logs.
    """
    def __init__(self, execution_id, original_stdout):
        self.execution_id = execution_id
        self.original = original_stdout
        self.buffer = []
        self.lock = threading.Lock()

    def write(self, text):
        self.original.write(text)
        with self.lock:
            for char in text:
                if char == '\n':
                    line = ''.join(self.buffer).rstrip('\r')
                    self.buffer = []
                    append_stdout_line(self.execution_id, line)
                else:
                    self.buffer.append(char)

    def flush(self):
        self.original.flush()
        
    def close(self):
        with self.lock:
            if self.buffer:
                line = ''.join(self.buffer).rstrip('\r')
                append_stdout_line(self.execution_id, line)
                self.buffer = []

def export_execution_json(execution_id: str, output_dir: Path, username: str = None) -> None:
    """
    Exports a copy of the execution record to the output folder in JSON format.
    Ensures backwards compatibility with the expected JSON structure.
    """
    record = get_execution(execution_id)
    if not record:
        return
    
    start_time = record["logs"][0]["timestamp"] if record["logs"] else datetime.utcnow().isoformat()
    end_time = record["logs"][-1]["timestamp"] if record["logs"] else datetime.utcnow().isoformat()
    error_msg = None
    for log_entry in reversed(record["logs"]):
        if "error_message" in log_entry:
            error_msg = log_entry["error_message"]
            break

    export_data = {
        "execution_id": execution_id,
        "user_id": record["user_id"],
        "username": username,
        "status": "success" if record["status"] == "completed" else "failed",
        "start_time": start_time,
        "end_time": end_time,
        "input_dir": str(config.INPUT_DIR),
        "output_dir": str(config.OUTPUT_DIR),
        "target_schema": str(config.TARGET_SCHEMA_PATH) if config.TARGET_SCHEMA_PATH else None,
        "error_message": error_msg,
        "log_milestones": [
            f"[{log['timestamp']}] [{log['step']}] {log['message']}" for log in record["logs"]
        ]
    }
    
    output_dir.mkdir(parents=True, exist_ok=True)
    export_file = output_dir / f"execution_{execution_id}.json"
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2)
    print(f"Exported execution JSON to: {export_file}")


def run_pipeline(user_id: int, execution_id: str = None, target_step: str = None) -> str:
    """
    Executes the sequential agents onboarding pipeline for the specified user ID.
    Directly triggers the agent contract functions step-by-step or a single step.
    Ensures a single active run per user using a concurrency lock.
    """
    if execution_id is None:
        execution_id = str(uuid.uuid4())
    username = None
    ctx = None
    
    # 1. Single-user concurrency lock check
    if is_user_running(user_id):
        err_msg = "User already has an active pipeline execution running."
        start_execution(execution_id, user_id)
        complete_execution(execution_id, "failed", err_msg)
        
        # Resolve username if possible to write metadata export
        try:
            username = get_username_by_id(user_id)
        except Exception:
            pass
            
        try:
            export_execution_json(execution_id, Path(config.OUTPUT_DIR), username)
        except Exception as export_err:
            print(f"Failed to export execution JSON for rejected run: {export_err}")
            
        return execution_id

    try:
        # 2. Validate user ID exists
        try:
            username = get_username_by_id(user_id)
        except ValueError as e:
            # Controlled failure: User does not exist
            start_execution(execution_id, user_id)
            complete_execution(execution_id, "failed", str(e))
            export_execution_json(execution_id, Path(config.OUTPUT_DIR), None)
            return execution_id

        # Initialize execution entry in store
        start_execution(execution_id, user_id)
        transition_step(execution_id, "Init", 0, f"Initiating pipeline execution {execution_id} for user {username}.")

        # Redirect standard output to capture agent logging in execution logs
        original_stdout = sys.stdout
        redirector = LogRedirector(execution_id, original_stdout)
        sys.stdout = redirector

        # 3. Verify config.OUTPUT_DIR matches the user's isolated workspace outputs directory
        expected_output_dir = config.WORKSPACES_DIR / "users" / username / "outputs"
        if Path(config.OUTPUT_DIR).resolve() != expected_output_dir.resolve():
            raise ValueError(f"Active workspace output path '{config.OUTPUT_DIR}' does not match expected output path '{expected_output_dir}' for user '{username}'.")

        # 4. Verify target schema path is set and points to an existing file
        if not config.TARGET_SCHEMA_PATH or not Path(config.TARGET_SCHEMA_PATH).is_file():
            raise ValueError(f"Target schema path '{config.TARGET_SCHEMA_PATH}' is missing or invalid.")

        # 5. Verify input files are present
        input_files = list_files(str(config.INPUT_DIR))
        if not input_files:
            raise ValueError(f"No supported files found in user uploads directory: {config.INPUT_DIR}")

        steps_map = {
            "Discovery": {"progress": 10, "label": "Starting Discovery Agent..."},
            "Profiling": {"progress": 30, "label": "Starting Profiling Agent..."},
            "Mapping": {"progress": 50, "label": "Starting Mapping Agent..."},
            "Specification": {"progress": 70, "label": "Starting Specification Agent..."},
            "Readiness": {"progress": 85, "label": "Starting Readiness Agent..."},
            "Planning": {"progress": 95, "label": "Starting Planning Agent..."}
        }

        # Initialize or load context snapshot
        if target_step is None or target_step == "Discovery":
            transition_step(execution_id, "Init", 5, f"Verified active configurations. Found {len(input_files)} file(s) in input directory.")
            ctx = fresh_context(input_files)
        else:
            ctx = load_snapshot()
            if not ctx:
                raise ValueError("Context snapshot missing. Please run Discovery Agent first to initialize the pipeline.")
            # Ensure fresh uploads list is mapped
            ctx["source_files"] = input_files

        # 6. Execute Agents
        if target_step is None:
            # ORIGINAL FLOW: Run all steps sequentially
            # Discovery Step
            transition_step(execution_id, "Discovery", 10, "Starting Discovery Agent...")
            run_discovery_agent(input_files, ctx, verbose=True)
            save_snapshot(ctx)

            # Profiling Step
            transition_step(execution_id, "Profiling", 30, "Starting Profiling Agent...")
            run_profiling_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Mapping Step
            transition_step(execution_id, "Mapping", 50, "Starting Mapping Agent...")
            run_mapping_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Specification Step
            transition_step(execution_id, "Specification", 70, "Starting Specification Agent...")
            run_specification_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Readiness Step
            transition_step(execution_id, "Readiness", 85, "Starting Readiness Agent...")
            run_readiness_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Planning Step
            transition_step(execution_id, "Planning", 95, "Starting Planning Agent...")
            run_planning_agent(ctx, verbose=True)
            save_snapshot(ctx)
        else:
            # TARGET STEP FLOW: Run only the specific step
            if target_step not in steps_map:
                raise ValueError(f"Unknown target step: {target_step}")
            
            step_info = steps_map[target_step]
            transition_step(execution_id, target_step, step_info["progress"], step_info["label"])
            
            if target_step == "Discovery":
                run_discovery_agent(input_files, ctx, verbose=True)
            elif target_step == "Profiling":
                run_profiling_agent(ctx, verbose=True)
            elif target_step == "Mapping":
                run_mapping_agent(ctx, verbose=True)
            elif target_step == "Specification":
                run_specification_agent(ctx, verbose=True)
            elif target_step == "Readiness":
                run_readiness_agent(ctx, verbose=True)
            elif target_step == "Planning":
                run_planning_agent(ctx, verbose=True)
                
            save_snapshot(ctx)

        # Success completion
        complete_execution(execution_id, "completed")

    except Exception as e:
        # Controlled failure state capture
        complete_execution(execution_id, "failed", str(e))
        if ctx is not None:
            try:
                save_snapshot(ctx)
            except Exception as snap_err:
                print(f"Error saving failure snapshot: {snap_err}")
                
    finally:
        # Restore original stdout
        if 'original_stdout' in locals():
            sys.stdout = original_stdout
            redirector.close()
            
        # Export metadata log JSON to active output directory
        try:
            export_execution_json(execution_id, Path(config.OUTPUT_DIR), username)
        except Exception as export_err:
            sys.__stdout__.write(f"CRITICAL: Failed to write execution results JSON: {export_err}\n")
            sys.__stdout__.flush()

    return execution_id
