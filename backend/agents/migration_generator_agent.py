"""
migration_generator_agent.py
------------------------------
Agent 7  =  7a (Migration Script Generator) + 7b (Orchestrator Generator)

7a — LLM-based, one call per entity.
     Produces per entity: migrate_<entity>.py, rollback_<entity>.py,
     validate_<entity>.py  written to outputs/migration/<target>/<slug>/
     Stores artifact records (path + SHA-256) in context["migration"].

7b — Pure Python, no LLM.
     Reads context.migration.artifacts + context.plan.waves.
     Writes run_migration_<run_id>.py — the single wave-ordered entry point
     that Agent 10 (Execution) will run unchanged.
     Stores orchestrator path in context["migration"]["orchestrator"].

Why split:
  • 7a output (entity scripts) is reviewed by Agent 8 Pass 1 + Pass 2.
  • 7b output (orchestrator)   is reviewed by Agent 8 Pass 3.
  • Agent 10 runs only — zero code generation responsibility.

Context keys read:
  plan, mappings, specification, file_registry, quality_report,
  runtime_requirements, operational_requirements          ← from pipeline_config.json
Context keys written:
  migration  { artifacts, orchestrator, execution_manifest, summary, llm_trace }

Failure codes: MISSING_MAPPING | CODE_GENERATION_ERROR |
               UNSUPPORTED_TARGET_DATABASE | LLM_UNAVAILABLE
"""

import os
import sys
import json
import time
import re
import hashlib
from pathlib import Path

import config
from context import append_audit_event

MAX_RETRIES = 2
RETRY_DELAY = 3
AGENT_NAME  = "MigrationCodeGenerator"
PROMPT_ID   = "migration.generator.v4"


