"""
migration_validation_agent.py
------------------------------
Agent 11 — Validation Agent

Reads context.execution and validation artifacts, runs them against the target database,
compares physical source file row counts with target row counts, and calls LLM to produce
a validation report.

Reads:  context.execution, context.migration.artifacts, context.file_registry (or file)
Writes: context["validation"]

Output shape:
  {
    "status":        "PASS | FAIL",
    "quality_score": 0,
    "issues":        [...],
    "evidence":      [...],
    "metrics": {
      "row_match":      false,
      "checksum_match": false
    },
    "llm_trace":     { ... }
  }

Failure codes: DATA_MISMATCH | INTEGRITY_VIOLATION | CHECKSUM_FAILURE
               | UNSUPPORTED_TARGET_DATABASE | LLM_UNAVAILABLE
"""

import os
import json
import time
import re
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

import config
import duckdb
from context import append_audit_event
from tools.output_tools import load_output

MAX_RETRIES = 2
RETRY_DELAY = 3

AGENT_NAME = "ValidationAgent"
PROMPT_ID  = "migration.validation.v1"


# ── Bedrock helper ─────────────────────────────────────────────────────────────

def _call_bedrock(prompt: str, system: str, label: str = "",
                  max_tokens: int = 2048, temperature: float = 0.0) -> tuple[str, dict]:
    last_error = None
    model_id   = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    start_ms   = time.time() * 1000

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client  = config.get_bedrock_client()
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
            }
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            body      = json.loads(response["body"].read())
            text      = body["content"][0]["text"]
            latency   = int(time.time() * 1000 - start_ms)
            usage     = body.get("usage", {})
            llm_trace = {
                "model":       model_id,
                "prompt_id":   PROMPT_ID,
                "temperature": temperature,
                "tokens_in":   usage.get("input_tokens", 0),
                "tokens_out":  usage.get("output_tokens", 0),
                "latency_ms":  latency,
            }
            return text, llm_trace
        except Exception as e:
            last_error = e
            wait = RETRY_DELAY
            m = re.search(r"retry in\s*([0-9]+(?:\.[0-9]+)?)s", str(e), re.IGNORECASE)
            if m:
                wait = max(RETRY_DELAY, int(float(m.group(1))))
            if attempt <= MAX_RETRIES:
                print(f"  ! [{label}] attempt {attempt} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)

    raise RuntimeError(f"LLM_UNAVAILABLE: {last_error}")


def _parse_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        parts   = cleaned.split("```")
        cleaned = parts[1] if len(parts) >= 2 else cleaned
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = min((i for i in [cleaned.find("{"), cleaned.find("[")] if i != -1), default=-1)
        if start == -1:
            raise
        close = "}" if cleaned[start] == "{" else "]"
        end   = cleaned.rfind(close)
        return json.loads(cleaned[start:end + 1])


# ── connection/resource helper ──────────────────────────────────────────────────

def _get_duckdb_connection():
    """Return a DuckDB connection to the configured database file.
    Uses config.DB_PATH (a Path) as the persistent database location.
    If the file does not exist, DuckDB will create it automatically.
    """
    try:
        # Ensure the directory exists
        db_path = config.DB_PATH
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(database=str(db_path))
        return conn
    except Exception as e:
        print(f"[validation] DuckDB connection failed: {e}")
        return None


def _get_dynamodb_resource():
    try:
        import boto3
        region = os.getenv("AWS_REGION", "us-east-1")
        return boto3.resource("dynamodb", region_name=region)
    except Exception:
        return None


# ── row counting helpers ───────────────────────────────────────────────────────

def _get_source_row_counts(context: dict = None) -> dict:
    """Returns {logical_table: total_source_rows} by reading the file registry and source files."""
    counts = {}
    try:
        registry = load_output("file_registry.json")
        if not registry or "error" in registry:
            # try to load using direct config path
            if config.FILE_REGISTRY_PATH.exists():
                with open(config.FILE_REGISTRY_PATH, "r", encoding="utf-8") as f:
                    registry = json.load(f)
            else:
                return counts
        
        # Determine records list
        records = []
        if isinstance(registry, list):
            records = registry
        elif isinstance(registry, dict):
            records = registry.get("tables") or registry.get("registry") or []

        storage = context.get("_storage") if context else None

        for rec in records:
            logical = rec.get("logical_table")
            total_rows = 0
            for sf in rec.get("source_files", []):
                # Try registry row_count first
                rc = sf.get("row_count")
                if rc is not None:
                    total_rows += int(rc)
                else:
                    fname = sf.get("file_name")
                    file_path = sf.get("file_path") or fname
                    if storage:
                        # Stream file from storage instead of reading from local filesystem
                        content = storage.read_text_file(file_path)
                        if content:
                            if file_path.lower().endswith(".csv"):
                                total_rows += len(content.strip().split("\n")) - 1
                            elif file_path.lower().endswith(".json"):
                                try:
                                    import json
                                    data = json.loads(content)
                                    total_rows += len(data) if isinstance(data, list) else 1
                                except Exception:
                                    pass
                            elif file_path.lower().endswith(".sql"):
                                inserts = re.findall(r"INSERT\s+INTO", content, re.IGNORECASE)
                                total_rows += len(inserts)
                    else:
                        # Fallback to local file read (e.g. for SQL insert estimations) if file exists locally
                        file_path_obj = config.INPUT_DIR / fname
                        if file_path_obj.exists():
                            if file_path_obj.suffix.lower() == ".csv":
                                df = pd.read_csv(file_path_obj)
                                total_rows += len(df)
                            elif file_path_obj.suffix.lower() == ".json":
                                df = pd.read_json(file_path_obj)
                                total_rows += len(df)
                            elif file_path_obj.suffix.lower() == ".sql":
                                content = file_path_obj.read_text(encoding="utf-8")
                                inserts = re.findall(r"INSERT\s+INTO", content, re.IGNORECASE)
                                total_rows += len(inserts)
            counts[logical] = total_rows
    except Exception as e:
        print(f"  ! Warning: could not parse source row counts: {e}")
    return counts


# ── LLM system prompt ──────────────────────────────────────────────────────────

VALIDATOR_SYSTEM = """You are a senior database migration QA engineer.

Given the migration execution results, source vs target row counts, and validation test logs, produce a validation report.
Verify if the target data conforms to constraints, row matches, and check for any data mismatches or checksum/integrity failures.

Based on validation results, assign:
- status: "PASS" if score >= 95 and no critical issues exist; "FAIL" otherwise.
- quality_score: integer 0-100 indicating quality.
- evidence: list of validation checks that succeeded or failed.
- issues: detailed error reports for failed checks (e.g. DATA_MISMATCH, INTEGRITY_VIOLATION, CHECKSUM_FAILURE).

Return ONLY valid JSON. No markdown.

Output format:
{
  "status": "PASS | FAIL",
  "quality_score": 98,
  "evidence": [
    {"check": "Row count validation", "status": "PASSED/FAILED", "detail": "..."}
  ],
  "issues": [
    {"type": "DATA_MISMATCH | INTEGRITY_VIOLATION | CHECKSUM_FAILURE", "description": "..."}
  ]
}
"""


# ── main agent entry point ─────────────────────────────────────────────────────

def run_migration_validation_agent(context: dict, verbose: bool = True) -> dict:
    """
    Agent 11 — Validation Agent.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION VALIDATION AGENT  (Agent 11)")
        print("=" * 60)

    target = context.get("target_database")
    if target not in ("duckdb", "dynamodb"):
        msg = f"UNSUPPORTED_TARGET_DATABASE: '{target}'"
        print(f"  x {msg}")
        context["validation"] = {"status": "FAIL", "quality_score": 0, "error": msg, "llm_trace": {}}
        append_audit_event(context, AGENT_NAME, "target_validation", "failed", {"error": msg})
        return context

    execution = context.get("execution", {})
    if not execution:
        msg = "DATA_MISMATCH: Execution status missing. Run Execution Agent first."
        print(f"  x {msg}")
        context["validation"] = {"status": "FAIL", "quality_score": 0, "error": msg, "llm_trace": {}}
        append_audit_event(context, AGENT_NAME, "input_validation", "failed", {"error": msg})
        return context

    artifacts = context.get("migration", {}).get("artifacts", [])
    val_artifacts = [a for a in artifacts if a.get("artifact_type") == "validation_test"]

    # 1. Deterministic row counting validation
    source_counts = _get_source_row_counts(context=context)
    execution_logs = execution.get("logs", [])
    
    entity_validation_runs = []
    row_match_ok = True
    checksum_match_ok = True  # Default to true, updated below

    conn = _get_duckdb_connection() if target == "duckdb" else None
    dynamo = _get_dynamodb_resource() if target == "dynamodb" else None

    for art in val_artifacts:
        entity = art.get("entity")
        path_str = art.get("path")
        
        # Determine paths
        candidate_paths = [Path(path_str), Path(config.OUTPUT_DIR).parent / path_str]
        test_path = None
        for p in candidate_paths:
            if p.exists():
                test_path = p
                break
        
        test_content = ""
        run_status = "SKIPPED"
        run_error = None
        target_rows = None

        if test_path:
            test_content = test_path.read_text(encoding="utf-8")
            
            # Mock or execute target verification
            if target == "duckdb" and conn:
                try:
                    # Run target count checks if validation sql has select count
                    m = re.search(r"select\s+count\(\*\)\s+from\s+(\w+)", test_content, re.IGNORECASE)
                    if m:
                        tbl = m.group(1)
                        # DuckDB uses execute and fetchone
                        result = conn.execute(f"SELECT COUNT(*) FROM {tbl};").fetchone()
                        target_rows = result[0] if result else 0
                    run_status = "SUCCESS"
                except Exception as ex:
                    run_error = str(ex)
                    run_status = "FAILED"
            elif target == "dynamodb" and dynamo:
                try:
                    # Run verification python script via exec
                    namespace = {"dynamodb": dynamo, "__builtins__": __builtins__}
                    exec(test_content, namespace)   # noqa: S102
                    target_rows = namespace.get("item_count")
                    run_status = "SUCCESS"
                except Exception as ex:
                    run_error = str(ex)
                    run_status = "FAILED"
            else:
                # No connection available; retrieve count from execution output log
                run_status = "SUCCESS_MOCKED"

        # If target_rows couldn't be queried directly, look up in execution logs
        if target_rows is None:
            exec_step = next((l for l in execution_logs if l.get("entity") == entity), None)
            if exec_step:
                target_rows = exec_step.get("rows", 0)
            else:
                target_rows = 0

        source_rows = source_counts.get(entity, 0)
        row_matched = (source_rows == target_rows)
        if not row_matched:
            row_match_ok = False

        entity_validation_runs.append({
            "entity":       entity,
            "artifact":     path_str,
            "source_rows":  source_rows,
            "target_rows":  target_rows,
            "row_matched":  row_matched,
            "run_status":   run_status,
            "run_error":    run_error
        })

    # Derive overall checksum / integrity heuristics
    checksum_match_ok = row_match_ok and not execution.get("failed_tasks")

    # 2. Call LLM for comprehensive summary and grading
    prompt = f"""Review the migration validation results and determine the quality report.

TARGET DATABASE: {target}
EXECUTION STATUS: {execution.get("status")}
ROWS PROCESSED: {execution.get("rows_processed")}
FAILED TASKS: {json.dumps(execution.get("failed_tasks"), indent=2)}

VALIDATION CHECKS RUN:
{json.dumps(entity_validation_runs, indent=2)}

METRICS DETECTED:
- row_match: {row_match_ok}
- checksum_match: {checksum_match_ok}

Analyze constraints compliance and issue a structured PASS/FAIL validation schema.
"""

    llm_trace = {}
    validation_report = {}
    try:
        raw, llm_trace = _call_bedrock(prompt, VALIDATOR_SYSTEM, label=AGENT_NAME)
        validation_report = _parse_json(raw)
    except Exception as e:
        if verbose:
            print(f"  ! LLM validation report failed: {e}. Falling back to default grading.")
        validation_report = {
            "status":        "PASS" if checksum_match_ok else "FAIL",
            "quality_score": 100 if checksum_match_ok else 70,
            "evidence":      [{"check": "Deterministic Match Check", "status": "PASSED" if checksum_match_ok else "FAILED", "detail": "Checked rows & tasks"}],
            "issues":        [{"type": "CHECKSUM_FAILURE", "description": "Validation failed due to discrepancies or execution tasks failure"}] if not checksum_match_ok else []
        }

    status = validation_report.get("status", "FAIL")
    quality_score = validation_report.get("quality_score", 0)

    # Hard enforcement: if execution failed or row mismatch, score cannot exceed 85 and status should reflect it
    if not checksum_match_ok or execution.get("status") == "FAILED":
        status = "FAIL"
        quality_score = min(quality_score, 80)

    context["validation"] = {
        "status":        status,
        "quality_score": quality_score,
        "issues":        validation_report.get("issues", []),
        "evidence":      validation_report.get("evidence", []),
        "metrics": {
            "row_match":      row_match_ok,
            "checksum_match": checksum_match_ok
        },
        "llm_trace":     llm_trace
    }

    append_audit_event(context, AGENT_NAME, "validate_migration", "completed", {
        "status":        status,
        "quality_score": quality_score,
        "row_match":     row_match_ok,
    })

    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION VALIDATION COMPLETE")
        print("=" * 60)
        print(f"  Status        : {status}")
        print(f"  Quality Score : {quality_score}/100")
        print(f"  Row Match     : {row_match_ok}")
        print(f"  Issues count  : {len(context['validation']['issues'])}")
        print("=" * 60)

    return context
