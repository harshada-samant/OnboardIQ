import sys
from pathlib import Path
import importlib

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import os
from context import fresh_context, save_snapshot, normalise_target
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
from config import load_and_validate_env

SUPPORTED = {".csv", ".json", ".sql"}


def _reload_agent_runners() -> None:
    """
    Refresh agent modules so long-lived processes pick up code edits
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


def list_files(input_dir: str) -> list:
    input_path = Path(input_dir)
    if not input_path.exists() or not input_path.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    return sorted(
        str(p) for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED
    )


def run_pipeline(input_dir: str = None, verbose: bool = True, chat: bool = False) -> dict:
    import config
    load_and_validate_env()
    _reload_agent_runners()

    if not input_dir:
        input_dir = str(config.INPUT_DIR)

    files = list_files(input_dir)
    if not files:
        raise ValueError(f"No supported files found in {input_dir}.")


    print(f"Input files ({len(files)}): {[Path(f).name for f in files]}")

    ctx = fresh_context(files)

    # Resolve/detect target database
    schema_name = Path(config.TARGET_SCHEMA_PATH).name.lower() if config.TARGET_SCHEMA_PATH else ""
    if "dynamo" in schema_name:
        ctx["target_database"] = "dynamodb"
    elif "duck" in schema_name or "sql" in schema_name or schema_name == "target_schema.json" or "maximo" in schema_name:
        ctx["target_database"] = "duckdb"
    else:
        raise ValueError("UNSUPPORTED_TARGET_DATABASE: Target schema not recognized as DuckDB or DynamoDB.")

    # Agent 1 — Discovery
    run_discovery_agent(files, ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 2 — Profiling
    run_profiling_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 3 — Mapping
    run_mapping_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 4 — Specification
    run_specification_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 5 — Readiness
    run_readiness_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 6 — Planning
    run_planning_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 7 — Migration Code Generator
    run_migration_generator_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Agent 8 — Migration Reviewer
    run_migration_reviewer_agent(ctx, verbose=verbose)
    save_snapshot(ctx)

    # Bounded repair loop: up to 2 retries (3 total review runs)
    repair_attempts = 0
    while ctx.get("review", {}).get("status") == "REJECTED" and ctx.get("review", {}).get("fix_required") and repair_attempts < 2:
        repair_attempts += 1
        print(f"\n--- [Repair Loop] Attempt {repair_attempts} ---")
        run_migration_repair_agent(ctx, verbose=verbose)
        save_snapshot(ctx)
        
        # Re-run reviewer
        run_migration_reviewer_agent(ctx, verbose=verbose)
        save_snapshot(ctx)

    # Agent 10 — Execution Agent (runs only if approved)
    PASSING_STATUSES = {"APPROVED", "APPROVED WITH WARNINGS"}
    if ctx.get("review", {}).get("status") not in PASSING_STATUSES:
        print("  ! Skipping Execution, Validation, and Approval because Migration Review was not approved.")
        ctx["execution"] = {
            "status": "SKIPPED",
            "reason": "Migration review was not approved; downstream stages were intentionally not run.",
        }
        save_snapshot(ctx)
    else:
        run_migration_execution_agent(ctx, verbose=verbose)
        save_snapshot(ctx)

        # Agent 11 — Validation Agent
        run_migration_validation_agent(ctx, verbose=verbose)
        save_snapshot(ctx)

        # Agent 12 — Approval Agent
        run_migration_approval_agent(ctx, verbose=verbose)
        save_snapshot(ctx)

    # Agent 13 — Conversational Assistant (optional)
    if chat:
        from agents.conversational_assistant import start_chat
        start_chat(ctx, verbose=verbose)

    return ctx

