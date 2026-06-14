"""
tests/run_discovery.py
-----------------------
Entry point for the Discovery Agent.
"""

import sys
import json
import os
from pathlib import Path
from rich.console import Console

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import load_and_validate_env
from agents.discovery_agent import run_discovery_agent

# Initialize and validate environment
load_and_validate_env()

# Shared context store — all agents read/write this
context = {
    "source_files":    [],
    "entity_catalog":  None,
    "quality_report":  None,
    "mappings":        None,
    "specification":   None,
    "readiness":       None,
    "plan":            None
}

file_paths = [
    "data/assets.csv",
    "data/workorders.csv",
    "data/sample/assets.csv",
    "data/sample/locations.csv",
    "data/sample/users.csv"
]

context["source_files"] = file_paths
console = Console()

console.rule("[bold cyan]OnboardIQ  —  Agentic Onboarding Platform[/bold cyan]")

# Run the agent
context = run_discovery_agent(file_paths, context, verbose=True)

console.rule("[bold green]Pipeline complete[/bold green]")
# Print final catalog
console.print("\n--- ENTITY CATALOG ---", style="bold yellow")
console.print(json.dumps(context["entity_catalog"], indent=2))
