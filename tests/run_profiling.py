"""
tests/run_profiling.py
-----------------------
Independent test runner for the Data Profiling Agent (Agent 2).
Loads the context snapshot saved by Discovery Agent (Agent 1)
and runs profiling evaluations without calling the LLM.
"""

import json
import os
import sys
from pathlib import Path
from rich.console import Console

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from agents.profiling_agent import run_profiling_agent
from context import save_snapshot

console = Console()

def main():
    console.rule("[bold cyan]OnboardIQ  —  Agent 2 Profiling Runner[/bold cyan]")

    snapshot_path = os.path.join("outputs", "context_snapshot.json")
    if not os.path.exists(snapshot_path):
        console.print(f"[bold red]Error:[/bold red] Context snapshot file not found: {snapshot_path}")
        console.print("Please run the Discovery Agent first to generate the registry and catalog:")
        console.print("  [bold yellow]python tests/run_discovery.py[/bold yellow]\n")
        sys.exit(1)

    # Load context snapshot
    console.print(f"Loading context snapshot from {snapshot_path}...")
    with open(snapshot_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)

    # Run Profiling Agent
    try:
        ctx = run_profiling_agent(ctx, verbose=True)
        console.rule("[bold green]Profiling complete[/bold green]")
        
        # Save snapshot update
        save_snapshot(ctx)
        
        # Print a sample of the summary
        summary = ctx.get("quality_report", {}).get("profile_summary", {})
        console.print("\n--- PROFILING SUMMARY ---", style="bold yellow")
        console.print_json(data=summary)
    except Exception as e:
        console.print(f"[bold red]Profiling failed:[/bold red] {e}")
        raise e

if __name__ == "__main__":
    main()