# ── Bedrock ────────────────────────────────────────────────────────────────────
def _call_bedrock(
    system_prompt: str,
    developer_prompt: str,
    user_prompt: str,
    label: str = "",
    max_tokens: int = 16000,
    temperature: float = 0.0,
):

    last_error = None
    model_id = os.getenv(
        "AWS_BEDROCK_MODEL",
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )

    start_ms = time.time() * 1000

    for attempt in range(1, MAX_RETRIES + 2):

        try:
            client = config.get_bedrock_client()

            payload = {
                "anthropic_version": "bedrock-2023-05-31",

                "system": system_prompt,

                "messages": [
                    {
                        "role": "user",
                        "content": f"""
### APPLICATION RULES
{developer_prompt}

### REQUEST
{user_prompt}
"""
                    }
                ],

                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": 0.95,
            }

            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )

            body = json.loads(response["body"].read())

            # text = body["content"][0]["text"]

            # latency = int(time.time() * 1000 - start_ms)

            # usage = body.get("usage") or {}

            # body = json.loads(response["body"].read())

            content = body.get("content", [])

            text = "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict)
            )

            latency = int(time.time() * 1000 - start_ms)

            usage = body.get("usage") or {}

            debug_dir = Path(config.OUTPUT_DIR) / "migration" / "_debug"
            debug_dir.mkdir(parents=True, exist_ok=True)

            (
                debug_dir / f"bedrock_meta_{label}.json"
            ).write_text(
                json.dumps(
                    {
                        "stop_reason": body.get("stop_reason"),
                        "content_blocks": len(content),
                        "tokens_in": usage.get("input_tokens"),
                        "tokens_out": usage.get("output_tokens"),
                        "response_chars": len(text),
                        "contains_entities": '"entities"' in text,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            (
                debug_dir / f"bedrock_raw_{label}_text.txt"
            ).write_text(
                text,
                encoding="utf-8",
            )

            print(f"[{label}] content_blocks={len(content)}")
            print(f"[{label}] stop_reason={body.get('stop_reason')}")
            print(f"[{label}] output_tokens={usage.get('output_tokens')}")


            return text, {
                "model": model_id,
                "prompt_id": PROMPT_ID,
                "temperature": temperature,
                "tokens_in": usage.get("input_tokens", 0),
                "tokens_out": usage.get("output_tokens", 0),
                "latency_ms": latency,
            }

        except Exception as e:
            last_error = e

            if attempt <= MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(f"LLM_UNAVAILABLE: {last_error}")


# def _parse_json(raw: str) -> dict:
#     cleaned = (raw or "").strip()
#     if cleaned.startswith("```"):
#         parts   = cleaned.split("```")
#         cleaned = parts[1] if len(parts) >= 2 else cleaned
#         if cleaned.lstrip().startswith("json"):
#             cleaned = cleaned.lstrip()[4:]
#     cleaned = cleaned.strip()
#     try:
#         return json.loads(cleaned)
#     except json.JSONDecodeError:
#         start = min((i for i in [cleaned.find("{"), cleaned.find("[")] if i != -1), default=-1)
#         if start == -1:
#             raise
#         close = "}" if cleaned[start] == "{" else "]"
#         end   = cleaned.rfind(close)
#         return json.loads(cleaned[start:end + 1])

# def _parse_json(raw: str) -> dict:
#     cleaned = (raw or "").strip()

#     # Fast path
#     try:
#         return json.loads(cleaned)
#     except Exception:
#         pass

#     # Extract JSON code block if present
#     json_match = re.search(
#         r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
#         cleaned,
#         flags=re.DOTALL,
#     )

#     if json_match:
#         return json.loads(json_match.group(1))

#     # Fallback: find first JSON object/array anywhere in text
#     decoder = json.JSONDecoder()

#     for i, ch in enumerate(cleaned):
#         if ch in "{[":
#             try:
#                 obj, _ = decoder.raw_decode(cleaned[i:])
#                 return obj
#             except Exception:
#                 continue

#     raise ValueError("No valid JSON found in model response")

def _parse_json(raw: str) -> dict:
    cleaned = (raw or "").strip()

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # Prefer final wrapper
    idx = cleaned.rfind('"entities"')

    if idx != -1:
        start = cleaned.rfind("{", 0, idx)

        if start != -1:
            decoder = json.JSONDecoder()
            obj, _ = decoder.raw_decode(cleaned[start:])

            if isinstance(obj, dict):
                return obj

    raise ValueError("Could not extract entities JSON")



def resolve_source_file(
    source_entity,
    target_entity,
    plan,
    file_registry_index,
):
    """
    Returns a list of one or more absolute source file paths for this entity.
    A logical table may be split across multiple physical files with the
    same schema — all of them must be loaded (see _build_file_registry_index).
    """

    # 1. PLAN — plan.waves[].entities is a list of entity-name strings,
    #    e.g. ["Assets", "WorkOrders"], NOT a list of dicts. There is no
    #    per-entity source_file info in the plan; this step only confirms
    #    the entity is part of the plan before falling through to the
    #    registry, which is the actual source of filenames.
    for wave in (
        plan.get("waves")
        or []
    ):

        for entity_name in (
            wave.get("entities")
            or []
        ):

            if entity_name == source_entity:
                break

    # 2. Registry fallback (actual filename source)
    source_files = (
        file_registry_index.get(source_entity)
        or file_registry_index.get(target_entity)
    )

    if source_files:
        return source_files

    # 3. Fail
    raise RuntimeError(
        f"MISSING_SOURCE_FILE: {source_entity}"
    )
# ── artifact helpers ───────────────────────────────────────────────────────────

def _artifact_dir(target: str) -> Path:
    base = Path(config.OUTPUT_DIR) / "migration" / target
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_artifact(content: str, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".py" and not content.startswith("#!"):
        content = f"#!{sys.executable}\n" + content
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return hashlib.sha256(content.encode()).hexdigest()


def _make_artifact_record(artifact_id, artifact_type, entity,
                           path, sha256, depends_on, version=1):
    return {
        "artifact_id":   artifact_id,
        "artifact_type": artifact_type,
        "entity":        entity,
        "path":          path,
        "sha256":        sha256,
        "version":       version,
        "depends_on":    depends_on,
    }


# ── requirement readers ────────────────────────────────────────────────────────



def _read_runtime_requirements(context: dict) -> dict:
    value = context.get("runtime_requirements")
    if not value:
        print(
            "  ! WARNING: context.runtime_requirements is empty.\n"
            "    Fix: ensure pipeline_config.json has 'runtime_requirements'\n"
            "    and fresh_context() was called before this agent."
        )
    value = dict(value or {})

    # Normalise the DUCKDB_PATH instruction: the system prompt mandates
    # con = duckdb.connect(os.environ["DUCKDB_PATH"]) for standalone
    # scripts. pipeline_config.json may say "config.DUCKDB_PATH" which
    # implies importing the pipeline's config module — that contradicts
    # the standalone-script requirement and confuses the model into
    # producing inconsistent/placeholder code. Override it here so the
    # prompt never contains a conflicting instruction.
    value["duckdb_path"] = (
        "Connect using con = duckdb.connect(config.DUCKDB_PATH). "
    )

    # Similarly, "source_data_dir" instructions referencing context['source_files']
    # assume the script can import the pipeline's context module — it can't.
    # The resolved absolute SOURCE FILES list is provided directly in the
    # per-entity prompt; scripts should use that list as-is.
    value["source_data_dir"] = (
        "Source file paths are provided as an absolute-path list in the "
        "SOURCE FILES section of this prompt. Use them exactly as given — "
        "do not look them up via any pipeline module or environment variable."
    )
    return value


def _read_operational_requirements(context: dict) -> dict:
    value = context.get("operational_requirements")
    if not value:
        print(
            "  ! WARNING: context.operational_requirements is empty.\n"
            "    Fix: ensure pipeline_config.json has 'operational_requirements'\n"
            "    and fresh_context() was called before this agent."
        )
    return value or {}
    
    
def derive_from_specification(specification):
    """
    Extract executable quality rules from specification.
    """

    if not specification:
        return {}

    result = {}

    for entity in specification:

        entity_name = (
            entity.get("target_entity")
            or entity.get("entity")
        )

        if not entity_name:
            continue

        rules = []

        columns = (
            entity.get("columns")
            or entity.get("fields")
            or []
        )

        for col in columns:

            field = (
                col.get("target_column")
                or col.get("target_field")
                or col.get("name")
            )

            if not field:
                continue

            # NOT NULL
            if col.get("nullable") is False:

                rules.append({
                    "field": field,
                    "rule": "NOT_NULL"
                })

            # VALIDATION RULES
            for validation in (
                col.get("validation_rules")
                or []
            ):

                rules.append({
                    "field": field,
                    "rule": validation
                })

            # FK
            if col.get("reference_entity"):

                rules.append({
                    "field": field,
                    "rule": "FK_EXISTS",
                    "reference_entity":
                        col["reference_entity"]
                })

        if rules:
            result[entity_name] = rules

    return result


def _derive_quality_requirements(context: dict) -> dict:
    existing = context.get("quality_requirements")
    if existing:
        return existing
    derived: dict = {}
    spec_data   = context.get("specification", {})
    entity_spec = spec_data.get("entity_specification", spec_data) if isinstance(spec_data, dict) else {}
    for entity, fields in (entity_spec.items() if isinstance(entity_spec, dict) else []):
        constraints = []
        for fld in (fields if isinstance(fields, list) else []):
            rule = fld.get("validation_rule", "")
            if rule:
                constraints.append({
                    "field":      fld.get("target_field", fld.get("source_field", "")),
                    "rule":       rule,
                    "nullable":   fld.get("nullable", True),
                    "constraint": fld.get("business_constraint", ""),
                })
        if constraints:
            derived[entity] = constraints
    quality_report = context.get("quality_report", {})
    for chk in (quality_report.get("checks", []) if isinstance(quality_report, dict) else []):
        ent, fld, kind = chk.get("entity",""), chk.get("field",""), chk.get("check_type","")
        if ent and fld and kind:
            derived.setdefault(ent, []).append({"field": fld, "rule": kind, "source": "quality_report"})
    return derived


def _build_dependency_map(plan: dict) -> dict:
    dep_map: dict = {}
    prev: list    = []
    for wave in sorted(plan.get("waves", []), key=lambda w: w.get("wave_number", 0)):
        entities = wave.get("entities", [])
        for ent in entities:
            dep_map[ent] = (
                wave.get("depends_on", [])
                or list(prev)
            )
        prev = entities
    return dep_map


def _build_file_registry_index(context: dict) -> dict:
    """
    Returns {logical_table: [absolute_path_to_source_file, ...]}.

    IMPORTANT: a logical table can be split across multiple physical files
    with the same schema (has_duplicates=true means "split files", NOT
    "duplicate rows"). e.g. WorkOrders = work_orders.csv (10 rows) +
    workorders01.csv (10 rows) = 20 rows total. Both files must be loaded
    or 50% of the data is silently dropped.

    'source_files[].file_name' is therefore the source of truth, not
    'representative_file' (which is only a single canonical reference,
    e.g. for schema_fingerprint comparison upstream — not a migration
    instruction to use only one file).

    Each filename is joined with config.INPUT_DIR to produce an absolute
    path the generated migration scripts can open directly with
    READ_CSV / open() without needing to know INPUT_DIR themselves.
    """
    index: dict = {}
    for entry in (context.get("file_registry") or []):
        t = entry.get("logical_table", "")
        source_files = entry.get("source_files", [])
        paths = [
            str(config.INPUT_DIR / sf["file_name"])
            for sf in source_files
            if sf.get("file_name") and sf.get("has_data", True)
        ]
        if not paths:
            # fallback for malformed entries with no source_files
            f = entry.get("representative_file", "")
            if f:
                paths = [str(config.INPUT_DIR / f)]
        if t and paths:
            index[t] = paths
    return index


# ── 7a system prompts ──────────────────────────────────────────────────────────

_SYSTEM_DUCKDB = """You are a senior Python engineer writing DuckDB migration scripts.

==============================================================
ABSOLUTE RULE: OUTPUT IS PYTHON SOURCE CODE, NEVER RAW SQL FILES.
Every value in migration_script / rollback_script / validation_script is the
FULL TEXT of a .py file starting with "import duckdb" — NOT a .sql
file, NOT SQL statements with comments, NOT a template with
"-- Example:" placeholders. Every script must be directly runnable
with: python <script>.py
==============================================================

CONNECTION RULE (do not deviate):
    con = duckdb.connect(config.DUCKDB_PATH)

The script must be fully standalone with zero imports beyond:
duckdb, os, sys, json, logging, datetime.

Fill in this exact skeleton for migrate_<entity>.py — replace ALL_CAPS
placeholders with real, working code. Do not leave SQL comments or
"-- Example" placeholders anywhere in the output.

```python
import duckdb
import os
import sys
import json
from datetime import datetime, timezone

RUN_ID = os.environ.get("RUN_ID", "manual")
ENTITY = "<entity_name>"

def log(stage, **fields):
    print(json.dumps({"run_id": RUN_ID, "entity": ENTITY, "stage": stage,
                       "timestamp": datetime.now(timezone.utc).isoformat(), **fields}), flush=True)

def main():
    log("ingestion_start")
    con = duckdb.connect(config.DUCKDB_PATH)
    try:
        con.execute("BEGIN TRANSACTION")

        con.execute('''
            CREATE TABLE IF NOT EXISTS <TARGET_TABLE> (
                <COLUMN DEFINITIONS WITH TYPES AND CONSTRAINTS>
            )
        ''')

        # SOURCE_FILES is a Python list — if it has more than one path,
        # build a single READ_CSV call across all of them, e.g.:
        #   con.execute("CREATE OR REPLACE TEMP TABLE staging AS "
        #                "SELECT * FROM READ_CSV(?, header=true)", [SOURCE_FILES])
        # (DuckDB's READ_CSV accepts a list of file paths directly.)
        source_files = <SOURCE FILES LIST FROM PROMPT>
        con.execute(
            "CREATE OR REPLACE TEMP TABLE staging AS "
            "SELECT * FROM READ_CSV(?, header=true, union_by_name=true)",
            [source_files],
        )
        log("ingestion_end", rows_read=con.execute("SELECT COUNT(*) FROM staging").fetchone()[0])

        log("transform_start")
        # Idempotent: clear existing rows for this load before inserting
        con.execute("DELETE FROM <TARGET_TABLE>")

        # Apply EVERY field mapping's transformation_logic here using SQL
        # expressions inside the SELECT (e.g. UPPER(TRIM(asset_no)) AS c_asset_id).
        con.execute('''
            INSERT INTO <TARGET_TABLE> (<TARGET COLUMNS>)
            SELECT
                <ONE EXPRESSION PER FIELD MAPPING, WITH TRANSFORMATION APPLIED>
            FROM staging
        ''')
        log("transform_end")

        log("load_start")
        rows_written = con.execute("SELECT COUNT(*) FROM <TARGET_TABLE>").fetchone()[0]
        con.execute("COMMIT")
        log("load_end", rows_written=rows_written)

    except Exception as e:
        con.execute("ROLLBACK")
        log("load_end", status="FAILED", error_code=type(e).__name__, error_message=str(e))
        raise
    finally:
        con.close()

if __name__ == "__main__":
    main()
```

Apply the same standalone-script, log(), try/finally pattern to
rollback_<entity>.py (DROP TABLE IF EXISTS <TARGET_TABLE>, or guarded
DELETE) and validate_<entity>.py (compare row counts, run every rule
in QUALITY REQUIREMENTS as a SELECT that must return 0 violating rows,
raise AssertionError on any failure, log validation_start/validation_end).

Return ONLY one valid JSON object.

STRICT RULES:
- Output must parse with json.loads().
- No markdown.
- No code fences.
- Every script must be a JSON string.
- Escape all internal quotes and newlines.
- Do not terminate a JSON field early.
- Do not emit any text outside JSON.



Output format:
{
  "entities": [
    {
      "entity": "<EntityName>" ,
      "migration_script":   "" ,
      "rollback_script":    "" ,
      "validation_script":  "" ,
      "depends_on":      []
    }
  ]
}
"""

_SYSTEM_DYNAMO = """You are a senior cloud engineer specialising in AWS DynamoDB migrations.

Produce three standalone Python scripts per entity using boto3.

1. migrate_<entity>.py  — batch-write items with exponential back-off
2. rollback_<entity>.py — scan + batch_delete all written items
3. validate_<entity>.py — count items, check key uniqueness, verify required attributes

All scripts must:
- CRITICAL: SOURCE FILES may contain MULTIPLE file paths for one entity —
  this means the logical table is split across multiple files with the
  SAME schema (NOT duplicate data). You MUST read and combine rows from
  ALL listed files before writing to DynamoDB. Loading only one file
  silently drops data.
- Apply all field_mappings transformations
- Implement every item in RUNTIME REQUIREMENTS exactly
- Emit structured JSON log lines with the exact stage names and metric fields
  from OPERATIONAL REQUIREMENTS
- Batch writes in chunks of 25; retry with exponential back-off + jitter
- Read AWS_REGION, DYNAMODB_TABLE from os.environ — never hardcode credentials
- Validate all QUALITY REQUIREMENTS before writing

Return ONLY valid JSON. No markdown.

Output format:
{
  "entities": [
    {
      "entity": "<EntityName>",
      "migration_script":   "<full Python script>",
      "rollback_script":    "<full Python script>",
      "validation_script":  "<full Python script>",
      "depends_on":         ["<entity>", ...]
    }
  ]
}
"""


def _build_developer_prompt(
    target,
    runtime_requirements,
    operational_requirements,
):
    if target == "duckdb":
        key_migrate, key_rollback, key_validate = "migration_script", "rollback_script", "validation_script"
    else:
        key_migrate, key_rollback, key_validate = "migration_script", "rollback_script", "validation_script"

    return f"""
Generate EXACTLY 3 standalone Python scripts.

Artifacts:
1 migrate_<entity>.py
2 rollback_<entity>.py
3 validate_<entity>.py

REMINDER: every "{key_migrate}" / "{key_rollback}" / "{key_validate}" value
is the COMPLETE TEXT of a runnable .py file (starts with "import ...").
It is NEVER raw SQL, NEVER a template, NEVER contains "-- Example" or
placeholder comments. Every transformation, table name, and column from
FIELD MAPPINGS and SPECIFICATION must be written out as real code.

Requirements:
- Implement runtime requirements
- Implement validation checks
- Emit operational metrics
- Use exact source file paths from SOURCE FILES (load ALL of them if more than one)
- Never hardcode credentials
- Return ONLY valid JSON

Output:

{{
 "entities":[
   {{
     "entity":"",
     "{key_migrate}":"",
     "{key_rollback}":"",
     "{key_validate}":"",
     "depends_on":[]
   }}
 ]
}}

RUNTIME:
{json.dumps(runtime_requirements, indent=2)}

OPERATIONAL:
{json.dumps(operational_requirements, indent=2)}
"""



def _build_user_prompt(
    target,
    entity,
    mappings,
    specification,
    source_files,
    depends_on,
    wave_context,
):

    return f"""
Generate migration scripts.

TARGET:
{target}

ENTITY:
{entity}

SOURCE FILES (absolute paths — use exactly as-is in READ_CSV / COPY / open(), do not modify or join with another directory.
If more than one path is listed, the table is split across multiple files with the SAME schema — load and combine ALL of them, do not use only the first one):
{json.dumps(source_files, indent=2)}

DEPENDS ON:
{json.dumps(depends_on)}

FIELD MAPPINGS:
{json.dumps(mappings, indent=2)}

SPECIFICATION:
{json.dumps(specification, indent=2)}

WAVE:
{json.dumps(wave_context, indent=2)}
"""


# ── 7a artifact persistence ────────────────────────────────────────────────────

def _persist_duckdb_artifacts(entity_results, art_dir, run_id):
    artifacts, ordered_steps = [], []
    for i, ent in enumerate(entity_results):
        name       = ent["entity"]
        slug       = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        depends_on = ent.get("depends_on", [])
        for art_type, key, suffix in [
            ("migration_script",   "migration_script",  "migrate"),
            ("rollback_script",    "rollback_script",   "rollback"),
            ("validation_script", "validation_script", "validate"),
        ]:
            content  = ent.get(key, f"# No {art_type} for {name}\n")
            rel_path = f"outputs/migration/duckdb/{slug}/{suffix}_{slug}.py"
            abs_path = art_dir / slug / f"{suffix}_{slug}.py"
            sha      = _write_artifact(content, abs_path)
            art_id   = f"mig_{slug}_{art_type}_v1"
            artifacts.append(_make_artifact_record(art_id, art_type, name, rel_path, sha, depends_on))
        slug2 = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        ordered_steps.append({
            "step": i + 1, "entity": name, "depends_on": depends_on,
            "artifacts": [f"mig_{slug2}_{t}_v1" for t in
                          ("migration_script", "rollback_script", "validation_script")],
        })
    return artifacts, ordered_steps


def _persist_dynamo_artifacts(entity_results, art_dir, run_id):
    artifacts, ordered_steps = [], []
    for i, ent in enumerate(entity_results):
        name       = ent["entity"]
        slug       = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        depends_on = ent.get("depends_on", [])
        for art_type, key, suffix in [
            ("migration_script",   "migration_script",  "migrate"),
            ("rollback_script",    "rollback_script",   "rollback"),
            ("validation_script", "validation_script", "validate"),
        ]:
            content  = ent.get(key, f"# No {art_type} for {name}\n")
            rel_path = f"outputs/migration/dynamodb/{slug}/{suffix}_{slug}.py"
            abs_path = art_dir / slug / f"{suffix}_{slug}.py"
            sha      = _write_artifact(content, abs_path)
            art_id   = f"mig_{slug}_{art_type}_v1"
            artifacts.append(_make_artifact_record(art_id, art_type, name, rel_path, sha, depends_on))
        slug2 = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        ordered_steps.append({
            "step": i + 1, "entity": name, "depends_on": depends_on,
            "artifacts": [f"mig_{slug2}_{t}_v1" for t in
                          ("migration_script", "rollback_script", "validation_script")],
        })
    return artifacts, ordered_steps


# ══════════════════════════════════════════════════════════════════════════════
#  7a  — Migration Script Generator
# ══════════════════════════════════════════════════════════════════════════════

def run_7a_script_generator(context: dict, verbose: bool = True) -> dict:
    """
    Agent 7a — generates per-entity migrate / rollback / validate Python scripts.
    One LLM call per entity. Writes scripts to disk.
    Populates context["migration"]["artifacts"] and context["migration"]["execution_manifest"].
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  AGENT 7a — MIGRATION SCRIPT GENERATOR")
        print("=" * 60)

    target = context.get("target_database")
    if target not in ("duckdb", "dynamodb"):
        msg = f"UNSUPPORTED_TARGET_DATABASE: '{target}'"
        print(f"  x {msg}")
        context["migration"] = {"status": "FAILED", "error": msg}
        append_audit_event(context, AGENT_NAME, "7a_target_validation", "failed", {"error": msg})
        return context

    mappings_data = context.get("mappings", {})
    if not mappings_data:
        msg = "MISSING_MAPPING: context.mappings is empty. Run Mapping Agent first."
        print(f"  x {msg}")
        context["migration"] = {"status": "FAILED", "error": msg}
        append_audit_event(context, AGENT_NAME, "7a_input_validation", "failed", {"error": msg})
        return context

    plan                     = context.get("plan", {})
    spec_data                = context.get("specification", {})
    compact_mappings         = mappings_data.get("mappings", mappings_data) if isinstance(mappings_data, dict) else mappings_data
    compact_spec             = spec_data.get("entity_specification", spec_data) if isinstance(spec_data, dict) else spec_data
    file_registry_index      = _build_file_registry_index(context)
    dependency_map           = _build_dependency_map(plan)
    wave_context             = plan.get("waves", [])
    runtime_requirements     = _read_runtime_requirements(context)
    operational_requirements = _read_operational_requirements(context)
    # Unwrap specification: derive_from_specification expects a list of entity dicts,
    # but context["specification"] is {"entity_specification": {...}, "_meta": {...}}.
    # Convert the inner dict {"EntityName": [fields]} → [{"target_entity": name, "columns": fields}]
    _raw_spec = context.get("specification", {})
    _entity_spec_dict = (
        _raw_spec.get("entity_specification", _raw_spec)
        if isinstance(_raw_spec, dict)
        else _raw_spec
    )
    if isinstance(_entity_spec_dict, dict):
        _spec_list = [
            {"target_entity": ent_name, "columns": ent_fields}
            for ent_name, ent_fields in _entity_spec_dict.items()
            if isinstance(ent_fields, list)  # skip "_meta" and non-list values
        ]
    else:
        _spec_list = _entity_spec_dict if isinstance(_entity_spec_dict, list) else []

    quality_requirements = (
        derive_from_specification(_spec_list)
        or _derive_quality_requirements(context)
    )

    entity_list = compact_mappings if isinstance(compact_mappings, list) else (
        [{"source_entity": k, "field_mappings": v} for k, v in compact_mappings.items()]
        if isinstance(compact_mappings, dict) else []
    )

    if verbose:
        names = [e.get("source_entity", e.get("entity", "?")) for e in entity_list]
        print(f"  Target     : {target}")
        print(f"  Entities   : {names}")
        print(f"  Runtime req: {'✓' if runtime_requirements else 'MISSING'}")
        print(f"  Ops req    : {'✓' if operational_requirements else 'MISSING'}")

    system              = _SYSTEM_DUCKDB if target == "duckdb" else _SYSTEM_DYNAMO
    all_entity_results  = []
    aggregated_trace    = {"model": "", "prompt_id": PROMPT_ID, "temperature": 0.0,
                           "tokens_in": 0, "tokens_out": 0, "latency_ms": 0}

    for mapping_entry in entity_list:
        source_entity  = mapping_entry.get("source_entity", mapping_entry.get("entity", "Unknown"))
        target_entity  = mapping_entry.get("target_entity", source_entity)

        try:
            field_mappings = mapping_entry.get("field_mappings", [])
            entity_spec    = (compact_spec.get(target_entity) or compact_spec.get(source_entity) or []
                              ) if isinstance(compact_spec, dict) else []
            # resolve_source_file returns a list of one or more absolute paths
            # (config.INPUT_DIR / each source_files[].file_name), and raises
            # MISSING_SOURCE_FILE if the entity isn't in file_registry —
            # so no silent fallback filename is possible here.
            source_files = resolve_source_file(
                source_entity,
                target_entity,
                context["plan"],
                file_registry_index,
            )

            entity_quality = {
                source_entity: quality_requirements.get(source_entity, []),
                target_entity: quality_requirements.get(target_entity, []),
            }
            depends_on = dependency_map.get(source_entity, dependency_map.get(target_entity, []))

            developer_prompt = _build_developer_prompt(
                target,
                runtime_requirements,
                operational_requirements,
            )

            user_prompt = _build_user_prompt(
                target,
                target_entity,
                field_mappings,
                entity_spec,
                source_files,
                depends_on,
                wave_context,
            )

            if verbose:
                print(f"  → [{source_entity}] generating scripts (files: {source_files})...")

            try:
                raw, trace = _call_bedrock(
                    system_prompt=system,
                    developer_prompt=developer_prompt,
                    user_prompt=user_prompt,
                    label=source_entity,
                )

            except RuntimeError as e:
                msg = f"LLM_UNAVAILABLE: {e}"
                print(f"  x [{source_entity}] {msg}")
                context["migration"] = {"status": "FAILED", "error": msg, "llm_trace": aggregated_trace}
                append_audit_event(context, AGENT_NAME, "7a_llm_call", "failed",
                                   {"error": msg, "entity": source_entity})
                return context

            aggregated_trace["model"]      = trace["model"]
            aggregated_trace["tokens_in"]  += trace.get("tokens_in", 0)
            aggregated_trace["tokens_out"] += trace.get("tokens_out", 0)
            aggregated_trace["latency_ms"] += trace.get("latency_ms", 0)

            try:
                result = _parse_json(raw)
                block  = result.get("entities", [])
                if isinstance(block, dict):
                    block = [block]

                # ── diagnostic: validate the shape the LLM actually returned ──
                expected_keys = (
                    # ("migration_sql", "rollback_sql", "validation_sql") if target == "duckdb"
                    # else
                    ("migration_script", "rollback_script", "validation_script")
                )
                for ent_block in block:
                    ent_name = ent_block.get("entity", "?")
                    missing  = [k for k in expected_keys if not ent_block.get(k)]

                    # Content-shape check (duckdb only): each value must look
                    # like Python source, not raw SQL or a placeholder template.
                    shape_issues = []
                    if target == "duckdb":
                        for key in expected_keys:
                            content = ent_block.get(key, "") or ""
                            stripped = content.strip()
                            looks_like_sql = stripped.upper().startswith(("BEGIN;", "BEGIN TRANSACTION", "--", "CREATE TABLE", "DROP TABLE"))
                            has_import     = "import duckdb" in content or "import os" in content
                            has_placeholder = "-- Example" in content or "placeholder" in content.lower()
                            if content and (looks_like_sql or not has_import or has_placeholder):
                                shape_issues.append(key)

                    if missing or shape_issues:
                        # Dump the raw response so the actual shape can be inspected.
                        debug_dir = Path(config.OUTPUT_DIR) / "migration" / target / "_debug"
                        debug_dir.mkdir(parents=True, exist_ok=True)
                        debug_path = debug_dir / f"raw_response_{source_entity}.json"
                        debug_path.write_text(raw, encoding="utf-8")
                        if missing:
                            print(
                                f"  ! [{ent_name}] LLM response is missing key(s) {missing}. "
                                f"Got keys: {list(ent_block.keys())}. "
                                f"Raw response saved to {debug_path} for inspection."
                            )
                        if shape_issues:
                            print(
                                f"  ! [{ent_name}] These fields look like raw SQL / placeholder "
                                f"templates instead of runnable Python: {shape_issues}. "
                                f"Raw response saved to {debug_path} for inspection."
                            )

                all_entity_results.extend(block)
            except Exception as e:
                msg = f"CODE_GENERATION_ERROR: parse failed for '{source_entity}' — {e}"
                print(f"  x [{source_entity}] {msg}")
                # Dump raw response on parse failure too.
                debug_dir = Path(config.OUTPUT_DIR) / "migration" / target / "_debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"raw_response_{source_entity}_PARSE_FAILED.txt").write_text(raw, encoding="utf-8")
                context["migration"] = {"status": "FAILED", "error": msg, "llm_trace": aggregated_trace}
                append_audit_event(context, AGENT_NAME, "7a_parse", "failed",
                                   {"error": msg, "entity": source_entity})

                return context

        except Exception as e:
            # Catch-all: anything unexpected (KeyError, MISSING_SOURCE_FILE
            # RuntimeError from resolve_source_file, etc.) is reported with
            # entity context instead of propagating as a bare crash.
            import traceback
            msg = f"CODE_GENERATION_ERROR: unexpected error for '{source_entity}' — {e}"
            print(f"  x [{source_entity}] {msg}")
            print(traceback.format_exc())
            context["migration"] = {"status": "FAILED", "error": msg, "llm_trace": aggregated_trace}
            append_audit_event(context, AGENT_NAME, "7a_unexpected_error", "failed",
                               {"error": msg, "entity": source_entity})
            return context


    art_dir = _artifact_dir(target)
    run_id  = context.get("meta", {}).get("run_id", "unknown")

    try:
        if target == "duckdb":
            artifacts, ordered_steps = _persist_duckdb_artifacts(all_entity_results, art_dir, run_id)
        else:
            artifacts, ordered_steps = _persist_dynamo_artifacts(all_entity_results, art_dir, run_id)
    except Exception as e:
        msg = f"CODE_GENERATION_ERROR: write failed — {e}"
        print(f"  x {msg}")
        context["migration"] = {"status": "FAILED", "error": msg, "llm_trace": aggregated_trace}
        append_audit_event(context, AGENT_NAME, "7a_write", "failed", {"error": msg})
        return context

    # Initialise migration block — 7b will add orchestrator key
    context["migration"] = {
        "artifacts": artifacts,
        "execution_manifest": {"run_id": run_id, "ordered_steps": ordered_steps},
        "summary": {
            "migration_artifact_count":  sum(1 for a in artifacts if a["artifact_type"] == "migration_script"),
            "rollback_artifact_count":   sum(1 for a in artifacts if a["artifact_type"] == "rollback_script"),
            "validation_artifact_count": sum(1 for a in artifacts if a["artifact_type"] == "validation_script"),
        },
        "llm_trace": aggregated_trace,
        "status":    "SCRIPTS_GENERATED",   # 7b will update to READY_FOR_REVIEW
    }

    append_audit_event(context, AGENT_NAME, "7a_generate", "completed", {
        "target": target, "artifact_count": len(artifacts),
        "entities": [e["entity"] for e in all_entity_results],
    })

    if verbose:
        s = context["migration"]["summary"]
        print(f"  Migration scripts   : {s['migration_artifact_count']}")
        print(f"  Rollback scripts    : {s['rollback_artifact_count']}")
        print(f"  Validation scripts  : {s['validation_artifact_count']}")
        print(f"  Status              : SCRIPTS_GENERATED")

    return context


# ══════════════════════════════════════════════════════════════════════════════
#  7b  — Orchestrator Generator  (pure Python, no LLM)
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_path(rel_path: str) -> Path | None:
    for c in [Path(rel_path), Path(config.OUTPUT_DIR).parent / rel_path]:
        if c.exists():
            return c
    return None


def _build_orchestrator_code(ordered_steps, artifacts, run_id, target):
    """Build run_migration_<run_id>.py source as a string."""
    step_defs = []
    for step in ordered_steps:
        entity  = step["entity"]
        mig_art = next((a for a in artifacts
                        if a["entity"] == entity and a["artifact_type"] == "migration_script"), None)
        path    = str(_resolve_path(mig_art["path"])) if mig_art and _resolve_path(mig_art["path"]) else None
        step_defs.append({
            "step":       step["step"],
            "entity":     entity,
            "depends_on": step.get("depends_on", []),
            "script_path": path,
        })

    timeout    = int(os.getenv("MIGRATION_STEP_TIMEOUT", "300"))
    interpreter = sys.executable
    step_json   = json.dumps(step_defs, indent=4)

    return f'''#!{interpreter}
"""
run_migration_{run_id}.py
--------------------------
Auto-generated orchestrator — do NOT edit by hand.
Target : {target}
Run ID : {run_id}

Runs each entity migration script in wave order so that tables created
in wave N are visible to scripts in wave N+1 via the shared DuckDB file.

Usage:
    python run_migration_{run_id}.py

Required env vars:
    DUCKDB_PATH       — path to the shared DuckDB database file
    SOURCE_DATA_DIR   — (optional) directory containing source CSV files
"""

import os, sys, json, subprocess, time
from datetime import datetime, timezone

INTERPRETER = r"{interpreter}"
TIMEOUT     = {timeout}
RUN_ID      = "{run_id}"
TARGET      = "{target}"

STEPS = {step_json}


def log(record: dict):
    print(json.dumps(record), flush=True)


def run_step(step: dict) -> dict:
    entity      = step["entity"]
    script_path = step["script_path"]
    step_num    = step["step"]

    if script_path is None:
        err = f"Script path not found for {{entity}}"
        log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
              "stage": "step_error", "status": "FAILED", "error": err}})
        return {{"step": step_num, "entity": entity, "status": "FAILED", "rows": 0, "error": err}}

    log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
          "stage": "step_start", "status": "RUNNING",
          "depends_on": step.get("depends_on", []),
          "timestamp": datetime.now(timezone.utc).isoformat()}})

    t0 = time.time()
    try:
        result      = subprocess.run(
            [INTERPRETER, script_path],
            capture_output=True, text=True,
            env=os.environ.copy(), timeout=TIMEOUT,
        )
        duration_ms = int((time.time() - t0) * 1000)
        stdout, stderr = result.stdout.strip(), result.stderr.strip()

        if result.returncode != 0:
            err = f"Exit {{result.returncode}}. stderr: {{stderr[-500:]}}"
            log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
                  "stage": "step_end", "status": "FAILED",
                  "duration_ms": duration_ms, "error": err}})
            return {{"step": step_num, "entity": entity, "status": "FAILED",
                     "rows": 0, "error": err, "stdout": stdout, "stderr": stderr}}

        rows = 0
        for line in stdout.splitlines():
            try:
                entry = json.loads(line)
                if entry.get("stage") == "load_end" and "rows_written" in entry:
                    rows = int(entry["rows_written"]); break
            except (json.JSONDecodeError, ValueError):
                continue

        log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
              "stage": "step_end", "status": "SUCCESS",
              "duration_ms": duration_ms, "rows_written": rows}})
        return {{"step": step_num, "entity": entity, "status": "SUCCESS",
                 "rows": rows, "error": None}}

    except subprocess.TimeoutExpired:
        err = f"Timed out after {{TIMEOUT}}s"
        log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
              "stage": "step_end", "status": "FAILED", "error": err}})
        return {{"step": step_num, "entity": entity, "status": "FAILED", "rows": 0, "error": err}}


def main():
    duckdb_path = config.DUCKDB_PATH
    if not duckdb_path:
        print(json.dumps({{"run_id": RUN_ID, "stage": "init", "status": "FAILED",
                           "error": "DUCKDB_PATH not set in config"}}))
        sys.exit(1)

    log({{"run_id": RUN_ID, "stage": "orchestrator_start", "target": TARGET,
          "total_steps": len(STEPS), "duckdb_path": duckdb_path,
          "timestamp": datetime.now(timezone.utc).isoformat()}})

    results, failed = [], []
    for step in sorted(STEPS, key=lambda s: s["step"]):
        r = run_step(step)
        results.append(r)
        if r["status"] != "SUCCESS":
            failed.append(r)
            log({{"run_id": RUN_ID, "stage": "orchestrator_abort",
                  "reason": f"Step {{r['step']}} ({{r['entity']}}) failed. Stopping.",
                  "failed_steps": failed}})
            sys.exit(1)

    log({{"run_id": RUN_ID, "stage": "orchestrator_end", "status": "SUCCESS",
          "total_steps": len(STEPS),
          "total_rows_written": sum(r.get("rows", 0) for r in results),
          "timestamp": datetime.now(timezone.utc).isoformat()}})


if __name__ == "__main__":
    main()
'''


def run_7b_orchestrator_generator(context: dict, verbose: bool = True) -> dict:
    """
    Agent 7b — writes run_migration_<run_id>.py from context.migration.
    Pure Python, no LLM. Precondition: 7a must have run successfully.
    Adds context["migration"]["orchestrator"] = { path, sha256 }.
    Updates context["migration"]["status"] = "READY_FOR_REVIEW".
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  AGENT 7b — ORCHESTRATOR GENERATOR")
        print("=" * 60)

    migration = context.get("migration", {})
    if migration.get("status") not in ("SCRIPTS_GENERATED",):
        msg = "PRECONDITION_FAILED: run 7a first (status must be SCRIPTS_GENERATED)"
        print(f"  x {msg}")
        append_audit_event(context, AGENT_NAME, "7b_precondition", "failed", {"error": msg})
        return context

    artifacts     = migration.get("artifacts", [])
    manifest      = migration.get("execution_manifest", {})
    ordered_steps = manifest.get("ordered_steps", [])
    run_id        = manifest.get("run_id", context.get("meta", {}).get("run_id", "unknown"))
    target        = context.get("target_database", "duckdb")

    code     = _build_orchestrator_code(ordered_steps, artifacts, run_id, target)
    out_dir  = Path(config.OUTPUT_DIR) / "migration" / target
    out_dir.mkdir(parents=True, exist_ok=True)
    orch_path = out_dir / f"run_migration_{run_id}.py"
    sha256    = _write_artifact(code, orch_path)
    rel_path  = f"outputs/migration/{target}/run_migration_{run_id}.py"

    context["migration"]["orchestrator"] = {
        "path":   rel_path,
        "sha256": sha256,
    }
    context["migration"]["status"] = "READY_FOR_REVIEW"

    append_audit_event(context, AGENT_NAME, "7b_orchestrator", "completed", {
        "path": rel_path, "steps": len(ordered_steps),
    })

    if verbose:
        print(f"  Orchestrator : {orch_path}")
        print(f"  Steps        : {len(ordered_steps)}")
        print(f"  Status       : READY_FOR_REVIEW")

    return context


# ══════════════════════════════════════════════════════════════════════════════
#  Combined entry point  (7a → 7b in sequence)
# ══════════════════════════════════════════════════════════════════════════════

def run_migration_generator_agent(context: dict, verbose: bool = True) -> dict:
    """
    Runs 7a then 7b in sequence.
    Call this from your pipeline runner instead of calling 7a / 7b separately
    unless you need to inspect intermediate state.
    """
    context = run_7a_script_generator(context, verbose=verbose)
    if context.get("migration", {}).get("status") == "FAILED":
        return context
    context = run_7b_orchestrator_generator(context, verbose=verbose)
    return context
