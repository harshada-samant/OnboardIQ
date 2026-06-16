"""
tests/run_specification.py
---------------------------
Independent test runner for the Specification Generation Agent (Agent 4).
Loads the context snapshot saved by earlier pipeline runs (Discovery,
Profiling, and Mapping) and runs specification creation using AWS Bedrock.
"""

import json
import os
import sys
from pathlib import Path

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import load_and_validate_env
from agents.specification_agent import run_specification_agent
from context import save_snapshot

def main():
    print("============================================================")
    print("  OnboardIQ  —  Agent 4 Specification Runner")
    print("============================================================")

    # Validate environment
    load_and_validate_env()

    snapshot_path = os.path.join("outputs", "context_snapshot.json")
    if not os.path.exists(snapshot_path):
        print(f"Error: Context snapshot file not found: {snapshot_path}")
        print("Please run the main pipeline or previous agents first.")
        sys.exit(1)

    # Load context snapshot
    print(f"Loading context snapshot from {snapshot_path}...")
    with open(snapshot_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    # Run Specification Agent
    try:
        # Clear cache to guarantee a fresh Bedrock generation
        spec_path = os.path.join("outputs", "migration_spec.json")
        md_spec_path = os.path.join("outputs", "migration_spec.md")
        if os.path.exists(spec_path):
            os.remove(spec_path)
        if os.path.exists(md_spec_path):
            os.remove(md_spec_path)

        ctx = run_specification_agent(ctx, verbose=True)
        print("============================================================")
        print("  Specification Generation complete")
        print("============================================================")
        
        # Save snapshot update
        save_snapshot(ctx)
        
    except Exception as e:
        print(f"Specification run failed: {e}")
        raise e

if __name__ == "__main__":
    main()
