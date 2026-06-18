import os
import sys
import threading
import uuid
import json
import shutil
import importlib
from datetime import datetime
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.database import get_username_by_id
from pipeline import list_files
from context import fresh_context, save_snapshot, load_snapshot
from backend.adapters.s3_source_adapter import S3SourceAdapter
from backend.adapters.storage_interface import LocalStorageBackend, S3StorageBackend

# Import agent runner functions directly
from agents.discovery_agent import run_discovery_agent
from agents.profiling_agent import run_profiling_agent
from agents.mapping_agent import run_mapping_agent
from agents.specification_agent import run_specification_agent
from agents.readiness_agent import run_readiness_agent
from agents.planning_agent import run_planning_agent
from agents.migration_generator_agent import run_migration_generator_agent
from agents.migration_reviewer_agent import run_migration_reviewer_agent
from agents.migration_repair_agent import run_migration_repair_agent
from agents.migration_execution_agent import run_migration_execution_agent
from agents.migration_validation_agent import run_migration_validation_agent
from agents.migration_approval_agent import run_migration_approval_agent

# Import execution store helpers
from backend.execution_store import (
    start_execution,
    transition_step,
    complete_execution,
    get_execution,
    claim_execution,
    append_stdout_line
)


def _reload_agent_runners() -> None:
    """
    Refresh agent modules so a long-lived backend process picks up code edits
    on the next pipeline run without a manual restart.
    """
    module_names = {
        "discovery_agent": "agents.discovery_agent",
        "profiling_agent": "agents.profiling_agent",
        "mapping_agent": "agents.mapping_agent",
        "specification_agent": "agents.specification_agent",
        "readiness_agent": "agents.readiness_agent",
        "planning_agent": "agents.planning_agent",
        "migration_generator_agent": "agents.migration_generator_agent",
        "migration_reviewer_agent": "agents.migration_reviewer_agent",
        "migration_repair_agent": "agents.migration_repair_agent",
        "migration_execution_agent": "agents.migration_execution_agent",
        "migration_validation_agent": "agents.migration_validation_agent",
        "migration_approval_agent": "agents.migration_approval_agent",
    }

    loaded = {}
    for key, module_name in module_names.items():
        module = importlib.import_module(module_name)
        loaded[key] = importlib.reload(module)

    globals().update({
        "run_discovery_agent": loaded["discovery_agent"].run_discovery_agent,
        "run_profiling_agent": loaded["profiling_agent"].run_profiling_agent,
        "run_mapping_agent": loaded["mapping_agent"].run_mapping_agent,
        "run_specification_agent": loaded["specification_agent"].run_specification_agent,
        "run_readiness_agent": loaded["readiness_agent"].run_readiness_agent,
        "run_planning_agent": loaded["planning_agent"].run_planning_agent,
        "run_migration_generator_agent": loaded["migration_generator_agent"].run_migration_generator_agent,
        "run_migration_reviewer_agent": loaded["migration_reviewer_agent"].run_migration_reviewer_agent,
        "run_migration_repair_agent": loaded["migration_repair_agent"].run_migration_repair_agent,
        "run_migration_execution_agent": loaded["migration_execution_agent"].run_migration_execution_agent,
        "run_migration_validation_agent": loaded["migration_validation_agent"].run_migration_validation_agent,
        "run_migration_approval_agent": loaded["migration_approval_agent"].run_migration_approval_agent,
    })

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


def _wipe_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)


def _build_storage_backend(username: str, execution_id: str):
    if config.USE_S3_SOURCE:
        prefix = config.s3_input_prefix(username, execution_id)
        return S3StorageBackend(S3SourceAdapter(config.S3_BUCKET, prefix))
    return LocalStorageBackend(str(config.INPUT_DIR))

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
        "status": "success" if record["status"] in ("completed", "skipped") else "failed",
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


