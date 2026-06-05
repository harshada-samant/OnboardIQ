import sys
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import typer
from rich.console import Console
from pipeline import run_pipeline

app     = typer.Typer()
console = Console()

@app.command()
def run(
    input: str = typer.Option(
        "data/sample", "--input", "-i",
        help="Directory containing input CSV/JSON files"
    ),
    verbose: bool = typer.Option(
        True, "--verbose/--quiet",
        help="Show detailed agent logs"
    ),
    chat: bool = typer.Option(
        False, "--chat",
        help="Launch conversational assistant after pipeline completes"
    ),
):
    console.rule("[bold cyan]OnboardIQ  —  Agentic Onboarding Platform[/bold cyan]")

    try:
        ctx = run_pipeline(input, verbose=verbose, chat=chat)
        console.rule("[bold green]Pipeline complete[/bold green]")

        if not chat:
            console.print(
                "\nTip: run with [bold]--chat[/bold] to open the Conversational Assistant",
                style="dim"
            )
    except Exception as e:
        console.print(f"[bold red]Pipeline failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@app.command()
def chat(
    verbose: bool = typer.Option(False, "--verbose/--quiet")
):
    """Launch the Conversational Assistant using existing pipeline outputs (no re-run)."""
    from dotenv import load_dotenv
    load_dotenv()
    from context import fresh_context
    from tools.output_tools import load_output
    from agents.conversational_assistant import start_chat

    ctx = fresh_context([])
    for fname, key in [
        ("entity_catalog.json",   "entity_catalog"),
        ("quality_report.json",   "quality_report"),
        ("mapping_document.json", "mappings"),
    ]:
        result = load_output(fname)
        if "error" not in result:
            ctx[key] = result
        else:
            console.print(f"[yellow]Warning:[/yellow] {fname} not found — run pipeline first.")

    start_chat(ctx, verbose=verbose)


if __name__ == "__main__":
    app()
