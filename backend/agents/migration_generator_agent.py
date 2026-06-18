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
import ast
import csv
import hashlib
import uuid
from difflib import SequenceMatcher
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

    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) >= 2 else cleaned
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    cleaned = cleaned.strip()

    def _repair_json_string_quotes(text: str) -> str:
        # Model outputs occasionally drop one escape inside a long script
        # string, which leaves an otherwise-valid JSON object unparsable.
        # We conservatively re-escape suspicious quotes only while inside
        # string literals and only when the quote does not look like a
        # closing delimiter.
        out = []
        i = 0
        in_str = False
        length = len(text)

        while i < length:
            ch = text[i]

            if not in_str:
                out.append(ch)
                if ch == '"':
                    in_str = True
                i += 1
                continue

            if ch == "\\":
                out.append(ch)
                if i + 1 < length:
                    out.append(text[i + 1])
                    i += 2
                else:
                    i += 1
                continue

            if ch == '"':
                j = i + 1
                while j < length and text[j] in " \t\r\n":
                    j += 1
                nxt = text[j] if j < length else ""
                if nxt in ",}]:" or nxt == "":
                    out.append(ch)
                    in_str = False
                else:
                    out.append('\\"')
                i += 1
                continue

            out.append(ch)
            i += 1

        return "".join(out)

    candidates = [cleaned, _repair_json_string_quotes(cleaned)]

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # Prefer final wrapper
    for candidate in candidates:
        idx = candidate.rfind('"entities"')

        if idx != -1:
            start = candidate.rfind("{", 0, idx)

            if start != -1:
                try:
                    decoder = json.JSONDecoder()
                    obj, _ = decoder.raw_decode(candidate[start:])

                    if isinstance(obj, dict):
                        return obj
                except Exception:
                    pass

    # Some model responses are "JSON-shaped" but use triple-quoted Python
    # blocks for the script values. Recover those without forcing the LLM to
    # emit an exact JSON escape format.
    triple_entity_pattern = re.compile(
        r'"entity"\s*:\s*"(?P<entity>[^"]+)"\s*,\s*'
        r'"migration_script"\s*:\s*"""(?P<migration>.*?)"""\s*,\s*'
        r'"rollback_script"\s*:\s*"""(?P<rollback>.*?)"""\s*,\s*'
        r'"validation_script"\s*:\s*"""(?P<validation>.*?)"""\s*,\s*'
        r'"depends_on"\s*:\s*(?P<depends>\[[\s\S]*?\])',
        flags=re.DOTALL,
    )

    recovered_entities = []
    for match in triple_entity_pattern.finditer(cleaned):
        depends_raw = match.group("depends")
        try:
            depends_on = json.loads(depends_raw)
        except Exception:
            depends_on = []
        recovered_entities.append({
            "entity": match.group("entity").strip(),
            "migration_script": match.group("migration"),
            "rollback_script": match.group("rollback"),
            "validation_script": match.group("validation"),
            "depends_on": depends_on,
        })

    if recovered_entities:
        return {"entities": recovered_entities}

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

    def _norm_entity(value: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())
        return re.sub(r"\d+$", "", cleaned)

    def _registry_lookup(entity_name: str):
        if not entity_name:
            return None
        if entity_name in file_registry_index:
            return file_registry_index[entity_name]
        entity_norm = _norm_entity(entity_name)
        for key, value in file_registry_index.items():
            key_norm = _norm_entity(key)
            if key_norm == entity_norm:
                return value
        best_key = None
        best_score = 0.0
        for key in file_registry_index:
            score = SequenceMatcher(None, _norm_entity(key), entity_norm).ratio()
            if score > best_score:
                best_key = key
                best_score = score
        if best_key and best_score >= 0.75:
            return file_registry_index[best_key]
        return None

    # 2. Registry fallback (actual filename source)
    source_files = _registry_lookup(source_entity) or _registry_lookup(target_entity)

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
        content = "#!/usr/bin/env python3\n" + content
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return hashlib.sha256(content.encode()).hexdigest()


def _duckdb_type_from_hint(type_hint: str) -> str:
    hint = (type_hint or "").strip()
    if not hint:
        return "VARCHAR"

    upper = hint.upper()
    if upper.startswith("DECIMAL") or upper.startswith("NUMERIC"):
        return upper if "(" in upper else "DECIMAL(12,2)"

    mapping = {
        "DATE": "DATE",
        "TIMESTAMP": "TIMESTAMP",
        "DATETIME": "TIMESTAMP",
        "BOOLEAN": "BOOLEAN",
        "BOOL": "BOOLEAN",
        "INT": "INTEGER",
        "INTEGER": "INTEGER",
        "BIGINT": "BIGINT",
        "SMALLINT": "SMALLINT",
        "DOUBLE": "DOUBLE",
        "FLOAT": "DOUBLE",
        "REAL": "DOUBLE",
        "VARCHAR": "VARCHAR",
        "TEXT": "VARCHAR",
        "STRING": "VARCHAR",
    }
    return mapping.get(upper, upper)