def _wipe_migration_output_dir() -> None:
    migration_dir = os.path.join(str(config.OUTPUT_DIR), "migration")
    if os.path.exists(migration_dir):
        shutil.rmtree(migration_dir)
    os.makedirs(migration_dir, exist_ok=True)
    print(f"  [migration] Wiped and recreated migration dir: {migration_dir}")


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
    _reload_agent_runners()
    
    # 1. Single-user concurrency lock check
    if get_execution(execution_id) is None:
        start_execution(execution_id, user_id, status="starting")

    if not claim_execution(execution_id, user_id):
        err_msg = "User already has an active pipeline execution running."
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
            if get_execution(execution_id) is None:
                start_execution(execution_id, user_id)
            complete_execution(execution_id, "failed", str(e))
            export_execution_json(execution_id, Path(config.OUTPUT_DIR), None)
            return execution_id

        # Initialize execution entry in store unless the service already created it.
        if get_execution(execution_id) is None:
            start_execution(execution_id, user_id)

        # 3. Verify config.OUTPUT_DIR matches the user's isolated workspace outputs directory
        expected_output_dir = config.WORKSPACES_DIR / "users" / username / "outputs"
        if Path(config.OUTPUT_DIR).resolve() != expected_output_dir.resolve():
            raise ValueError(f"Active workspace output path '{config.OUTPUT_DIR}' does not match expected output path '{expected_output_dir}' for user '{username}'.")

        # 4. Verify target schema path is set and points to an existing file.
        # S3 source mode may supply source data remotely, but target schemas are still local unless configured otherwise.
        if not config.TARGET_SCHEMA_PATH or not Path(config.TARGET_SCHEMA_PATH).is_file():
            raise ValueError(f"Target schema path '{config.TARGET_SCHEMA_PATH}' is missing or invalid.")

        # Start from a clean output workspace only for full fresh runs.
        if target_step is None:
            _wipe_output_dir(Path(config.OUTPUT_DIR))

        storage_backend = _build_storage_backend(username, execution_id)
        source_entries = storage_backend.list_files()
        if not source_entries:
            source_location = "S3 source" if config.USE_S3_SOURCE else f"local input directory '{config.INPUT_DIR}'"
            raise ValueError(f"No supported files found in {source_location} for user '{username}'.")

        input_files = [entry["key"] for entry in source_entries]

        transition_step(execution_id, "Init", 0, f"Initiating pipeline execution {execution_id} for user {username}.")

        # Redirect standard output to capture agent logging in execution logs
        original_stdout = sys.stdout
        redirector = LogRedirector(execution_id, original_stdout)
        sys.stdout = redirector

        steps_map = {
            "Discovery": {"progress": 10, "label": "Starting Discovery Agent..."},
            "Profiling": {"progress": 30, "label": "Starting Profiling Agent..."},
            "Mapping": {"progress": 50, "label": "Starting Mapping Agent..."},
            "Specification": {"progress": 70, "label": "Starting Specification Agent..."},
            "Readiness": {"progress": 85, "label": "Starting Readiness Agent..."},
            "Planning": {"progress": 95, "label": "Starting Planning Agent..."},
            "MigrationGenerator": {"progress": 96, "label": "Starting Migration Code Generator..."},
            "MigrationReviewer": {"progress": 97, "label": "Starting Migration Reviewer..."},
            "MigrationRepair": {"progress": 98, "label": "Starting Migration Repair Agent..."},
            "MigrationExecution": {"progress": 99, "label": "Starting Migration Execution Agent..."},
            "MigrationValidation": {"progress": 100, "label": "Starting Migration Validation Agent..."},
            "MigrationApproval": {"progress": 100, "label": "Starting Migration Approval Agent..."},
            "MigrationAgent": {"progress": 100, "label": "Starting Migration Agent..."}
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

        # Inject username and storage backend
        ctx["username"] = username
        ctx["_storage"] = storage_backend

        schema_name = Path(config.TARGET_SCHEMA_PATH).name.lower() if config.TARGET_SCHEMA_PATH else ""

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

            # Resolve target database for context
            if "dynamo" in schema_name:
                ctx["target_database"] = "dynamodb"
            elif "duck" in schema_name or "sql" in schema_name or schema_name == "target_schema.json" or "maximo" in schema_name:
                ctx["target_database"] = "duckdb"
            else:
                raise ValueError("UNSUPPORTED_TARGET_DATABASE: Target schema not recognized as DuckDB or DynamoDB.")

            # Preserve the active per-user output directory established by workspace/config.

            # Migration Generator
            transition_step(execution_id, "MigrationGenerator", 96, "Starting Migration Code Generator...")
            _wipe_migration_output_dir()
            run_migration_generator_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Migration Reviewer
            transition_step(execution_id, "MigrationReviewer", 97, "Starting Migration Reviewer...")
            run_migration_reviewer_agent(ctx, verbose=True)
            save_snapshot(ctx)

            # Conditional Repair
            if ctx.get("review", {}).get("status") == "REJECTED" and ctx.get("review", {}).get("fix_required"):
                transition_step(execution_id, "MigrationRepair", 98, "Starting Migration Repair Agent...")
                run_migration_repair_agent(ctx, verbose=True)
                save_snapshot(ctx)

                # Re‑run Reviewer after repair
                transition_step(execution_id, "MigrationReviewer", 97, "Re‑running Migration Reviewer after repair...")
                run_migration_reviewer_agent(ctx, verbose=True)
                save_snapshot(ctx)

            # Migration Execution (only if approved or approved with warnings)
            PASSING_STATUSES = {"APPROVED", "APPROVED WITH WARNINGS"}
            if ctx["review"]["status"] in PASSING_STATUSES:
                transition_step(execution_id, "MigrationExecution", 99, "Starting Migration Execution Agent...")
                run_migration_execution_agent(ctx, verbose=True)
                save_snapshot(ctx)

                # Migration Validation
                transition_step(execution_id, "MigrationValidation", 100, "Starting Migration Validation Agent...")
                run_migration_validation_agent(ctx, verbose=True)
                save_snapshot(ctx)

            # Migration Approval (final step)
            transition_step(execution_id, "MigrationApproval", 100, "Starting Migration Approval Agent...")
            run_migration_approval_agent(ctx, verbose=True)
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
            elif target_step == "MigrationGenerator":
                ctx["target_database"] = "duckdb" if "dynamo" not in schema_name else "dynamodb"
                _wipe_migration_output_dir()
                run_migration_generator_agent(ctx, verbose=True)
            elif target_step == "MigrationReviewer":
                ctx["target_database"] = "duckdb" if "dynamo" not in schema_name else "dynamodb"
                run_migration_reviewer_agent(ctx, verbose=True)
            elif target_step == "MigrationRepair":
                run_migration_repair_agent(ctx, verbose=True)
            elif target_step == "MigrationExecution":
                ctx["target_database"] = "duckdb" if "dynamo" not in schema_name else "dynamodb"
                run_migration_execution_agent(ctx, verbose=True)
            elif target_step == "MigrationValidation":
                ctx["target_database"] = "duckdb" if "dynamo" not in schema_name else "dynamodb"
                run_migration_validation_agent(ctx, verbose=True)
            elif target_step == "MigrationApproval":
                run_migration_approval_agent(ctx, verbose=True)
            elif target_step == "MigrationAgent":
                ctx["target_database"] = "duckdb" if "dynamo" not in schema_name else "dynamodb"
                
                # 7. Migration Generator
                transition_step(execution_id, "MigrationAgent", 15, "Starting Migration Code Generator...")
                _wipe_migration_output_dir()
                run_migration_generator_agent(ctx, verbose=True)
                save_snapshot(ctx)
                if ctx.get("migration", {}).get("status") == "FAILED":
                    raise ValueError(ctx.get("migration", {}).get("error", "Migration Generator failed."))

                # 8. Migration Reviewer
                transition_step(execution_id, "MigrationAgent", 35, "Starting Migration Reviewer...")
                run_migration_reviewer_agent(ctx, verbose=True)
                save_snapshot(ctx)
                if ctx.get("review", {}).get("status") == "FAILED":
                    raise ValueError(ctx.get("review", {}).get("error", "Migration Reviewer failed."))

                # 9. Bounded repair loop: up to 2 retries (3 total review runs)
                repair_attempts = 0
                while ctx.get("review", {}).get("status") == "REJECTED" and ctx.get("review", {}).get("fix_required") and repair_attempts < 2:
                    repair_attempts += 1
                    transition_step(execution_id, "MigrationAgent", 35 + repair_attempts * 10, f"Starting Migration Repair Agent (Attempt {repair_attempts})...")
                    run_migration_repair_agent(ctx, verbose=True)
                    save_snapshot(ctx)
                    
                    transition_step(execution_id, "MigrationAgent", 35 + repair_attempts * 10 + 5, f"Re-running Migration Reviewer (Attempt {repair_attempts})...")
                    run_migration_reviewer_agent(ctx, verbose=True)
                    save_snapshot(ctx)

                # 10. Execution Agent (runs only if approved)
                PASSING_STATUSES = {"APPROVED", "APPROVED WITH WARNINGS"}
                if ctx["review"]["status"] in PASSING_STATUSES:
                    transition_step(execution_id, "MigrationAgent", 70, "Starting Migration Execution Agent...")
                    run_migration_execution_agent(ctx, verbose=True)
                    save_snapshot(ctx)
                    if ctx.get("execution", {}).get("status") == "FAILED":
                        raise ValueError(ctx.get("execution", {}).get("error", "Migration Execution failed."))

                    # 11. Validation Agent
                    transition_step(execution_id, "MigrationAgent", 90, "Starting Migration Validation Agent...")
                    run_migration_validation_agent(ctx, verbose=True)
                    save_snapshot(ctx)
                    if ctx.get("validation", {}).get("status") == "FAILED":
                        raise ValueError(ctx.get("validation", {}).get("error", "Migration Validation failed."))
                    
                    # 12. Approval Agent (final step)
                    transition_step(execution_id, "MigrationAgent", 100, "Starting Migration Approval Agent...")
                    run_migration_approval_agent(ctx, verbose=True)
                    save_snapshot(ctx)
                else:
                    msg = "Skipping Execution, Validation, and Approval because Migration Review was not approved."
                    print(f"  ! {msg}")
                    complete_execution(execution_id, "skipped", msg)
                    return execution_id
                
            save_snapshot(ctx)

        # Determine final status from agents' outcomes rather than assuming success.
        final_error = None
        try:
            approval_rec = ctx.get("approval", {}) if ctx else {}
            execution_rec = ctx.get("execution", {}) if ctx else {}
            validation_rec = ctx.get("validation", {}) if ctx else {}

            # Approval rejection, execution not SUCCESS, or validation not PASS => mark failed
            approval_status = approval_rec.get("status")
            exec_status = execution_rec.get("status")
            val_status = validation_rec.get("status")

            failure_reasons = []
            if approval_status and approval_status.upper() == "REJECTED":
                failure_reasons.append(f"approval_status={approval_status}")
            if exec_status and exec_status.upper() != "SUCCESS":
                # treat PARTIAL/FAILED as non-success
                failure_reasons.append(f"execution_status={exec_status}")
            if val_status and val_status.upper() != "PASS":
                failure_reasons.append(f"validation_status={val_status}")

            if failure_reasons:
                final_error = "; ".join(failure_reasons)
                complete_execution(execution_id, "failed", final_error)
            else:
                complete_execution(execution_id, "completed")
        except Exception as status_err:
            # If any unexpected error occurs while computing final status, fail safely.
            complete_execution(execution_id, "failed", str(status_err))

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
