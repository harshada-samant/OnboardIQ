import json
import uuid
import os
from datetime import datetime, timezone
import config
from pathlib import Path

def load_pipeline_config(path: str = None) -> dict:
    """
    Loads pipeline_config.json from the project base directory (config.BASE_DIR).
    Returns an empty dict if the file is missing so the pipeline still runs.
    """
    config_path = Path(path) if path else config.BASE_DIR / "pipeline_config.json"
    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[context] Warning: Failed to load pipeline_config.json: {e}")
    else:
        print(f"[context] Warning: pipeline_config.json not found at {config_path}. Using defaults.")
    return {}

# ── target alias normalisation ─────────────────────────────────────────────────

_TARGET_ALIASES = {
    "duckdb":        "duckdb",
    "duck_db":       "duckdb",
    "dynamodb":      "dynamodb",
    "dynamo_db":     "dynamodb",
}

SUPPORTED_TARGETS = {"duckdb", "dynamodb"}


def normalise_target(raw: str) -> str | None:
    """
    Returns canonical target key or None if unsupported.
    Always call this before running migration-stage agents.
    """
    if raw is None:
        return None
    return _TARGET_ALIASES.get(raw.strip().lower())


def fresh_context(source_files: list) -> dict:
    pipeline_cfg = load_pipeline_config()

    return {
        # ── existing keys (Agents 1-6) — unchanged ──────────────────────────
        "source_files":     source_files,
        "target_database":  'duckdb',          # set before Agent 7; normalise_target() first
        "entity_catalog":   {},
        "file_registry":    [],
        "quality_report":   {},
        "mappings":         [],
        "specification":    [],
        "readiness":        {},              # Agent 5
        "plan":             {},              # Agent 6

        # ── migration-stage keys (Agents 7-12) — additive ───────────────────
        "meta": {
            "run_id":           str(uuid.uuid4()),
            "pipeline_version": "1.0",
            "status":           "RUNNING",
            "created_at":       datetime.now(timezone.utc).isoformat(),
        },
        "migration": {
            "status": "NOT_STARTED"
        },                  # Agent 7 — Migration Code Generator
        "review":     {},   # Agent 8 — Migration Reviewer
        "repair":     {},   # Agent 9 — Migration Repair Agent
        "execution":  {},   # Agent 10 — Execution Agent
        "validation": {},   # Agent 11 — Validation Agent
        "approval":   {},   # Agent 12 — Approval Agent
        "audit": {
            "events": []    # append-only; all agents write here
        },
        # ── pipeline config injected here so all agents can read them ────────
        "runtime_requirements":     pipeline_cfg.get("runtime_requirements", {}),
        "operational_requirements": pipeline_cfg.get("operational_requirements", {}),
    }


# ── audit helper (used by all migration agents) ────────────────────────────────

def append_audit_event(ctx: dict, agent: str, action: str,
                       status: str, details: dict | None = None) -> None:
    """Append a structured event to context.audit.events."""
    ctx.setdefault("audit", {}).setdefault("events", []).append({
        "agent":     agent,
        "action":    action,
        "status":    status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details":   details or {},
    })


def save_snapshot(ctx: dict, filename: str = "context_snapshot.json"):
    """Persist the full context dict so pipeline state can be resumed/reviewed later."""
    os_output_dir = config.OUTPUT_DIR
    os_output_dir.mkdir(exist_ok=True)
    with open(os_output_dir / filename, "w") as f:
        json.dump(ctx, f, indent=2, default=str)
    print(f"  [saved] {os_output_dir}/{filename}")


def load_snapshot(filename: str = "context_snapshot.json") -> dict:
    """Loads a persisted context dict from the outputs folder."""
    path = config.OUTPUT_DIR / filename
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[context] Failed to load snapshot: {e}")
            return None
    return None



