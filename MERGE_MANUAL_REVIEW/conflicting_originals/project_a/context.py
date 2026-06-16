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
    print(f"[debug] saving snapshot to {os_output_dir / filename}")
    with open(os_output_dir / filename, "w") as f:
        json.dump(ctx, f, indent=2, default=str)
    print(f"  [saved] {os_output_dir}/{filename}")


def load_snapshot(filename: str = "context_snapshot.json") -> dict:
    """Loads a persisted context dict from the outputs folder."""
    path = config.OUTPUT_DIR / filename
    print(f"[debug] looking for snapshot at {path}")
    print(f"[debug] file exists: {path.exists()}")
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[context] Failed to load snapshot: {e}")
            return None
    return None

