"""
specification_agent.py
------------------------
Agent 4 — Specification Generation Agent.
Auto-generates migration data contracts and specifications by merging
mapping documents and profiling quality reports with target schemas.
"""

import os
import json
import time
import re
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from tools.output_tools import save_output, load_output

OUTPUT_DIR   = "outputs"
MAX_RETRIES  = 2
RETRY_DELAY  = 3

# ── bedrock call helper ────────────────────────────────────────────────────────

def _call_bedrock(prompt: str, system: str, label: str = "", max_tokens: int = 4096, temperature: float = 0.0) -> str:
    last_error = None
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client = boto3.client(
                service_name="bedrock-runtime",
                region_name=aws_region,
                aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            )
            
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "temperature": temperature
            }
            
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            
            body = json.loads(response["body"].read())
            return body["content"][0]["text"]
        except Exception as e:
            last_error = e
            wait = RETRY_DELAY
            m = re.search(r"retry in\s*([0-9]+(?:\.[0-9]+)?)s", str(e), re.IGNORECASE)
            if m:
                wait = max(RETRY_DELAY, int(float(m.group(1))))
            if attempt <= MAX_RETRIES:
                print(f"  ! [{label}] attempt {attempt} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
    raise last_error


def _parse_json(raw: str) -> dict:
    cleaned = (raw or "").strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
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


# ── prompts ───────────────────────────────────────────────────────────────────

SPEC_SYSTEM = """You are the OnboardIQ Specification Agent, a senior data architect and database engineer.

Your task is to generate a strict, production-ready "Migration Specification" (Data Contract) by merging field mappings and data profiling outcomes with target database schema constraints.

Input information provided:
1. TARGET SCHEMA: The fields, types, required flags, and descriptions expected by the target system.
2. FIELD MAPPINGS: Source-to-target field associations and their transformation logic.
3. DATA QUALITY REPORT: Null rates, uniqueness metrics, and detected issues (orphans, duplicates) for source columns.

For each mapped target entity, you must output a list of specification records for its fields in a JSON format matching the schema below.

JSON SCHEMA FORMAT:
{
  "entity_specification": {
    "<TargetEntityName>": [
      {
        "source_field": "<source field name>",
        "target_field": "<target field name>",
        "data_type": "<concrete SQL type, e.g., VARCHAR(50), INT, DATE, DECIMAL(12,2), BOOLEAN>",
        "nullable": true/false,
        "validation_rule": "<validation rule expression, regex constraint, e.g., REGEX('^[A-Z0-9_-]+$'), range, or reference constraint>",
        "transformation": "<applied transformation logic from mappings>",
        "business_constraint": "<PRIMARY KEY, FOREIGN KEY(ParentTable.parent_field), NOT NULL, UNIQUE, or empty string if none>"
      }
    ]
  }
}

STRICT SPECIFICATION GENERATION RULES:
1. 'source_field' and 'target_field': Use the exact names from the field mappings.
2. 'data_type':
   - Translate target schema types ('string', 'date', 'decimal', 'boolean') to concrete SQL database types.
   - For strings, inspect the sample values or domain context. If it's a code/ID, use 'VARCHAR(20)' or 'VARCHAR(50)'. If it's a description/name, use 'VARCHAR(255)' or 'VARCHAR(100)'.
   - For dates, use 'DATE' or 'TIMESTAMP'.
   - For decimals, use 'DECIMAL(10,2)' or 'DECIMAL(12,4)'.
   - For booleans, use 'BOOLEAN'.
3. 'nullable':
   - Must be false if the target schema specifies 'required: true', or if the field is the primary key (or part of it).
   - If the target schema specifies 'required: false' AND the quality report indicates zero nulls in the source, set 'nullable' to false to enforce quality preservation, unless there is a strong reason (like a sparse field).
   - Set to true if the field is optional and has null values.
4. 'validation_rule':
   - If the field is a Primary Key: use 'IS_UNIQUE' or 'NOT_NULL'.
   - If the field is a Foreign Key: use 'FOREIGN_KEY(ParentTargetTable.target_field)'. Refer to relationships in the catalog/schemas to identify parent tables.
   - If there is a regex/format pattern identified (e.g. LOCxx, SITExx): use 'REGEX(pattern)' style rules. E.g., 'REGEX(\\'^LOC\\\\d{2}$\\\')'.
   - If date: use 'IS_DATE'.
   - If numeric: write range checks like '>= 0' if applicable (e.g., cost).
5. 'business_constraint':
   - Must be 'PRIMARY KEY' for target identifiers.
   - Must be 'FOREIGN_KEY(ParentTargetTable.target_field)' for columns referencing parent keys.
   - Must be 'NOT NULL' if the column cannot be null.
   - Use 'UNIQUE' if the column values must be unique but it's not the primary key.
   - Default to empty string '' if no special constraints apply.
6. 'transformation': Copy the 'transformation_logic' from the mapping document.

Return ONLY valid JSON. Do not write any markdown wrappers (like ```json), introduction, or conversational filler outside the JSON structure.
"""

# ── core agent run ────────────────────────────────────────────────────────────

def run_specification_agent(context: dict, verbose: bool = True) -> dict:
    """
    Main entry point called from pipeline.py.
    
    1. Loads target schema from schemas/target_schema.json.
    2. Loads mappings from context or outputs/mapping_document.json.
    3. Loads quality report from context or outputs/quality_report.json.
    4. Caches and loads from file if cache is newer than inputs.
    5. Calls AWS Bedrock to build structured specifications.
    6. Saves JSON and Markdown specification documents.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  AI SPECIFICATION AGENT")
        print("=" * 60)

    # 1. Paths
    schema_path  = "schemas/target_schema.json"
    mapping_path = os.path.join(OUTPUT_DIR, "mapping_document.json")
    quality_path = os.path.join(OUTPUT_DIR, "quality_report.json")
    spec_path    = os.path.join(OUTPUT_DIR, "migration_spec.json")
    md_spec_path = os.path.join(OUTPUT_DIR, "migration_spec.md")

    # 2. Check Cache Validity
    if os.path.exists(spec_path) and os.path.exists(md_spec_path):
        spec_mtime = os.path.getmtime(spec_path)
        mapping_mtime = os.path.getmtime(mapping_path) if os.path.exists(mapping_path) else 0
        quality_mtime = os.path.getmtime(quality_path) if os.path.exists(quality_path) else 0
        
        if spec_mtime >= mapping_mtime and spec_mtime >= quality_mtime:
            if verbose:
                print("  -> Found cached migration specification. Skipping API call.")
            with open(spec_path, "r", encoding="utf-8") as f:
                cached_spec = json.load(f)
            context["specification"] = cached_spec
            return context

    # 3. Load Inputs
    if not os.path.exists(schema_path):
        print(f"  x Target schema not found at {schema_path}")
        return context

    with open(schema_path, "r", encoding="utf-8") as f:
        target_schema = json.load(f)

    # Get mappings
    mappings_data = context.get("mappings")
    if not mappings_data:
        if os.path.exists(mapping_path):
            with open(mapping_path, "r", encoding="utf-8") as f:
                mappings_data = json.load(f)
        else:
            print("  x mappings missing. Run AI Mapping Agent first.")
            return context

    # Get quality report
    quality_data = context.get("quality_report")
    if not quality_data:
        if os.path.exists(quality_path):
            with open(quality_path, "r", encoding="utf-8") as f:
                quality_data = json.load(f)
        else:
            print("  x quality_report missing. Run Data Profiling Agent first.")
            return context

    # Build prompt
    prompt = f"""
Please generate the migration specifications for the following mapping and quality contexts.

TARGET SCHEMA:
{json.dumps(target_schema, indent=2)}

FIELD MAPPINGS:
{json.dumps(mappings_data.get("mappings", []), indent=2)}

DATA QUALITY REPORT:
{json.dumps(quality_data.get("entity_quality", {}), indent=2)}
"""

    if verbose:
        print("  Calling Bedrock to generate migration specifications...")

    try:
        raw = _call_bedrock(prompt, SPEC_SYSTEM, label="SpecificationAgent")
        result = _parse_json(raw)
        entity_spec = result.get("entity_specification", {})
    except Exception as e:
        print(f"  x Bedrock call failed: {e}")
        entity_spec = {}

    spec_output = {
        "entity_specification": entity_spec
    }

    # Save outputs
    save_output(spec_output, "migration_spec.json")
    context["specification"] = spec_output

    # Generate Markdown Table
    _generate_markdown_spec(entity_spec, md_spec_path)

    if verbose:
        _print_summary(entity_spec)

    return context


def _generate_markdown_spec(entity_spec: dict, output_path: str):
    """Generates a clean human-readable Markdown file from the specifications."""
    lines = ["# Migration Specifications and Data Contracts\n"]
    lines.append("This document outlines the source-to-target database mapping specifications, types, validation rules, and business constraints.\n")

    for target_entity, fields in entity_spec.items():
        lines.append(f"## Target Entity: {target_entity}\n")
        lines.append("| Source Field | Target Field | Data Type | Nullable | Validation Rule | Transformation | Business Constraint |")
        lines.append("|---|---|---|---|---|---|---|")
        for f in fields:
            src = f.get("source_field", "")
            tgt = f.get("target_field", "")
            dtype = f.get("data_type", "")
            null = str(f.get("nullable", ""))
            v_rule = f.get("validation_rule", "")
            trans = f.get("transformation", "")
            const = f.get("business_constraint", "")
            
            lines.append(f"| {src} | {tgt} | {dtype} | {null} | `{v_rule}` | `{trans}` | {const} |")
        lines.append("\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _print_summary(entity_spec: dict):
    print("\n" + "=" * 60)
    print("  SPECIFICATION GENERATION COMPLETE")
    print("=" * 60)
    for entity, fields in entity_spec.items():
        print(f"  {entity:20s} | {len(fields)} fields specified")
    print(f"\n  Saved JSON to: outputs/migration_spec.json")
    print(f"  Saved MD   to: outputs/migration_spec.md")
    print("=" * 60)
