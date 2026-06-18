"""
mapping_agent.py
-----------------
Agent 3 — AI Mapping Agent

Two modes:
  A) Autonomous  : Groq LLM generates source→target field mappings automatically
                   using the entity_catalog + target_schema.
  B) Interactive : the Conversational Assistant calls this agent mid-chat when
                   the user manually confirms, overrides, or adds a mapping.
                   Every manual change is written to outputs/user_mappings.json
                   and merged into the final mapping document so downstream
                   agents (Spec, Readiness, Planning) see the corrected version.

Output written to:  outputs/mapping_document.json
User overrides at:  outputs/user_mappings.json
"""

import os
import json
import time
import re
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from tools.output_tools import save_output, load_output


import config

MAX_RETRIES  = 2
RETRY_DELAY  = 3



# ── helpers ───────────────────────────────────────────────────────────────────

def _call_bedrock(prompt: str, system: str, label: str = "", max_tokens: int = 4096, temperature: float = 0.0) -> str:
    last_error = None
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client = config.get_bedrock_client()
            
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


# ── user mapping store ────────────────────────────────────────────────────────

def _load_user_mappings() -> list:
    """Load manually confirmed/overridden mappings from disk."""
    path = os.path.join(config.OUTPUT_DIR, "user_mappings.json")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save_user_mappings(mappings: list) -> None:
    """Persist user mappings immediately after every change."""
    path = os.path.join(config.OUTPUT_DIR, "user_mappings.json")
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(mappings, f, indent=2)


def add_user_mapping(source_entity: str, source_field: str,
                     target_entity: str, target_field: str,
                     transformation: str = "direct",
                     note: str = "") -> dict:
    """
    Called by the Conversational Assistant when the user confirms or adds
    a mapping manually during chat.

    Saves immediately to disk so the next agent run picks it up.
    Returns the saved entry.
    """
    entry = {
        "source_entity":    source_entity,
        "source_field":     source_field,
        "target_entity":    target_entity,
        "target_field":     target_field,
        "transformation":   transformation,
        "confidence_score": 1.0,        # user-confirmed = 100%
        "reasoning":        f"User-confirmed mapping. {note}".strip(),
        "origin":           "user"
    }
    existing = _load_user_mappings()
    # Replace if same source_entity + source_field already exists
    existing = [m for m in existing
                if not (m["source_entity"] == source_entity
                        and m["source_field"] == source_field)]
    existing.append(entry)
    _save_user_mappings(existing)
    return entry


def remove_user_mapping(source_entity: str, source_field: str) -> bool:
    """Remove a user-confirmed mapping. Returns True if something was removed."""
    existing = _load_user_mappings()
    filtered = [m for m in existing
                if not (m["source_entity"] == source_entity
                        and m["source_field"] == source_field)]
    if len(filtered) == len(existing):
        return False
    _save_user_mappings(filtered)
    return True


def get_user_mappings() -> list:
    return _load_user_mappings()


# ── LLM mapping prompt ────────────────────────────────────────────────────────

MAPPING_SYSTEM = """
You are an expert data migration mapping analyst.

You will receive:
  1. An entity catalog (source schema) — entities with their fields, primary keys, and FK relationships.
  2. A target schema — the desired destination schema with required/optional fields and data types.

Your job: generate field-level mappings from every source entity to the best-matching target entity.

Return ONLY valid JSON. No markdown. No text outside the JSON.

Output structure:
{
  "mappings": [
    {
      "source_entity": "Assets",
      "target_entity": "Asset",
      "field_mappings": [
        {
          "source_field": "asset_no",
          "target_field": "asset_id",
          "confidence_score": 0.95,
          "transformation_logic": "uppercase(trim(asset_no))",
          "reasoning": "Direct semantic match. asset_no is the primary key of source Assets, maps to asset_id in target."
        }
      ],
      "unmapped_source_fields": ["purchase_date"],
      "unmapped_required_target_fields": []
    }
  ]
}

Rules:
- confidence_score: 0.0–1.0. Use 0.9+ for exact/near-exact name matches, 0.7–0.89 for semantic matches, below 0.7 for guesses.
- transformation_logic: suggest realistic SQL/Python transforms (e.g. uppercase(), trim(), lookup(), cast(), concat()).
  Use "direct" if no transformation is needed.
- unmapped_source_fields: source fields that have no good target match.
- unmapped_required_target_fields: required target fields with no source mapping.
- Map EVERY source entity to the closest target entity, even if the names differ.
- If a source entity has no clear target, still output the mapping block with all fields as unmapped.
"""


