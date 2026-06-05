import json
import config

def fresh_context(source_files: list) -> dict:
    return {
        "source_files":   source_files,
        "entity_catalog": {},
        "file_registry":  None,
        "quality_report": {},
        "mappings":       [],
        "specification":  [],
        "readiness":      {},   # Agent 5
        "plan":           {}    # Agent 6
    }


def save_snapshot(ctx: dict, filename: str = "context_snapshot.json"):
    """Persist the full context dict so pipeline state can be resumed/reviewed later."""
    os_output_dir = config.OUTPUT_DIR
    os_output_dir.mkdir(exist_ok=True)
    with open(os_output_dir / filename, "w") as f:
        json.dump(ctx, f, indent=2, default=str)
    print(f"  [saved] {os_output_dir}/{filename}")

