import sys
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import os
from context import fresh_context, save_snapshot
from agents.discovery_agent import run_discovery_agent
from agents.profiling_agent import run_profiling_agent
from agents.mapping_agent import run_mapping_agent
from agents.specification_agent import run_specification_agent
from agents.readiness_agent import run_readiness_agent
from agents.planning_agent import run_planning_agent
from config import load_and_validate_env

SUPPORTED = {".csv", ".json", ".sql"}


def list_files(input_dir: str) -> list:
    input_path = Path(input_dir)
    if not input_path.exists() or not input_path.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_path}")
    return sorted(
        str(p) for p in input_path.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED
    )


def run_pipeline(input_dir: str, verbose: bool = True, chat: bool = False) -> dict:
    load_and_validate_env()

    files = list_files(input_dir)
    if not files:
        raise ValueError(f"No supported files found in {input_dir}.")

    print(f"Input files ({len(files)}): {[Path(f).name for f in files]}")

    ctx = fresh_context(files)

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

    # Agent 7 — Conversational Assistant (optional)
    if chat:
        from agents.conversational_assistant import start_chat
        start_chat(ctx, verbose=verbose)

    return ctx