# ── core agent run ────────────────────────────────────────────────────────────

def run_mapping_agent(context: dict, verbose: bool = True) -> dict:
    """
    Main entry point called from pipeline.py.

    1. Loads entity_catalog + target_schema.
    2. Calls Groq to auto-generate mappings.
    3. Merges any user-confirmed mappings on top (user always wins).
    4. Saves outputs/mapping_document.json.
    5. Updates context["mappings"].
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  AI MAPPING AGENT")
        print("=" * 60)

    entity_catalog = context.get("entity_catalog", {})
    if not entity_catalog:
        print("  x entity_catalog missing. Run Discovery Agent first.")
        return context

    # Load target schema
    schema_path = str(config.TARGET_SCHEMA_PATH)
    if not os.path.exists(schema_path):
        print(f"  x Target schema not found at {schema_path}")
        return context

    with open(schema_path) as f:
        target_schema = json.load(f)

    if verbose:
        entities = [e.get("entity_name") for e in entity_catalog.get("entities", [])]
        print(f"  Source entities  : {entities}")
        print(f"  Target entities  : {list(target_schema.keys())}")

    # Build compact source summary for prompt (no raw data, just schema)
    source_summary = []
    for entity in entity_catalog.get("entities", []):
        source_summary.append({
            "entity_name": entity.get("entity_name"),
            "primary_key": entity.get("primary_key"),
            "fields": [
                {
                    "name":      f.get("name"),
                    "dtype":     f.get("dtype"),
                    "role":      f.get("role"),
                    "null_pct":  f.get("null_pct", 0)
                }
                for f in entity.get("fields", [])
            ]
        })

    prompt = f"""
Map every source entity field to the best-matching target entity field.

SOURCE SCHEMA:
{json.dumps(source_summary, indent=2)}