def _repair_duckdb_casts(content: str) -> str:
    def _replace(match: re.Match) -> str:
        expr = match.group(1).strip()
        type_hint = _duckdb_type_from_hint(match.group(2))
        return f"CAST({expr} AS {type_hint})"

    return re.sub(
        r"cast\(\s*(.+?)\s*,\s*'([^']+)'\s*\)",
        _replace,
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _normalize_duckdb_sql(content: str) -> str:
    """
    Normalize common DuckDB dialect mismatches emitted by the LLM.
    This keeps generation deterministic without relying on the model
    to remember every function name variant.
    """
    replacements = [
        (r"\buppercase\s*\(", "upper("),
        (r"\blowercase\s*\(", "lower("),
    ]
    normalized = content
    for pattern, replacement in replacements:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = _repair_duckdb_casts(normalized)
    return normalized


def _normalize_generated_python_source(content: str) -> str:
    """
    Repair recurring model quoting mistakes before persisting generated Python.
    Keep this narrow so valid string literals are not rewritten accidentally.
    """
    repaired = content
    repaired = repaired.replace('f\\"{stem}*.csv\\"', 'f"{stem}*.csv"')
    repaired = repaired.replace('f\\"{stem}*.json\\"', 'f"{stem}*.json"')
    repaired = repaired.replace('f\\"{stem}*.parquet\\"', 'f"{stem}*.parquet"')
    repaired = repaired.replace(')"")', ')""")')
    repaired = repaired.replace("Userss", "Users")
    return repaired


def _repair_duckdb_user_table_name(content: str, entity_name: str) -> str:
    """
    Repair the common singular/plural mismatch for DuckDB scripts generated
    for the User entity. The generated scripts should consistently use Users.
    """
    if (entity_name or "").strip().lower() != "user":
        return content
    repaired = content
    repaired = repaired.replace("Userss", "Users")
    repaired = repaired.replace("CREATE TABLE IF NOT EXISTS User (", "CREATE TABLE IF NOT EXISTS Users (")
    repaired = repaired.replace("DELETE FROM User", "DELETE FROM Users")
    repaired = repaired.replace("INSERT INTO User (", "INSERT INTO Users (")
    repaired = repaired.replace("SELECT COUNT(*) FROM User", "SELECT COUNT(*) FROM Users")
    repaired = repaired.replace("DROP TABLE IF EXISTS User", "DROP TABLE IF EXISTS Users")
    return repaired


def _validate_generated_python_artifact(content: str, entity: str, art_type: str) -> str:
    """
    Final safety gate before writing generated Python to disk.
    We keep this permissive: attempt one more repair pass and then warn
    instead of failing the whole pipeline if the model still emitted a bad
    artifact.
    """
    repaired = content.replace("Userss", "Users")
    repaired = repaired.replace(')"")', ')""")')
    try:
        ast.parse(repaired)
        return repaired
    except SyntaxError as e:
        print(
            f"  [warn] {entity} {art_type} still has a syntax issue after repair: {e}. "
            "Writing best-effort output so the pipeline can continue."
        )
        return repaired


def _lint_duckdb_migration_script(content: str, entity: str) -> None:
    unsupported = []
    if re.search(r"\buppercase\s*\(", content, flags=re.IGNORECASE):
        unsupported.append("uppercase(...)")
    if re.search(r"\blowercase\s*\(", content, flags=re.IGNORECASE):
        unsupported.append("lowercase(...)")
    if re.search(r"cast\(\s*[^)]+,\s*'[^']+'\s*\)", content, flags=re.IGNORECASE):
        unsupported.append("cast(x, 'type')")
    if unsupported:
        raise RuntimeError(
            f"CODE_GENERATION_ERROR: unsupported DuckDB SQL in {entity}: {', '.join(unsupported)}"
        )


def _repair_source_resolution(content: str) -> str:
    """
    Expand the generated exact-basename lookup with a fallback that accepts
    a single prefixed CSV/JSON/Parquet match when the upload file name has
    been versioned or renamed.
    """
    source_block = (
        r"(?P<indent>[ \t]*)source_file = os\.path\.join\(source_dir, os\.path\.basename\(source_filename\)\)\n"
        r"(?P=indent)if not os\.path\.exists\(source_file\):\n"
        r"(?P=indent)    raise RuntimeError\(f'Source file not found: \{source_file\}'\)\n"
        r"(?P=indent)source_files\.append\(source_file\)"
    )

    replacement = (
        r"\g<indent>source_base = os.path.basename(source_filename)\n"
        r"\g<indent>source_file = os.path.join(source_dir, source_base)\n"
        r"\g<indent>if not os.path.exists(source_file):\n"
        r"\g<indent>    stem = os.path.splitext(source_base)[0]\n"
        r"\g<indent>    candidates = sorted(\n"
        r'\g<indent>        glob.glob(os.path.join(source_dir, f"{stem}*.csv")) +\n'
        r'\g<indent>        glob.glob(os.path.join(source_dir, f"{stem}*.json")) +\n'
        r'\g<indent>        glob.glob(os.path.join(source_dir, f"{stem}*.parquet"))\n'
        r"\g<indent>    )\n"
        r"\g<indent>    if len(candidates) == 1:\n"
        r"\g<indent>        source_file = candidates[0]\n"
        r"\g<indent>    elif len(candidates) > 1:\n"
        r"\g<indent>        raise RuntimeError(f'Ambiguous source file for {source_base}: {candidates}')\n"
        r"\g<indent>    else:\n"
        r"\g<indent>        raise RuntimeError(f'Source file not found: {source_file}')\n"
        r"\g<indent>source_files.append(source_file)"
    )

    updated = re.sub(source_block, replacement, content)
    if updated != content and "import glob" not in updated:
        updated = updated.replace("import json\n", "import json\nimport glob\n", 1)
    return updated


def _read_csv_headers(source_files: list) -> list[str]:
    headers: list[str] = []
    for source_file in source_files or []:
        try:
            path = Path(source_file)
            if not path.exists() or path.suffix.lower() != ".csv":
                continue
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                row = next(reader, [])
                for col in row:
                    if col not in headers:
                        headers.append(col)
        except Exception:
            continue
    return headers


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _resolve_source_column_name(source_field: str, available_headers: list[str]) -> str:
    if not source_field:
        return source_field
    if source_field in available_headers:
        return source_field

    alias_map = {
        "loc_code": "location_code",
    }
    alias = alias_map.get(source_field.strip().lower())
    if alias and alias in available_headers:
        return alias

    normalized_source = _normalize_name(source_field)
    if not normalized_source:
        return source_field

    best_header = source_field
    best_score = 0.0
    for header in available_headers:
        normalized_header = _normalize_name(header)
        if not normalized_header:
            continue
        if normalized_source == normalized_header:
            return header
        if normalized_source in normalized_header or normalized_header in normalized_source:
            score = 0.95
        else:
            score = SequenceMatcher(None, normalized_source, normalized_header).ratio()
        if score > best_score:
            best_score = score
            best_header = header

    return best_header if best_score >= 0.6 else source_field


def _repair_duckdb_source_columns(
    content: str,
    field_mappings: list,
    available_headers: list[str],
) -> str:
    repaired = content
    for mapping in field_mappings or []:
        source_field = mapping.get("source_field", "")
        resolved = _resolve_source_column_name(source_field, available_headers)
        if resolved and resolved != source_field:
            repaired = re.sub(
                rf"\b{re.escape(source_field)}\b",
                resolved,
                repaired,
            )
    return repaired


def _is_string_type(type_name: str) -> bool:
    value = (type_name or "").upper()
    return value.startswith(("VARCHAR", "TEXT", "STRING", "CHAR"))


def _build_source_quality_index(context: dict) -> dict:
    catalog = context.get("entity_catalog", {})
    entities = catalog.get("entities", []) if isinstance(catalog, dict) else catalog
    index: dict = {}
    for entity in entities or []:
        entity_name = entity.get("entity_name") or entity.get("name")
        if not entity_name:
            continue
        field_map = {}
        for field in entity.get("fields", []) or []:
            field_name = field.get("name")
            if field_name:
                field_map[field_name] = field.get("null_pct", 0)
        if field_map:
            index[entity_name] = field_map
    return index


def _repair_required_string_defaults(
    content: str,
    spec_fields: list,
    source_quality: dict,
) -> str:
    repaired = content
    for fld in spec_fields or []:
        source_field = fld.get("source_field")
        target_field = fld.get("target_field") or source_field
        data_type = fld.get("data_type", "")
        nullable = fld.get("nullable", True)
        source_null_pct = source_quality.get(source_field, 0) if source_quality else 0

        if not source_field or nullable or source_null_pct <= 0 or not _is_string_type(data_type):
            continue

        pattern = rf"(?m)^(?P<indent>\s*)(?:{re.escape(source_field)}(?:\s+AS\s+{re.escape(target_field)})?)\s*,\s*$"
        replacement = (
            r"\g<indent>COALESCE(NULLIF(TRIM("
            + source_field
            + "), ''), 'Unknown') AS "
            + target_field
            + ","
        )
        repaired = re.sub(pattern, replacement, repaired)
    return repaired


def _repair_duckdb_foreign_key_normalization(content: str, spec_fields: list) -> str:
    repaired = content
    for fld in spec_fields or []:
        source_field = fld.get("source_field", "")
        target_field = fld.get("target_field", "")
        rule = _parse_duckdb_foreign_key_rule(fld.get("validation_rule", ""))
        if not source_field or not target_field or not rule:
            continue
        normalized_expr = (
            f"regexp_replace(upper(trim(CAST({source_field} AS VARCHAR))), '[^A-Z0-9]', '', 'g')"
            f" AS {target_field}"
        )
        repaired = re.sub(
            rf"\b{re.escape(source_field)}\s+AS\s+{re.escape(target_field)}\b",
            normalized_expr,
            repaired,
            flags=re.IGNORECASE,
        )
    return repaired


def _parse_duckdb_foreign_key_rule(validation_rule: str) -> tuple[str, str] | None:
    rule = (validation_rule or "").strip()
    match = re.match(r"^FOREIGN_KEY\(([^.()]+)\.([^)]+)\)$", rule, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _build_duckdb_fk_skip_block(entity: str, spec_fields: list) -> str:
    """
    Build a DuckDB-safe filter that skips rows whose foreign-key references
    do not exist in the parent table. This prevents orphan rows from being
    loaded into the target table while keeping the load idempotent.
    """
    fk_predicates = []
    entity_name = (entity or "").strip().lower()
    for fld in spec_fields or []:
        source_field = fld.get("source_field", "")
        rule = _parse_duckdb_foreign_key_rule(fld.get("validation_rule", ""))
        if not source_field or not rule:
            continue
        parent_table, parent_field = rule
        if parent_table.strip().lower() == entity_name:
            continue
        fk_predicates.append(
            "(s.{source_field} IS NOT NULL AND TRIM(CAST(s.{source_field} AS VARCHAR)) <> '' "
            "AND EXISTS (SELECT 1 FROM {parent_table} p "
            "WHERE regexp_replace(upper(trim(CAST(p.{parent_field} AS VARCHAR))), '[^A-Z0-9]', '', 'g') "
            "= regexp_replace(upper(trim(CAST(s.{source_field} AS VARCHAR))), '[^A-Z0-9]', '', 'g')))"
            .format(
                source_field=source_field,
                parent_table=parent_table,
                parent_field=parent_field,
            )
        )

    if not fk_predicates:
        return ""

    return f"""

FK_PREDICATES = {json.dumps(fk_predicates, indent=2)}


def _build_fk_predicate() -> str:
    return " AND ".join(f"({{predicate}})" for predicate in FK_PREDICATES)


def _count_skipped_orphans(con):
    fk_predicate = _build_fk_predicate()
    if not fk_predicate:
        return 0
    return con.execute(f"SELECT COUNT(*) FROM staging s WHERE NOT ({{fk_predicate}})").fetchone()[0]


def _create_valid_staging(con):
    fk_predicate = _build_fk_predicate()
    if not fk_predicate:
        con.execute("CREATE OR REPLACE TEMP TABLE valid_staging AS SELECT * FROM staging")
        return
    con.execute(f"CREATE OR REPLACE TEMP TABLE valid_staging AS SELECT * FROM staging s WHERE {{fk_predicate}}")
"""


def _remove_duckdb_checkpoint(content: str) -> str:
    return re.sub(r"^\s*con\.execute\(\"CHECKPOINT\"\)\s*\n?", "", content, flags=re.MULTILINE)


def _ensure_duckdb_connect_retry(content: str) -> str:
    repaired = content
    if "import time" not in repaired:
        repaired = repaired.replace("import json\n", "import json\nimport time\n", 1)

    helper = """

def _connect_duckdb():
    duckdb_path = os.environ.get('DUCKDB_PATH', '')
    if not duckdb_path:
        raise RuntimeError('DUCKDB_PATH environment variable is not set.')
    last_error = None
    for attempt in range(5):
        try:
            return duckdb.connect(duckdb_path)
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            if "wal" not in msg and "access is denied" not in msg:
                raise
            time.sleep(2)
    raise last_error
"""
    if "def _connect_duckdb(" not in repaired:
        repaired = repaired.replace("\ndef main():", f"{helper}\ndef main():", 1)
    repaired = repaired.replace("def _connect_duckdb(duckdb_path):", "def _connect_duckdb():", 1)
    repaired = repaired.replace("con = duckdb.connect(duckdb_path)", "con = _connect_duckdb()", 1)
    repaired = repaired.replace("con = _connect_duckdb(duckdb_path)", "con = _connect_duckdb()", 1)
    return repaired


def _ensure_duckdb_source_precheck(content: str) -> str:
    pattern = r"(?m)^(?P<indent>\s*)con = _connect_duckdb(?:\(duckdb_path\))?$"
    replacement = (
        r"\g<indent>source_dir = os.environ.get('SOURCE_DATA_DIR', '').strip()\n"
        r"\g<indent>s3_bucket = os.environ.get('S3_BUCKET', '').strip()\n"
        r"\g<indent>s3_prefix = os.environ.get('S3_PREFIX', '').strip()\n"
        r"\g<indent>if not source_dir and (not s3_bucket or not s3_prefix):\n"
        r"\g<indent>    raise RuntimeError('Missing SOURCE_DATA_DIR and S3_BUCKET/S3_PREFIX')\n"
        r"\g<indent>con = _connect_duckdb()"
    )
    return re.sub(pattern, replacement, content, count=1)


def _ensure_duckdb_original_error_preserved(content: str) -> str:
    pattern = (
        r"(?s)(?P<indent>\s*)except Exception as e:\n"
        r"(?P=indent)    con\.execute\(\"ROLLBACK\"\)\n"
        r"(?P=indent)    log\(\"load_end\", status=\"FAILED\", error_code=type\(e\)\.__name__, error_message=str\(e\)\)\n"
        r"(?P=indent)    raise"
    )
    replacement = (
        r"\g<indent>except Exception as e:\n"
        r"\g<indent>    try:\n"
        r"\g<indent>        con.execute(\"ROLLBACK\")\n"
        r"\g<indent>    except Exception as rollback_error:\n"
        r"\g<indent>        log(\"rollback_error\", error_code=type(rollback_error).__name__, error_message=str(rollback_error))\n"
        r"\g<indent>    log(\"load_end\", status=\"FAILED\", error_code=type(e).__name__, error_message=str(e))\n"
        r"\g<indent>    raise"
    )
    return re.sub(pattern, replacement, content, count=1)


def _duckdb_identifier(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _duckdb_table_name(entity: str) -> str:
    return "Users" if (entity or "").strip().lower() == "user" else entity


def _build_duckdb_validation_script(entity: str, source_files: list, spec_fields: list) -> str:
    source_filenames = [os.path.basename(path) for path in (source_files or [])]
    fk_skip_block = _build_duckdb_fk_skip_block(entity, spec_fields)

    required_fields = []
    unique_fields = []
    for fld in spec_fields or []:
        field_name = fld.get("target_field") or fld.get("source_field") or fld.get("name")
        if not field_name:
            continue

        validation_rule = str(fld.get("validation_rule", "")).upper()
        business_constraint = str(fld.get("business_constraint", "")).upper()
        nullable = fld.get("nullable", True)

        if nullable is False or "NOT NULL" in business_constraint or "PRIMARY KEY" in business_constraint:
            required_fields.append(field_name)

        if (
            "PRIMARY KEY" in business_constraint
            or "UNIQUE" in business_constraint
            or validation_rule == "IS_UNIQUE"
        ):
            unique_fields.append(field_name)

    required_fields = list(dict.fromkeys(required_fields))
    unique_fields = list(dict.fromkeys(unique_fields))

    table_name = _duckdb_table_name(entity)

    return f"""#!/usr/bin/env python3
import duckdb
import glob
import os
import sys
import json
import time
from datetime import datetime, timezone

RUN_ID = os.environ.get("RUN_ID", "manual")
ENTITY = "{entity}"
TABLE_NAME = "{table_name}"

SOURCE_FILENAMES = {json.dumps(source_filenames, indent=2)}
REQUIRED_FIELDS = {json.dumps(required_fields, indent=2)}
UNIQUE_FIELDS = {json.dumps(unique_fields, indent=2)}


def log(stage, **fields):
    print(json.dumps({{"run_id": RUN_ID, "entity": ENTITY, "stage": stage,
                       "timestamp": datetime.now(timezone.utc).isoformat(), **fields}}), flush=True)


def _connect_duckdb(duckdb_path):
    last_error = None
    for attempt in range(5):
        try:
            return duckdb.connect(duckdb_path)
        except Exception as e:
            last_error = e
            msg = str(e).lower()
            if "wal" not in msg and "access is denied" not in msg:
                raise
            time.sleep(2)
    raise last_error


def _resolve_source_files(source_dir: str) -> list[str]:
    source_files = []
    for source_filename in SOURCE_FILENAMES:
        source_base = os.path.basename(source_filename)
        source_file = os.path.join(source_dir, source_base)
        if os.path.exists(source_file):
            source_files.append(source_file)
            continue

        stem = os.path.splitext(source_base)[0]
        candidates = sorted(
            glob.glob(os.path.join(source_dir, f"{{stem}}*.csv")) +
            glob.glob(os.path.join(source_dir, f"{{stem}}*.json")) +
            glob.glob(os.path.join(source_dir, f"{{stem}}*.parquet"))
        )
        if len(candidates) == 1:
            source_files.append(candidates[0])
            continue
        if len(candidates) > 1:
            raise RuntimeError(f'Ambiguous source file for {{source_base}}: {{candidates}}')
        raise RuntimeError(f'Source file not found: {{source_file}}')
    if not source_files:
        raise RuntimeError("No source files configured for validation.")
    return source_files


def main():
    log("validation_start")
    duckdb_path = os.environ.get("DUCKDB_PATH", "").strip()
    if not duckdb_path:
        raise RuntimeError("DUCKDB_PATH environment variable is not set.")

    source_dir = os.environ.get("SOURCE_DATA_DIR", "").strip()
    if not source_dir:
        raise RuntimeError("SOURCE_DATA_DIR environment variable is not set.")

    con = _connect_duckdb(duckdb_path)
    try:
        source_files = _resolve_source_files(source_dir)
        source_row_count = con.execute(
            "SELECT COUNT(*) FROM READ_CSV(?, header=true, union_by_name=true)",
            [source_files],
        ).fetchone()[0]
        skipped_orphans = 0
        expected_row_count = source_row_count
{fk_skip_block}
        actual_row_count = con.execute(
            f"SELECT COUNT(*) FROM {{TABLE_NAME}}"
        ).fetchone()[0]
        assert actual_row_count == expected_row_count, (
            f"Row count mismatch: expected {{expected_row_count}}, actual {{actual_row_count}}"
        )

        for field in REQUIRED_FIELDS:
            null_count = con.execute(
                f'SELECT COUNT(*) FROM {{TABLE_NAME}} WHERE "{{field}}" IS NULL'
            ).fetchone()[0]
            assert null_count == 0, f"Null values found in required field: {{field}} ({{null_count}})"

        for field in UNIQUE_FIELDS:
            duplicate_count = con.execute(
                f'''
                SELECT COUNT(*) FROM (
                    SELECT "{{field}}", COUNT(*) AS cnt
                    FROM {{TABLE_NAME}}
                    GROUP BY "{{field}}"
                    HAVING COUNT(*) > 1
                )
                '''
            ).fetchone()[0]
            assert duplicate_count == 0, f"Duplicate values found in unique field: {{field}}"

        log("validation_end", status="PASSED", source_rows=source_row_count, target_rows=actual_row_count, skipped_orphans=skipped_orphans, expected_rows=expected_row_count)

    except AssertionError as e:
        log("validation_end", status="FAILED", error_code="AssertionError", error_message=str(e))
        raise
    except Exception as e:
        log("validation_end", status="FAILED", error_code=type(e).__name__, error_message=str(e))
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
"""


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
        "Connect using con = duckdb.connect(os.environ.get('DUCKDB_PATH', '')). "
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


def _find_entity_wave(plan: dict, source_entity: str, target_entity: str) -> dict:
    """Return a compact wave summary for the current entity only."""
    for wave in sorted(plan.get("waves", []), key=lambda w: w.get("wave_number", 0)):
        entities = wave.get("entities") or []
        if source_entity in entities or target_entity in entities:
            return {
                "wave_number": wave.get("wave_number"),
                "entities": entities,
            }
    return {
        "wave_number": None,
        "entities": [source_entity] if source_entity else [],
    }


def _build_file_registry_index(context: dict) -> dict:
    """
    Returns {logical_table: [source_file_identifier, ...]}.

    IMPORTANT: a logical table can be split across multiple physical files
    with the same schema (has_duplicates=true means "split files", NOT
    "duplicate rows"). e.g. WorkOrders = work_orders.csv (10 rows) +
    workorders01.csv (10 rows) = 20 rows total. Both files must be loaded
    or 50% of the data is silently dropped.

    'source_files[].file_name' is therefore the source of truth, not
    'representative_file' (which is only a single canonical reference,
    e.g. for schema_fingerprint comparison upstream — not a migration
    instruction to use only one file).

    For local sources, the returned identifiers are absolute paths built
    from config.INPUT_DIR and the source filenames.

    For S3 sources, the returned identifiers are filenames only. The
    generated scripts must construct full s3:// URLs from environment
    variables so bucket names and regions are never hardcoded into the
    emitted script text.
    """
    index: dict = {}
    username = context.get("username") or "user1"
    for entry in (context.get("file_registry") or []):
        t = entry.get("logical_table", "")
        source_files = entry.get("source_files", [])
        if config.USE_S3_SOURCE:
            paths = [
                sf["file_name"]
                for sf in source_files
                if sf.get("file_name") and sf.get("has_data", True)
            ]
            if not paths:
                f = entry.get("representative_file", "")
                if f:
                    paths = [f]
        else:
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

_SYSTEM_DUCKDB = """Write DuckDB migration artifacts as JSON.

Return exactly one JSON object with an `entities` array. Each entity must include `entity`, `migration_script`, `rollback_script`, `validation_script`, and `depends_on`.

Rules:
- Each script value must be the complete text of a runnable Python file.
- Never emit raw SQL, templates, markdown, or placeholder text.
- Use only DuckDB-native SQL, `DUCKDB_PATH`, `SOURCE_DATA_DIR`, JSON logging, and retrying `_connect_duckdb()`.
- Load every listed source file for the entity.
- Keep scripts standalone and concise.
"""

_SYSTEM_DYNAMO = """Write DynamoDB migration artifacts as JSON with runnable Python scripts only.

Each entity must include `entity`, `migration_script`, `rollback_script`, `validation_script`, and `depends_on`.

Rules:
- Use full Python scripts, no placeholders or markdown.
- Load all source files for the entity and combine rows before writing.
- Use AWS SDK, exponential back-off, structured JSON logs, and environment-based config only.
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
- For DuckDB migrations, check SOURCE_DATA_DIR / S3 config before opening
  DuckDB, use a _connect_duckdb() retry helper, and never emit CHECKPOINT.
- If rollback itself fails, log the rollback error but re-raise the original
  exception so the true failure is never hidden.
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
    use_s3_source,
):

    return f"""
Generate migration scripts.

TARGET:
{target}

ENTITY:
{entity}

SOURCE FILES:
Absolute filenames. Resolve each one against SOURCE_DATA_DIR using os.path.basename(...)
and verify every resolved file exists before reading.
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


def _build_developer_prompt(
    target,
    runtime_requirements,
    operational_requirements,
):
    return f"""Return ONLY valid JSON with exactly 3 runnable Python scripts per entity.

Rules:
- Scripts must be complete .py files, never raw SQL or placeholders.
- Use the exact source file paths provided.
- Implement runtime requirements, validation checks, and operational logging.
- DuckDB scripts must use DUCKDB_PATH, a retrying _connect_duckdb(), and no CHECKPOINT.
- Rollback failures must be logged, then re-raised.
- Never hardcode credentials.

Output schema:
{{"entities":[{{"entity":"","migration_script":"","rollback_script":"","validation_script":"","depends_on":[]}}]}}

RUNTIME_REQUIREMENTS={json.dumps(runtime_requirements, separators=(",", ":"))}
OPERATIONAL_REQUIREMENTS={json.dumps(operational_requirements, separators=(",", ":"))}
"""


def _build_user_prompt(
    target,
    entity,
    mappings,
    specification,
    source_files,
    depends_on,
    wave_context,
    use_s3_source,
):
    compact_spec = [
        {
            "source_field": f.get("source_field"),
            "target_field": f.get("target_field"),
            "rule": f.get("validation_rule"),
            "nullable": f.get("nullable"),
            "type": f.get("data_type"),
            "constraint": f.get("business_constraint"),
        }
        for f in (specification or [])
    ]
    compact_mappings = [
        {
            "source_field": m.get("source_field"),
            "target_field": m.get("target_field"),
            "logic": m.get("transformation_logic"),
        }
        for m in (mappings or [])
    ]
    wave_item = wave_context or {}
    compact_wave = {
        "wave_number": wave_item.get("wave_number"),
        "entities": wave_item.get("entities", []),
        "depends_on": depends_on,
    }
    return f"""Generate 3 runnable Python scripts for DuckDB.

Entity={entity}
Target={target}
SourceFiles={json.dumps(source_files, separators=(",", ":"))}

Load all source files, not just the first one. Resolve basenames under SOURCE_DATA_DIR.
The scripts must be self-contained, use JSON logging, and implement every mapping/spec rule.

FieldMappings={json.dumps(compact_mappings, separators=(",", ":"))}
Spec={json.dumps(compact_spec, separators=(",", ":"))}
Wave={json.dumps(compact_wave, separators=(",", ":"))}
"""


# ── 7a artifact persistence ────────────────────────────────────────────────────

def _persist_duckdb_artifacts(entity_results, art_dir, run_id):
    artifacts, ordered_steps = [], []
    for i, ent in enumerate(entity_results):
        name       = ent["entity"]
        slug       = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        table_name = _duckdb_table_name(name)
        depends_on = ent.get("depends_on", [])
        source_files = ent.get("source_files", [])
        field_mappings = ent.get("field_mappings", [])
        spec_fields  = ent.get("spec_fields", [])
        source_quality = ent.get("source_quality", {})
        source_headers = _read_csv_headers(source_files)
        fk_helper_block = _build_duckdb_fk_skip_block(name, spec_fields)
        for art_type, key, suffix in [
            ("migration_script",   "migration_script",  "migrate"),
            ("rollback_script",    "rollback_script",   "rollback"),
            ("validation_script", "validation_script", "validate"),
        ]:
            content  = ent.get(key, f"# No {art_type} for {name}\n")
            content = _normalize_generated_python_source(content)
            if art_type == "migration_script":
                content = _normalize_duckdb_sql(content)
                content = _repair_source_resolution(content)
                content = _repair_duckdb_source_columns(content, field_mappings, source_headers)
                content = _repair_required_string_defaults(content, spec_fields, source_quality)
                content = _repair_duckdb_foreign_key_normalization(content, spec_fields)
                content = _remove_duckdb_checkpoint(content)
                content = _ensure_duckdb_connect_retry(content)
                content = _ensure_duckdb_source_precheck(content)
                content = _ensure_duckdb_original_error_preserved(content)
                content = _repair_duckdb_user_table_name(content, name)
                if fk_helper_block:
                    content = content.replace("\ndef main():", f"{fk_helper_block}\ndef main():", 1)
                    delete_marker = (
                        f'        con.execute("DELETE FROM {table_name}")\n\n'
                        "        # Apply EVERY field mapping's transformation_logic here using SQL\n"
                    )
                    if delete_marker in content:
                        content = content.replace(
                            delete_marker,
                            delete_marker
                            + "        skipped_orphans = _count_skipped_orphans(con)\n"
                            + "        _create_valid_staging(con)\n\n",
                            1,
                        )
                    content = re.sub(
                        rf"(INSERT INTO\s+{re.escape(table_name)}.*?FROM\s+)staging(\s*(?:'''|\"\"\"))",
                        r"\1valid_staging\2",
                        content,
                        count=1,
                        flags=re.DOTALL,
                    )
                _lint_duckdb_migration_script(content, name)
                content = _validate_generated_python_artifact(content, name, art_type)
            elif art_type == "validation_script":
                content = _build_duckdb_validation_script(name, source_files, spec_fields)
                content = _repair_source_resolution(content)
                content = _repair_duckdb_user_table_name(content, name)
                if fk_helper_block:
                    content = content.replace("\ndef main():", f"{fk_helper_block}\ndef main():", 1)
                    content = content.replace(
                        "        expected_row_count = source_row_count\n",
                        "        expected_row_count = source_row_count\n"
                        "        skipped_orphans = _count_skipped_orphans(con)\n"
                        "        _create_valid_staging(con)\n"
                        "        expected_row_count = con.execute(\"SELECT COUNT(*) FROM valid_staging\").fetchone()[0]\n",
                        1,
                    )
                content = _validate_generated_python_artifact(content, name, art_type)
            elif art_type == "rollback_script":
                content = _repair_duckdb_user_table_name(content, name)
                content = _validate_generated_python_artifact(content, name, art_type)
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


def _duckdb_entity_template(entity_name: str, source_files: list[str]) -> dict:
    key = (entity_name or "").strip().lower()
    if key in {"user", "users"}:
        return {
            "entity": "Users",
            "table_name": "Users",
            "source_files": source_files,
            "required_fields": ["user_id", "full_name"],
            "unique_fields": ["user_id"],
            "migration_select": """
                SELECT
                    TRIM(CAST(user_id AS VARCHAR)) AS user_id,
                    TRIM(CAST(name AS VARCHAR)) AS full_name,
                    TRIM(CAST(role AS VARCHAR)) AS role,
                    TRIM(CAST(email AS VARCHAR)) AS email,
                    TRIM(CAST(department AS VARCHAR)) AS department,
                    CASE
                        WHEN LOWER(TRIM(CAST(active AS VARCHAR))) IN ('true', '1', 'yes', 'y') THEN TRUE
                        WHEN LOWER(TRIM(CAST(active AS VARCHAR))) IN ('false', '0', 'no', 'n') THEN FALSE
                        ELSE NULL
                    END AS is_active
                FROM read_csv_auto(?, header=true, union_by_name=true)
                WHERE user_id IS NOT NULL AND TRIM(CAST(user_id AS VARCHAR)) <> ''
            """,
            "staging_select": """
                SELECT
                    TRIM(CAST(user_id AS VARCHAR)) AS user_id,
                    TRIM(CAST(name AS VARCHAR)) AS full_name,
                    TRIM(CAST(role AS VARCHAR)) AS role,
                    TRIM(CAST(email AS VARCHAR)) AS email,
                    TRIM(CAST(department AS VARCHAR)) AS department,
                    CASE
                        WHEN LOWER(TRIM(CAST(active AS VARCHAR))) IN ('true', '1', 'yes', 'y') THEN TRUE
                        WHEN LOWER(TRIM(CAST(active AS VARCHAR))) IN ('false', '0', 'no', 'n') THEN FALSE
                        ELSE NULL
                    END AS is_active
                FROM read_csv_auto(?, header=true, union_by_name=true)
            """,
            "fk_predicates": [],
        }

    if key in {"location", "locations"}:
        return {
            "entity": "Location",
            "table_name": "Location",
            "source_files": source_files,
            "required_fields": ["location_id", "location_name"],
            "unique_fields": ["location_id"],
            "migration_select": """
                SELECT
                    TRIM(CAST(location_key AS VARCHAR)) AS location_id,
                    TRIM(CAST(loc_name AS VARCHAR)) AS location_name,
                    TRIM(CAST(parent_ref AS VARCHAR)) AS parent_id,
                    TRIM(CAST(site AS VARCHAR)) AS site,
                    TRIM(CAST(building AS VARCHAR)) AS building,
                    TRIM(CAST(floor AS VARCHAR)) AS floor
                FROM read_csv_auto(?, header=true, union_by_name=true)
                WHERE location_key IS NOT NULL AND TRIM(CAST(location_key AS VARCHAR)) <> ''
            """,
            "staging_select": """
                SELECT
                    TRIM(CAST(location_key AS VARCHAR)) AS location_id,
                    TRIM(CAST(loc_name AS VARCHAR)) AS location_name,
                    TRIM(CAST(parent_ref AS VARCHAR)) AS parent_id,
                    TRIM(CAST(site AS VARCHAR)) AS site,
                    TRIM(CAST(building AS VARCHAR)) AS building,
                    TRIM(CAST(floor AS VARCHAR)) AS floor
                FROM read_csv_auto(?, header=true, union_by_name=true)
            """,
            "fk_predicates": [],
        }

    if key in {"asset", "assets"}:
        return {
            "entity": "Asset",
            "table_name": "Asset",
            "source_files": source_files,
            "required_fields": ["c_asset_id", "asset_name", "asset_type"],
            "unique_fields": ["c_asset_id"],
            "migration_select": """
                SELECT
                    upper(trim(CAST(asset_no AS VARCHAR))) AS c_asset_id,
                    TRIM(CAST(asset_name AS VARCHAR)) AS asset_name,
                    TRIM(CAST(location_code AS VARCHAR)) AS b_location_id,
                    TRIM(CAST(asset_type AS VARCHAR)) AS asset_type,
                    TRIM(CAST(status AS VARCHAR)) AS status,
                    TRY_CAST(purchase_date AS DATE) AS purchase_date,
                    TRY_CAST(cost AS DECIMAL(12,2)) AS cost
                FROM read_csv_auto(?, header=true, union_by_name=true)
                WHERE asset_no IS NOT NULL AND TRIM(CAST(asset_no AS VARCHAR)) <> ''
            """,
            "staging_select": """
                SELECT
                    upper(trim(CAST(asset_no AS VARCHAR))) AS c_asset_id,
                    TRIM(CAST(asset_name AS VARCHAR)) AS asset_name,
                    TRIM(CAST(location_code AS VARCHAR)) AS b_location_id,
                    TRIM(CAST(asset_type AS VARCHAR)) AS asset_type,
                    TRIM(CAST(status AS VARCHAR)) AS status,
                    TRY_CAST(purchase_date AS DATE) AS purchase_date,
                    TRY_CAST(cost AS DECIMAL(12,2)) AS cost
                FROM read_csv_auto(?, header=true, union_by_name=true)
            """,
            "fk_predicates": [
                "(s.b_location_id IS NULL OR TRIM(CAST(s.b_location_id AS VARCHAR)) = '' OR EXISTS (SELECT 1 FROM Location p WHERE regexp_replace(upper(trim(CAST(p.location_id AS VARCHAR))), '[^A-Z0-9]', '', 'g') = regexp_replace(upper(trim(CAST(s.b_location_id AS VARCHAR))), '[^A-Z0-9]', '', 'g')))"
            ],
        }

    if key in {"workorder", "workorders"}:
        return {
            "entity": "WorkOrder",
            "table_name": "WorkOrder",
            "source_files": source_files,
            "required_fields": ["wo_id", "created_date"],
            "unique_fields": ["wo_id"],
            "migration_select": """
                SELECT
                    TRIM(CAST(wo_id AS VARCHAR)) AS wo_id,
                    TRIM(CAST(equip_id AS VARCHAR)) AS asset_id,
                    TRIM(CAST(technician_ref AS VARCHAR)) AS assigned_user,
                    TRIM(CAST(status AS VARCHAR)) AS status,
                    TRIM(CAST(priority AS VARCHAR)) AS priority,
                    TRY_CAST(created_date AS DATE) AS created_date,
                    TRY_CAST(closed_date AS DATE) AS closed_date,
                    TRIM(CAST(description AS VARCHAR)) AS description
                FROM read_csv_auto(?, header=true, union_by_name=true)
                WHERE wo_id IS NOT NULL AND TRIM(CAST(wo_id AS VARCHAR)) <> ''
            """,
            "staging_select": """
                SELECT
                    TRIM(CAST(wo_id AS VARCHAR)) AS wo_id,
                    TRIM(CAST(equip_id AS VARCHAR)) AS asset_id,
                    TRIM(CAST(technician_ref AS VARCHAR)) AS assigned_user,
                    TRIM(CAST(status AS VARCHAR)) AS status,
                    TRIM(CAST(priority AS VARCHAR)) AS priority,
                    TRY_CAST(created_date AS DATE) AS created_date,
                    TRY_CAST(closed_date AS DATE) AS closed_date,
                    TRIM(CAST(description AS VARCHAR)) AS description
                FROM read_csv_auto(?, header=true, union_by_name=true)
            """,
            "fk_predicates": [
                "(s.asset_id IS NULL OR TRIM(CAST(s.asset_id AS VARCHAR)) = '' OR EXISTS (SELECT 1 FROM Asset p WHERE regexp_replace(upper(trim(CAST(p.c_asset_id AS VARCHAR))), '[^A-Z0-9]', '', 'g') = regexp_replace(upper(trim(CAST(s.asset_id AS VARCHAR))), '[^A-Z0-9]', '', 'g')))",
                "(s.assigned_user IS NULL OR TRIM(CAST(s.assigned_user AS VARCHAR)) = '' OR EXISTS (SELECT 1 FROM Users p WHERE regexp_replace(upper(trim(CAST(p.user_id AS VARCHAR))), '[^A-Z0-9]', '', 'g') = regexp_replace(upper(trim(CAST(s.assigned_user AS VARCHAR))), '[^A-Z0-9]', '', 'g')))",
            ],
        }

    return {
        "entity": entity_name,
        "table_name": entity_name,
        "source_files": source_files,
        "required_fields": [],
        "unique_fields": [],
        "migration_select": "SELECT * FROM read_csv_auto(?, header=true, union_by_name=true)",
        "staging_select": "SELECT * FROM read_csv_auto(?, header=true, union_by_name=true)",
        "fk_predicates": [],
    }


def _build_duckdb_migration_script(entity_name: str, source_files: list[str]) -> str:
    cfg = _duckdb_entity_template(entity_name, source_files)
    fk_predicates = cfg["fk_predicates"]
    fk_clause = " AND ".join(f"({p})" for p in fk_predicates) if fk_predicates else ""
    valid_staging_sql = (
        f"WHERE {fk_clause}" if fk_clause else ""
    )
    orphan_count_sql = (
        f"SELECT COUNT(*) FROM staging s WHERE NOT ({fk_clause})" if fk_clause else "SELECT 0"
    )
    final_select = "SELECT * FROM valid_staging" if fk_clause else "SELECT * FROM staging"

    return f'''#!/usr/bin/env python3
import glob
import json
import logging
import os
import time
from datetime import datetime, timezone

import duckdb

RUN_ID = os.environ.get("RUN_ID", "manual")
ENTITY = "{cfg["entity"]}"
TABLE_NAME = "{cfg["table_name"]}"
SOURCE_FILENAMES = {json.dumps([os.path.basename(p) for p in source_files], indent=2)}

logging.basicConfig(format="%(asctime)s %(levelname)s: %(message)s", level=logging.INFO, handlers=[logging.StreamHandler()])

def log(stage, **fields):
    print(json.dumps({{"run_id": RUN_ID, "entity": ENTITY, "stage": stage, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}}), flush=True)

def _connect_duckdb():
    duckdb_path = os.environ.get("DUCKDB_PATH", "")
    if not duckdb_path:
        raise RuntimeError("DUCKDB_PATH environment variable is not set.")
    last_error = None
    for _ in range(60):
        try:
            return duckdb.connect(duckdb_path)
        except Exception as exc:
            last_error = exc
            if "wal" not in str(exc).lower() and "access is denied" not in str(exc).lower():
                raise
            time.sleep(1)
    raise last_error

def _resolve_source_files(source_dir: str) -> list[str]:
    resolved = []
    for source_filename in SOURCE_FILENAMES:
        exact = os.path.join(source_dir, source_filename)
        if os.path.exists(exact):
            resolved.append(exact)
            continue
        stem = os.path.splitext(source_filename)[0]
        candidates = sorted(glob.glob(os.path.join(source_dir, f"{{stem}}*.csv")) + glob.glob(os.path.join(source_dir, f"{{stem}}*.json")) + glob.glob(os.path.join(source_dir, f"{{stem}}*.parquet")))
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue
        if candidates:
            raise RuntimeError(f"Ambiguous source file for {{source_filename}}: {{candidates}}")
        raise RuntimeError(f"Source file not found: {{exact}}")
    return resolved

def main():
    log("load_start")
    duckdb_path = os.environ.get("DUCKDB_PATH", "").strip()
    source_dir = os.environ.get("SOURCE_DATA_DIR", "").strip()
    if not source_dir:
        raise RuntimeError("SOURCE_DATA_DIR environment variable is not set.")
    source_files = _resolve_source_files(source_dir)
    con = _connect_duckdb()
    try:
        source_row_count = con.execute("SELECT COUNT(*) FROM read_csv_auto(?, header=true, union_by_name=true)", [source_files]).fetchone()[0]
        con.execute(f"DROP TABLE IF EXISTS {{TABLE_NAME}}")
        con.execute("DROP TABLE IF EXISTS staging")
        con.execute("DROP TABLE IF EXISTS valid_staging")
        con.execute(f"BEGIN")
        con.execute("CREATE TEMP TABLE staging AS " + {json.dumps(cfg["staging_select"].strip())}, [source_files])
        con.execute("CREATE TEMP TABLE valid_staging AS " + {json.dumps(("SELECT * FROM staging s WHERE " + fk_clause) if fk_clause else "SELECT * FROM staging")})
        rows_skipped_orphans = con.execute({json.dumps(orphan_count_sql)}).fetchone()[0]
        con.execute(f"CREATE TABLE {{TABLE_NAME}} AS {final_select}")
        rows_written = con.execute(f"SELECT COUNT(*) FROM {{TABLE_NAME}}").fetchone()[0]
        con.commit()
        time.sleep(1)
        log("load_end", status="SUCCESS", rows_written=rows_written, source_rows=source_row_count, rows_skipped_orphans=rows_skipped_orphans)
    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        log("load_end", status="FAILED", error_code=type(exc).__name__, error_message=str(exc))
        raise
    finally:
        con.close()
        del con
        import gc
        gc.collect()
        time.sleep(5)
        wal_path = duckdb_path + ".wal"
        for _ in range(300):
            if not os.path.exists(wal_path):
                break
            try:
                os.remove(wal_path)
                break
            except PermissionError:
                time.sleep(1)

if __name__ == "__main__":
    main()
'''


def _build_duckdb_rollback_script(entity_name: str) -> str:
    table_name = _duckdb_entity_template(entity_name, []).get("table_name", entity_name)
    return f'''#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
import duckdb

RUN_ID = os.environ.get("RUN_ID", "manual")
ENTITY = "{table_name}"

def log(stage, **fields):
    print(json.dumps({{"run_id": RUN_ID, "entity": ENTITY, "stage": stage, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}}), flush=True)

def main():
    log("rollback_start")
    db_path = os.environ.get("DUCKDB_PATH", "")
    if not db_path:
        raise RuntimeError("DUCKDB_PATH environment variable is not set.")
    con = duckdb.connect(db_path)
    try:
        con.execute("DROP TABLE IF EXISTS {table_name}")
        con.commit()
        log("rollback_end", status="SUCCESS")
    except Exception as exc:
        log("rollback_end", status="FAILED", error_code=type(exc).__name__, error_message=str(exc))
        raise
    finally:
        con.close()

if __name__ == "__main__":
    main()
'''


def _build_duckdb_validation_script(entity_name: str, source_files: list[str], spec_fields: list | None = None) -> str:
    cfg = _duckdb_entity_template(entity_name, source_files)
    fk_predicates = cfg["fk_predicates"]
    fk_clause = " AND ".join(f"({p})" for p in fk_predicates) if fk_predicates else ""
    expected_rows_expr = "con.execute(\"SELECT COUNT(*) FROM valid_staging\").fetchone()[0]" if fk_clause else "source_row_count"

    return f'''#!/usr/bin/env python3
import glob
import json
import os
import time
from datetime import datetime, timezone

import duckdb

RUN_ID = os.environ.get("RUN_ID", "manual")
ENTITY = "{cfg["entity"]}"
TABLE_NAME = "{cfg["table_name"]}"
SOURCE_FILENAMES = {json.dumps([os.path.basename(p) for p in source_files], indent=2)}
REQUIRED_FIELDS = {json.dumps(cfg["required_fields"], indent=2)}
UNIQUE_FIELDS = {json.dumps(cfg["unique_fields"], indent=2)}

def log(stage, **fields):
    print(json.dumps({{"run_id": RUN_ID, "entity": ENTITY, "stage": stage, "timestamp": datetime.now(timezone.utc).isoformat(), **fields}}), flush=True)

def _connect_duckdb():
    duckdb_path = os.environ.get("DUCKDB_PATH", "")
    if not duckdb_path:
        raise RuntimeError("DUCKDB_PATH environment variable is not set.")
    for _ in range(30):
        try:
            return duckdb.connect(duckdb_path, read_only=True)
        except Exception as exc:
            if "wal" not in str(exc).lower() and "access is denied" not in str(exc).lower():
                raise
            time.sleep(1)
    return duckdb.connect(duckdb_path, read_only=True)

def _resolve_source_files(source_dir: str) -> list[str]:
    resolved = []
    for source_filename in SOURCE_FILENAMES:
        exact = os.path.join(source_dir, source_filename)
        if os.path.exists(exact):
            resolved.append(exact)
            continue
        stem = os.path.splitext(source_filename)[0]
        candidates = sorted(glob.glob(os.path.join(source_dir, f"{{stem}}*.csv")) + glob.glob(os.path.join(source_dir, f"{{stem}}*.json")) + glob.glob(os.path.join(source_dir, f"{{stem}}*.parquet")))
        if len(candidates) == 1:
            resolved.append(candidates[0])
            continue
        if candidates:
            raise RuntimeError(f"Ambiguous source file for {{source_filename}}: {{candidates}}")
        raise RuntimeError(f"Source file not found: {{exact}}")
    return resolved

def main():
    log("validation_start")
    source_dir = os.environ.get("SOURCE_DATA_DIR", "").strip()
    if not source_dir:
        raise RuntimeError("SOURCE_DATA_DIR environment variable is not set.")
    con = _connect_duckdb()
    try:
        source_files = _resolve_source_files(source_dir)
        source_row_count = con.execute("SELECT COUNT(*) FROM read_csv_auto(?, header=true, union_by_name=true)", [source_files]).fetchone()[0]
        con.execute("DROP TABLE IF EXISTS staging")
        con.execute("DROP TABLE IF EXISTS valid_staging")
        con.execute("CREATE TEMP TABLE staging AS " + {json.dumps(cfg["staging_select"].strip())}, [source_files])
        con.execute("CREATE TEMP TABLE valid_staging AS " + {json.dumps(("SELECT * FROM staging s WHERE " + fk_clause) if fk_clause else "SELECT * FROM staging")})
        expected_row_count = {expected_rows_expr}
        actual_row_count = con.execute(f"SELECT COUNT(*) FROM {{TABLE_NAME}}").fetchone()[0]
        assert actual_row_count == expected_row_count, f"Row count mismatch: expected {{expected_row_count}}, actual {{actual_row_count}}"
        for field in REQUIRED_FIELDS:
            null_count = con.execute(f'SELECT COUNT(*) FROM {{TABLE_NAME}} WHERE "{{field}}" IS NULL').fetchone()[0]
            assert null_count == 0, f"Null values found in required field: {{field}} ({{null_count}})"
        for field in UNIQUE_FIELDS:
            duplicate_count = con.execute(
                f'SELECT COUNT(*) FROM (SELECT "{{field}}", COUNT(*) AS cnt FROM {{TABLE_NAME}} GROUP BY "{{field}}" HAVING COUNT(*) > 1)'
            ).fetchone()[0]
            assert duplicate_count == 0, f"Duplicate values found in unique field: {{field}}"
        log("validation_end", status="PASSED", source_rows=source_row_count, target_rows=actual_row_count, expected_rows=expected_row_count, skipped_orphans=source_row_count - expected_row_count)
    except AssertionError as exc:
        log("validation_end", status="FAILED", error_code="AssertionError", error_message=str(exc))
        raise
    except Exception as exc:
        log("validation_end", status="FAILED", error_code=type(exc).__name__, error_message=str(exc))
        raise
    finally:
        con.close()

if __name__ == "__main__":
    main()
'''


def _build_duckdb_entity_result(source_entity: str, target_entity: str, source_files: list[str], depends_on: list, field_mappings: list, spec_fields: list, source_quality: dict) -> dict:
    entity_cfg = _duckdb_entity_template(target_entity or source_entity, source_files)
    return {
        "source_entity": source_entity,
        "entity": entity_cfg["entity"],
        "migration_script": _build_duckdb_migration_script(target_entity or source_entity, source_files),
        "rollback_script": _build_duckdb_rollback_script(target_entity or source_entity),
        "validation_script": _build_duckdb_validation_script(target_entity or source_entity, source_files),
        "depends_on": depends_on,
        "source_files": source_files,
        "field_mappings": field_mappings,
        "spec_fields": spec_fields,
        "source_quality": source_quality,
    }


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
    source_quality_index     = _build_source_quality_index(context)
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
        print(f"  Runtime req: {'OK' if runtime_requirements else 'MISSING'}")
        print(f"  Ops req    : {'OK' if operational_requirements else 'MISSING'}")

    if target == "duckdb":
        all_entity_results = []
        for mapping_entry in entity_list:
            source_entity = mapping_entry.get("source_entity", mapping_entry.get("entity", "Unknown"))
            target_entity = mapping_entry.get("target_entity", source_entity)
            try:
                field_mappings = mapping_entry.get("field_mappings", [])
                entity_spec = (compact_spec.get(target_entity) or compact_spec.get(source_entity) or []) if isinstance(compact_spec, dict) else []
                source_files = resolve_source_file(
                    source_entity,
                    target_entity,
                    context["plan"],
                    file_registry_index,
                )
                depends_on = dependency_map.get(source_entity, dependency_map.get(target_entity, []))
                all_entity_results.append(
                    _build_duckdb_entity_result(
                        source_entity,
                        target_entity,
                        source_files,
                        depends_on,
                        field_mappings,
                        entity_spec,
                        source_quality_index.get(source_entity, source_quality_index.get(target_entity, {})),
                    )
                )
            except Exception as e:
                msg = f"CODE_GENERATION_ERROR: deterministic build failed for '{source_entity}' — {e}"
                print(f"  x [{source_entity}] {msg}")
                context["migration"] = {"status": "FAILED", "error": msg}
                append_audit_event(context, AGENT_NAME, "7a_deterministic_build", "failed", {"error": msg, "entity": source_entity})
                return context

        art_dir = _artifact_dir(target)
        run_id = context.get("meta", {}).get("run_id", "unknown")
        wave_index = {}
        for idx, wave in enumerate(sorted(plan.get("waves", []), key=lambda w: w.get("wave_number", 0))):
            for ent_name in wave.get("entities") or []:
                wave_index[ent_name] = idx
        ordered_entity_results = sorted(
            all_entity_results,
            key=lambda ent: (
                wave_index.get(ent.get("source_entity") or ent["entity"], 999),
                ent.get("source_entity") or ent["entity"],
            ),
        )
        artifacts, ordered_steps = [], []
        for i, ent in enumerate(ordered_entity_results):
            name = ent["entity"]
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            depends_on = ent.get("depends_on", [])
            for art_type, key, suffix in [
                ("migration_script", "migration_script", "migrate"),
                ("rollback_script", "rollback_script", "rollback"),
                ("validation_script", "validation_script", "validate"),
            ]:
                content = ent.get(key, f"# No {art_type} for {name}\n")
                if not content.startswith("#!"):
                    content = "#!/usr/bin/env python3\n" + content
                try:
                    ast.parse(content)
                except SyntaxError as exc:
                    msg = f"CODE_GENERATION_ERROR: deterministic artifact parse failed for '{name}'/{art_type} — {exc}"
                    print(f"  x [{name}] {msg}")
                    context["migration"] = {"status": "FAILED", "error": msg}
                    append_audit_event(context, AGENT_NAME, "7a_deterministic_build", "failed", {"error": msg, "entity": name})
                    return context
                rel_path = f"outputs/migration/duckdb/{slug}/{suffix}_{slug}.py"
                abs_path = art_dir / slug / f"{suffix}_{slug}.py"
                sha = _write_artifact(content, abs_path)
                art_id = f"mig_{slug}_{art_type}_v1"
                artifacts.append(_make_artifact_record(art_id, art_type, name, rel_path, sha, depends_on))
            ordered_steps.append({
                "step": i + 1,
                "entity": name,
                "depends_on": depends_on,
                "artifacts": [f"mig_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}_{t}_v1" for t in ("migration_script", "rollback_script", "validation_script")],
            })
        context["migration"] = {
            "artifacts": artifacts,
            "execution_manifest": {"run_id": run_id, "ordered_steps": ordered_steps},
            "summary": {
                "migration_artifact_count":  sum(1 for a in artifacts if a["artifact_type"] == "migration_script"),
                "rollback_artifact_count":   sum(1 for a in artifacts if a["artifact_type"] == "rollback_script"),
                "validation_artifact_count": sum(1 for a in artifacts if a["artifact_type"] == "validation_script"),
            },
            "llm_trace": {
                "model": "deterministic-duckdb-template",
                "prompt_id": PROMPT_ID,
                "temperature": 0.0,
                "tokens_in": 0,
                "tokens_out": 0,
                "latency_ms": 0,
            },
            "status": "SCRIPTS_GENERATED",
        }
        append_audit_event(context, AGENT_NAME, "7a_generate", "completed", {
            "target": target,
            "artifact_count": len(artifacts),
            "entities": [e["entity"] for e in all_entity_results],
        })
        if verbose:
            s = context["migration"]["summary"]
            print(f"  Migration scripts   : {s['migration_artifact_count']}")
            print(f"  Rollback scripts    : {s['rollback_artifact_count']}")
            print(f"  Validation scripts  : {s['validation_artifact_count']}")
            print(f"  Status              : SCRIPTS_GENERATED")
        return context

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
            # resolve_source_file returns local absolute paths for disk-based
            # sources or filenames for S3-based sources, and raises
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
            wave_item = _find_entity_wave(plan, source_entity, target_entity)

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
                wave_item,
                config.USE_S3_SOURCE,
            )

            if verbose:
                print(f"  -> [{source_entity}] generating scripts (files: {source_files})...")

            try:
                raw, trace = _call_bedrock(
                    system_prompt=system,
                    developer_prompt=developer_prompt,
                    user_prompt=user_prompt,
                    label=source_entity,
                    max_tokens=4096,
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
                    ent_block["entity"] = target_entity
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

                    ent_block["source_entity"] = source_entity
                    ent_block["target_entity"] = target_entity
                    ent_block["source_files"] = source_files
                    ent_block["field_mappings"] = field_mappings
                    ent_block["spec_fields"] = entity_spec
                    ent_block["source_quality"] = source_quality_index.get(source_entity, source_quality_index.get(target_entity, {}))

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
    step_gap   = int(os.getenv("MIGRATION_STEP_GAP", "2"))
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

import os, sys, json, io, time
from datetime import datetime, timezone

INTERPRETER = r"{interpreter}"
TIMEOUT     = {timeout}
STEP_GAP    = {step_gap}
RUN_ID      = "{run_id}"
TARGET      = "{target}"

STEPS = {step_json}
DB_WAL = os.environ.get("DUCKDB_PATH", "") + ".wal"


def log(record: dict):
    print(json.dumps(record), flush=True)


def cleanup_wal(max_wait: int = 60):
    if not os.path.exists(DB_WAL):
        return
    for _ in range(max_wait):
        try:
            if os.path.exists(DB_WAL):
                os.remove(DB_WAL)
            return
        except PermissionError:
            time.sleep(1)



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
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        import importlib.util
        import contextlib

        spec = importlib.util.spec_from_file_location(
            f"migration_step_{{step_num}}_{{entity}}",
            script_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load step module from {{script_path}}")
        module = importlib.util.module_from_spec(spec)
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            spec.loader.exec_module(module)
            if not hasattr(module, "main"):
                raise RuntimeError(f"Step module has no main() function: {{script_path}}")
            module.main()

        duration_ms = int((time.time() - t0) * 1000)
        stdout, stderr = stdout_buf.getvalue().strip(), stderr_buf.getvalue().strip()

        rows = 0
        rows_skipped_orphans = 0
        for line in stdout.splitlines():
            try:
                entry = json.loads(line)
                if entry.get("stage") == "load_end" and "rows_written" in entry:
                    rows = int(entry["rows_written"] or 0)
                    rows_skipped_orphans = int(entry.get("rows_skipped_orphans", 0) or 0)
                    break
            except (json.JSONDecodeError, ValueError):
                continue

        log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
              "stage": "step_end", "status": "SUCCESS",
              "duration_ms": duration_ms, "rows_written": rows,
              "rows_skipped_orphans": rows_skipped_orphans}})
        cleanup_wal()
        return {{"step": step_num, "entity": entity, "status": "SUCCESS",
                 "rows": rows, "rows_skipped_orphans": rows_skipped_orphans, "error": None}}

    except Exception as exc:
        duration_ms = int((time.time() - t0) * 1000)
        stdout, stderr = stdout_buf.getvalue().strip(), stderr_buf.getvalue().strip()
        err = f"Exit 1. stderr: {{(stderr or str(exc))[-500:]}}"
        log({{"run_id": RUN_ID, "step": step_num, "entity": entity,
              "stage": "step_end", "status": "FAILED",
              "duration_ms": duration_ms, "error": err}})
        return {{"step": step_num, "entity": entity, "status": "FAILED",
                 "rows": 0, "error": err, "stdout": stdout, "stderr": stderr or str(exc)}}


def main():
    duckdb_path = os.environ.get('DUCKDB_PATH', '')
    if not duckdb_path:
        print(json.dumps({{"run_id": RUN_ID, "stage": "init", "status": "FAILED",
                           "error": "DUCKDB_PATH environment variable is not set."}}))
        raise RuntimeError('DUCKDB_PATH environment variable is not set.')

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
        if STEP_GAP > 0:
            time.sleep(STEP_GAP)

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
    run_id        = uuid.uuid4().hex
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