TARGET SCHEMA:
{json.dumps(target_schema, indent=2)}
"""

    if verbose:
        print(f"  Calling {config.get_provider_name()} for auto-mappings...")

    try:
        raw     = _call_bedrock(prompt, MAPPING_SYSTEM, label="MappingAgent")
        result  = _parse_json(raw)
        ai_mappings = result.get("mappings", [])
    except Exception as e:
        print(f"  x {config.get_provider_name()} call failed: {e}")
        ai_mappings = []

    # ── merge user mappings (user overrides AI) ───────────────────────────────
    user_mappings = _load_user_mappings()
    if user_mappings:
        if verbose:
            print(f"  Merging {len(user_mappings)} user-confirmed mapping(s)...")
        ai_mappings = _apply_user_overrides(ai_mappings, user_mappings)
    ai_mappings = _repair_mapping_document(ai_mappings, target_schema)

    mapping_doc = {
        "mappings":          ai_mappings,
        "user_mapping_count": len(user_mappings),
        "ai_mapping_count":  sum(len(m.get("field_mappings", [])) for m in ai_mappings),
    }

    save_output(mapping_doc, "mapping_document.json")
    context["mappings"] = mapping_doc

    if verbose:
        _print_summary(ai_mappings, user_mappings)

    return context


def _apply_user_overrides(ai_mappings: list, user_mappings: list) -> list:
    """
    For each user mapping:
      - Find the matching source_entity block in ai_mappings.
      - Replace or add the field_mapping entry for that source_field.
    """
    # Index ai mappings by source_entity for fast lookup
    ai_index = {m["source_entity"]: m for m in ai_mappings}

    for um in user_mappings:
        src_entity  = um["source_entity"]
        src_field   = um["source_field"]

        if src_entity not in ai_index:
            # Entity block doesn't exist yet — create it
            ai_index[src_entity] = {
                "source_entity":                src_entity,
                "target_entity":                um["target_entity"],
                "field_mappings":               [],
                "unmapped_source_fields":       [],
                "unmapped_required_target_fields": []
            }

        block = ai_index[src_entity]

        # Remove existing mapping for this source_field (if any)
        block["field_mappings"] = [
            fm for fm in block["field_mappings"]
            if fm.get("source_field") != src_field
        ]
        # Remove from unmapped list if it was there
        block["unmapped_source_fields"] = [
            f for f in block.get("unmapped_source_fields", [])
            if f != src_field
        ]

        # Insert user mapping at top of field_mappings
        block["field_mappings"].insert(0, {
            "source_field":       src_field,
            "target_field":       um["target_field"],
            "confidence_score":   1.0,
            "transformation_logic": um.get("transformation", "direct"),
            "reasoning":          um.get("reasoning", "User-confirmed mapping."),
            "origin":             "user"
        })

    return list(ai_index.values())


def _print_summary(mappings: list, user_mappings: list):
    print("\n" + "=" * 60)
    print("  AI MAPPING COMPLETE")
    print("=" * 60)
    total_mapped   = sum(len(m.get("field_mappings", [])) for m in mappings)
    total_unmapped = sum(len(m.get("unmapped_source_fields", [])) for m in mappings)
    print(f"  Mapped fields    : {total_mapped}")
    print(f"  Unmapped fields  : {total_unmapped}")
    print(f"  User overrides   : {len(user_mappings)}")
    for m in mappings:
        src = m.get("source_entity")
        tgt = m.get("target_entity")
        n   = len(m.get("field_mappings", []))
        u   = len(m.get("unmapped_source_fields", []))
        print(f"  {src:20s} -> {tgt:20s}  | {n} mapped, {u} unmapped")
    print(f"\n  Saved to: outputs/mapping_document.json")
    print("=" * 60)


def _normalize_entity_name(name: str) -> str:
    raw = (name or "").strip()
    lowered = raw.lower()
    if lowered.endswith("ies"):
        return raw[:-3] + "y"
    if lowered.endswith("s") and len(raw) > 1:
        return raw[:-1]
    return raw


def _build_target_field_requirements(target_schema: dict) -> dict:
    requirements = {}
    for entity_name, fields in (target_schema or {}).items():
        if not isinstance(fields, dict):
            continue
        required_fields = {
            field_name
            for field_name, field_schema in fields.items()
            if isinstance(field_schema, dict) and field_schema.get("required", False)
        }
        requirements[entity_name] = required_fields
        requirements[_normalize_entity_name(entity_name)] = required_fields
    return requirements


def _repair_mapping_document(mappings: list, target_schema: dict) -> list:
    repaired = []
    target_requirements = _build_target_field_requirements(target_schema)

    for block in mappings or []:
        src_entity = block.get("source_entity", "")
        tgt_entity = block.get("target_entity", "")
        fields = list(block.get("field_mappings", []))
        unmapped_source = list(block.get("unmapped_source_fields", []))
        unmapped_required = list(block.get("unmapped_required_target_fields", []))

        if _normalize_entity_name(src_entity).lower() == "workorder":
            has_assigned_user = any((fm.get("target_field") or "").lower() == "assigned_user" for fm in fields)
            has_technician_ref = any((fm.get("source_field") or "").lower() == "technician_ref" for fm in fields)
            if not has_assigned_user and "technician_ref" in [f.lower() for f in unmapped_source]:
                fields.append({
                    "source_field": "technician_ref",
                    "target_field": "assigned_user",
                    "confidence_score": 0.9,
                    "transformation_logic": "direct",
                    "reasoning": "Auto-repaired semantic match: technician_ref is the work order assignee reference.",
                    "origin": "system_repair",
                })
                unmapped_source = [f for f in unmapped_source if f.lower() != "technician_ref"]

        required_targets = target_requirements.get(tgt_entity) or target_requirements.get(_normalize_entity_name(tgt_entity)) or set()
        unmapped_required = [f for f in unmapped_required if f in required_targets]

        repaired.append({
            **block,
            "field_mappings": fields,
            "unmapped_source_fields": unmapped_source,
            "unmapped_required_target_fields": unmapped_required,
        })

    return repaired
