"""
discovery_agent.py
-------------------
Discovery Agent — Two-Phase Scalable approach.
With per-table checkpointing, resume-on-crash, and retry logic (max 2).

PHASE 1 — Per-table LLM calls (parallel)
  - Before calling Gemini, checks if outputs/phase1_<file>.json already exists
  - If yes  → loads from disk, skips API call  (resume on crash)
  - If no   → calls Gemini with retry (max 2 attempts)
  - After success → saves result to outputs/phase1_<file>.json immediately

PHASE 2 — Relationship resolution (single tiny LLM call)
  - Reads all phase1 profiles from memory (already loaded in Phase 1)
  - Sends only FK signatures — no raw data, prompt stays tiny at any scale
  - Retry logic (max 2 attempts)

PHASE 3 — Merge + Save final catalog
"""

import os
import sys
import json
import time
import re
import concurrent.futures
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


from agents.payload_builder import build_context_payload
from tools.output_tools import save_output, load_output


import config

MAX_RETRIES   = 2      # max retry attempts per Gemini call
RETRY_DELAY   = 3      # seconds to wait between retries
PARSE_RETRIES = 2      # extra retries when model output is invalid JSON


# -------------------------------------------------------
# HELPERS
# -------------------------------------------------------

def _checkpoint_path(file_name: str) -> str:
    """Returns the checkpoint file path for a given source file."""
    safe_name = file_name.replace("/", "_").replace("\\", "_")
    return os.path.join(config.OUTPUT_DIR, f"phase1_{safe_name}.json")



def _extract_retry_delay_seconds(error_text: str) -> int:
    """Extract retry delay from provider error text, fallback to RETRY_DELAY."""
    if not error_text:
        return RETRY_DELAY

    # Examples seen in provider messages:
    # "Please retry in 41.137485812s." or "Please try again in 4.5s" or "try again in 1m2.5s"
    patterns = [
        r"retry in\s*([0-9]+(?:\.[0-9]+)?)s",
        r"try again in\s*([0-9]+(?:\.[0-9]+)?)s",
        r"retryDelay'?:\s*'([0-9]+(?:\.[0-9]+)?)s'"
    ]

    for pat in patterns:
        m = re.search(pat, error_text, flags=re.IGNORECASE)
        if m:
            return max(RETRY_DELAY, int(float(m.group(1))))

    # Check for minutes + seconds pattern, e.g. 1m2.5s
    m_min_sec = re.search(r"try again in\s*(?:([0-9]+)m)?([0-9]+(?:\.[0-9]+)?)s", error_text, flags=re.IGNORECASE)
    if m_min_sec:
        mins = int(m_min_sec.group(1) or 0)
        secs = float(m_min_sec.group(2) or 0)
        total_secs = int(mins * 60 + secs)
        return max(RETRY_DELAY, total_secs)

    return RETRY_DELAY


def _call_bedrock_with_retry(prompt: str, system: str, label: str = "", max_tokens: int = 2048, temperature: float = 0.0) -> str:
    """
    Calls AWS Bedrock with up to MAX_RETRIES retries on failure.

    On each failure:
      - Prints the error and attempt number
      - Waits RETRY_DELAY seconds before retrying
      - Raises the last exception if all attempts fail
    """
    last_error = None
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

    for attempt in range(1, MAX_RETRIES + 2):   # +2 so range covers 1..MAX_RETRIES+1
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
            err_text = str(e)

            is_rate_limit = ("ThrottlingException" in err_text or 
                             "LimitExceeded" in err_text or 
                             "TooManyRequestsException" in err_text or
                             "rate_limit_exceeded" in err_text)
                             
            if is_rate_limit:
                wait_s = _extract_retry_delay_seconds(err_text)
                print(f"  ! [{label}] Rate limit hit. Retrying in {wait_s}s...")
            else:
                wait_s = RETRY_DELAY

            if attempt <= MAX_RETRIES:
                print(f"  ! [{label}] Attempt {attempt} failed: {e}. Retrying in {wait_s}s...")
                time.sleep(wait_s)
            else:
                print(f"  x [{label}] All {MAX_RETRIES + 1} attempts failed.")

    raise last_error


def _parse_json(raw: str) -> dict:
    """Best-effort JSON parsing from LLM output."""
    cleaned = (raw or "").strip()

    # Remove markdown fences when present.
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        if len(parts) >= 2:
            cleaned = parts[1]
        if cleaned.lstrip().startswith("json"):
            cleaned = cleaned.lstrip()[4:]

    cleaned = cleaned.strip()

    # Try direct parse first.
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Fallback: extract outermost JSON object/array from surrounding text.
    obj_start = cleaned.find("{")
    arr_start = cleaned.find("[")

    starts = [i for i in (obj_start, arr_start) if i != -1]
    if not starts:
        raise

    start = min(starts)
    open_ch = cleaned[start]
    close_ch = "}" if open_ch == "{" else "]"
    end = cleaned.rfind(close_ch)
    if end == -1 or end <= start:
        raise

    candidate = cleaned[start:end + 1]
    return json.loads(candidate)


# -------------------------------------------------------
# PHASE 1 — SYSTEM PROMPT
# -------------------------------------------------------

PHASE1_SYSTEM = """
You are a data discovery expert analysing a single data table.

You will receive a summary of ONE file: its name, row count, and all fields
with dtype, null percentage, unique count, and sample values.

Return ONLY valid JSON. No markdown. No text outside the JSON.

Your output must follow this exact structure:

{
  "entity_name": "Assets",
  "source_file": "assets.csv",
  "row_count": 10,
  "primary_key": "asset_no",
  "fields": [
    {
      "name": "asset_no",
      "dtype": "object",
      "role": "primary_key",
      "null_pct": 0.0,
      "unique_count": 10
    },
    {
      "name": "loc_code",
      "dtype": "object",
      "role": "foreign_key",
      "null_pct": 10.0,
      "unique_count": 4,
      "fk_pattern": "LOC-xx"
    }
  ],
  "fk_candidates": [
    {
      "field": "loc_code",
      "pattern": "LOC-xx",
      "sample_values": ["LOC-01", "LOC-02"],
      "reasoning": "Values follow a location code pattern, likely references a Locations table"
    }
  ],
  "data_quality_notes": [
    "loc_code has 10% nulls",
    "wo_id has 1 duplicate (unique_count < row_count)"
  ]
}

Rules:
- primary_key: field with highest uniqueness, low nulls, ID-like name or pattern
- foreign_key: ID-like field that is NOT the primary key (references another table)
- fk_pattern: abstract the sample values into a pattern e.g. "A00x", "USR-xx", "LOC-xx", "WO-xxxx"
- data_quality_notes: only flag real issues (nulls > 10%, duplicate PKs, suspicious values)
- If no FK candidates exist, return empty list []
"""


def _phase1_single_table(file_entry: dict, verbose: bool = True) -> dict:
    """
    Phase 1: analyse ONE table.

    Flow:
      1. Check if checkpoint exists → load and return immediately (skip API call)
      2. Call Gemini with retry
      3. Parse JSON response
      4. Save to checkpoint file immediately
      5. Return profile
    """
    file_name       = file_entry["file_name"]
    checkpoint_file = _checkpoint_path(file_name)

    # # ---- RESUME: checkpoint already exists ----
    # if os.path.exists(checkpoint_file):
        
    #     if verbose:
    #         print(f"  ~ {file_name}  →  loaded from checkpoint (skipping API call)")
    #     return load_output(os.path.basename(checkpoint_file))
    
    # ---- RESUME: checkpoint already exists ----
    if os.path.exists(checkpoint_file):
        cached = load_output(os.path.basename(checkpoint_file))

        # If cached profile is explicitly FAILED, reprocess via Gemini.
        if isinstance(cached, dict):
            status = str(cached.get("status", "SUCCESS")).strip().upper()
            if status == "FAILED":
                if verbose:
                    print(f"  ! {file_name}  ->  checkpoint status=FAILED, reprocessing...")
            else:
                if verbose:
                    print(f"  ~ {file_name}  ->  loaded from checkpoint (skipping API call)")
                return cached
        else:
            # Bad/empty checkpoint content -> reprocess
            if verbose:
                print(f"  ! {file_name}  ->  invalid checkpoint content, reprocessing...")


    # ---- CALL GROQ with retry ----
    prompt = f"""
Analyse this single data table and return the entity profile JSON.

{json.dumps(file_entry, indent=2)}
"""
    try:
        raw     = _call_bedrock_with_retry(prompt, PHASE1_SYSTEM, label=file_name)
        profile = _parse_json(raw)

    except Exception as e:
        # All retries exhausted — return a safe fallback profile
        # Agent continues with remaining tables, this one is flagged
        print(f"  x {file_name}  ->  failed after retries: {e}")
        profile = {
            "entity_name":        file_name,
            "source_file":        file_name,
            "row_count":          file_entry.get("row_count", 0),
            "primary_key":        None,
            "fields":             [],
            "fk_candidates":      [],
            "data_quality_notes": [f"Phase 1 failed after {MAX_RETRIES + 1} attempts: {e}"],
            "status":             "FAILED"
        }

    # ---- SAVE checkpoint immediately ----
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    with open(checkpoint_file, "w") as f:
        json.dump(profile, f, indent=2, default=str)

    return profile


# -------------------------------------------------------
# PHASE 2 — SYSTEM PROMPT
# -------------------------------------------------------

PHASE2_SYSTEM = """
You are a data relationship expert.

You will receive a list of entity signatures. Each signature contains:
- entity name
- primary key field name
- foreign key candidates: field name + abstract value pattern + sample values
- all field names for the entity

Your job is to find relationships ACROSS entities by reasoning about:
1. Matching field names (exact or similar)
2. Matching value patterns (e.g. "A00x" in WorkOrders matches "A00x" PK in Assets)
3. Business logic (assigned_to with "USR-xx" pattern references a Users entity)

Return ONLY valid JSON. No markdown. No text outside the JSON.

{
  "relationships": [
    {
      "from_entity": "WorkOrders",
      "from_field": "asset_no",
      "to_entity": "Assets",
      "to_field": "asset_no",
      "confidence": "HIGH",
      "reasoning": "WorkOrders.asset_no pattern A00x matches Assets.asset_no primary key"
    },
    {
      "from_entity": "WorkOrders",
      "from_field": "assigned_to",
      "to_entity": "Users",
      "to_field": "user_id",
      "confidence": "MEDIUM",
      "reasoning": "assigned_to values USR-01, USR-02 follow a user ID pattern. No Users table uploaded but entity likely exists."
    }
    ],
    "potential_duplicate_entities": [
        {
            "entity_a": "Assets",
            "entity_b": "Equipment",
            "confidence": "MEDIUM",
            "reasoning": "Strong overlap in identifiers and business attributes; field names differ but semantics are similar"
        }
  ]
}

Confidence levels:
- HIGH   : field name matches AND value pattern matches a known PK
- MEDIUM : value pattern matches a known PK but field name differs, OR references an entity not in the upload
- LOW    : pattern-only guess with no corroborating evidence

Only return relationships with at least MEDIUM confidence.
Only return potential_duplicate_entities with at least MEDIUM confidence.
If none found return: {"relationships": [], "potential_duplicate_entities": []}
"""


def _phase2_resolve_relationships(entity_profiles: list) -> tuple[list, list]:
    """
    Phase 2: find relationships across ALL entities.
    Single LLM call. Prompt is tiny — just FK signatures, no raw data.
    Retries up to MAX_RETRIES times on failure.

        Returns:
            (relationships, potential_duplicate_entities)
    """

    # Strip to minimal signatures only
    signatures = [
        {
            "entity":       p.get("entity_name"),
            "primary_key":  p.get("primary_key"),
            "fk_candidates": p.get("fk_candidates", []),
            "all_fields": [
                f.get("name") for f in p.get("fields", [])
                if isinstance(f, dict) and f.get("name")
            ]
        }
        for p in entity_profiles
    ]

    prompt = f"""
Here are the entity signatures from all uploaded tables.
Find all relationships between them.

{json.dumps(signatures, indent=2)}
"""

    required_rel = {"from_entity", "from_field", "to_entity", "to_field", "confidence", "reasoning"}
    required_dup = {"entity_a", "entity_b", "confidence", "reasoning"}

    last_error = None
    for parse_attempt in range(1, PARSE_RETRIES + 2):
        try:
            raw = _call_bedrock_with_retry(prompt, PHASE2_SYSTEM, label="Phase2-relationships")
            result = _parse_json(raw)

            # Gemini sometimes returns a top-level list instead of
            # {"relationships": [...]} — support both formats.
            if isinstance(result, dict):
                relationships = result.get("relationships", [])
                duplicates = result.get("potential_duplicate_entities", [])
            elif isinstance(result, list):
                relationships = result
                duplicates = []
            else:
                relationships = []
                duplicates = []

            filtered_relationships = [
                r for r in relationships
                if isinstance(r, dict)
                and required_rel.issubset(r.keys())
                and str(r.get("confidence", "")).upper() in {"HIGH", "MEDIUM"}
            ]

            filtered_duplicates = [
                d for d in duplicates
                if isinstance(d, dict)
                and required_dup.issubset(d.keys())
                and str(d.get("confidence", "")).upper() in {"HIGH", "MEDIUM"}
            ]

            return filtered_relationships, filtered_duplicates

        except json.JSONDecodeError as e:
            last_error = e
            if parse_attempt <= PARSE_RETRIES:
                print(f"  ! [Phase2-relationships] Invalid JSON output on parse attempt {parse_attempt}: {e}. Retrying...")
            else:
                break

        except Exception as e:
            # API/network/quota failures are already retried in _call_gemini_with_retry.
            # Do not re-enter parse retry loop (which would trigger extra API calls).
            last_error = e
            break

    print(f"  x Phase 2 failed after retries: {last_error}")
    return [], []


# -------------------------------------------------------
# PHASE 3 — MERGE
# -------------------------------------------------------

def _merge(entity_profiles: list, relationships: list, potential_duplicate_entities: list) -> dict:
    """
    Merges Phase 1 entity profiles with Phase 2 relationships
    and potential duplicate-entity pairs.

    Attaches each relationship to its source entity.
    """
    profile_map = {p["entity_name"]: p for p in entity_profiles}

    for rel in relationships:
        from_entity = rel.get("from_entity")
        if from_entity in profile_map:
            profile_map[from_entity].setdefault("relationships", []).append({
                "from_field": rel["from_field"],
                "to_entity":  rel["to_entity"],
                "to_field":   rel["to_field"],
                "confidence": rel["confidence"],
                "reasoning":  rel["reasoning"]
            })

    for profile in profile_map.values():
        profile.setdefault("relationships", [])

    total_fields = sum(len(p.get("fields", [])) for p in entity_profiles)
    failed       = [p["entity_name"] for p in entity_profiles if p.get("status") == "FAILED"]

    return {
        "entities": list(profile_map.values()),
        "potential_duplicate_entities": potential_duplicate_entities,
        "summary": {
            "total_entities":         len(entity_profiles),
            "total_fields":           total_fields,
            "relationships_detected": len(relationships),
            "duplicate_entity_pairs": len(potential_duplicate_entities),
            "failed_tables":          failed
        }
    }


# -------------------------------------------------------
# MAIN AGENT ENTRY POINT
# -------------------------------------------------------

def run_discovery_agent(file_paths: list, context: dict, verbose: bool = True) -> dict:
    """
    Runs the two-phase Discovery Agent with checkpointing + retry.

    On first run   : processes all files, saves per-table checkpoints
    On re-run      : skips already-checkpointed files, only processes remaining
    On API failure : retries up to MAX_RETRIES times, marks table as FAILED and continues

    Args:
        file_paths : list of CSV/JSON file paths to analyse
        context    : shared context store dict
        verbose    : print progress to console

    Returns:
        Updated context with context["entity_catalog"] populated
    """

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    if verbose:
        print("\n" + "=" * 60)
        print("  DISCOVERY AGENT  (two-phase + checkpointing)")
        print("=" * 60)
        print(f"  Max retries per table : {MAX_RETRIES}")
        print(f"  Checkpoint dir        : {config.OUTPUT_DIR}/")

    # --------------------------------------------------
    # STEP 1 — Read all files → build payload
    # --------------------------------------------------
    if verbose:
        print(f"\n[Step 1] Reading {len(file_paths)} file(s)...")

    payload = build_context_payload(file_paths)

    if not payload["files"]:
        print("  x No files could be read. Aborting.")
        return context

    # Store file registry in context for downstream agents
    context["file_registry"] = payload.get("registry", [])

    if verbose:
        registry = payload.get("registry", [])
        print(f"\n  File registry: {len(registry)} logical table(s)")
        for reg in registry:
            source_files = reg.get("source_files", [])
            merge_strategy = reg.get("merge_strategy", "schema-grouping")
            dupes = f"  <- {len(source_files)} files merged [{merge_strategy}]" if reg.get("has_duplicates") else ""
            logical_table = reg.get("logical_table", "UNKNOWN")
            print(f"    {logical_table:20s}  sources: {[s.get('file_name', '?') for s in source_files]}{dupes}")
        print()
        for f in payload["files"]:
            exists   = "CHECKPOINT EXISTS" if os.path.exists(_checkpoint_path(f["file_name"])) else "needs processing"
            row_info = f"{f['row_count']} rows" if f.get("row_count") else "DDL only"
            print(f"  + {f['file_name']:30s}  {row_info:15s}  {len(f['fields'])} fields  [{exists}]")

    # --------------------------------------------------
    # PHASE 1 — Parallel per-table analysis with checkpointing
    # --------------------------------------------------
    if verbose:
        print(f"\n[Phase 1] Analysing {len(payload['files'])} table(s) in parallel...")

    entity_profiles = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_phase1_single_table, file_entry, verbose): file_entry["file_name"]
            for file_entry in payload["files"]
        }
        for future in concurrent.futures.as_completed(futures):
            file_name = futures[future]
            try:
                profile = future.result()
                entity_profiles.append(profile)
                if verbose and profile.get("status") != "FAILED":
                    pk  = profile.get("primary_key", "?")
                    fks = len(profile.get("fk_candidates", []))
                    print(f"  + {file_name}  ->  {profile.get('entity_name')}  |  PK: {pk}  |  FK candidates: {fks}")
            except Exception as e:
                print(f"  x Unexpected error on {file_name}: {e}")

    if not entity_profiles:
        print("  x Phase 1 produced no profiles. Aborting.")
        return context

    # Summary of Phase 1
    succeeded = [p for p in entity_profiles if p.get("status") != "FAILED"]
    failed    = [p for p in entity_profiles if p.get("status") == "FAILED"]
    if verbose:
        print(f"\n  Phase 1 done: {len(succeeded)} succeeded, {len(failed)} failed")
        if failed:
            print(f"  Failed tables: {[p['entity_name'] for p in failed]}")

    # --------------------------------------------------
    # PHASE 2 — Relationship resolution
    # --------------------------------------------------
    if verbose:
        total_fk = sum(len(p.get("fk_candidates", [])) for p in succeeded)
        print(f"\n[Phase 2] Resolving relationships across {len(succeeded)} entities ({total_fk} FK candidates)...")

    relationships, potential_duplicate_entities = _phase2_resolve_relationships(succeeded)

    if verbose:
        if relationships:
            for rel in relationships:
                print(f"  + {rel['from_entity']}.{rel['from_field']}  ->  {rel['to_entity']}.{rel['to_field']}  [{rel['confidence']}]")
        else:
            print("  (no relationships detected)")

        if potential_duplicate_entities:
            print("\n  Potential duplicate entities:")
            for dup in potential_duplicate_entities:
                print(f"  ~ {dup['entity_a']}  <>  {dup['entity_b']}  [{dup['confidence']}]  |  {dup['reasoning']}")
        else:
            print("  (no potential duplicate entities detected)")

    # --------------------------------------------------
    # PHASE 3 — Merge + save final catalog
    # --------------------------------------------------
    if verbose:
        print(f"\n[Phase 3] Merging and saving final catalog...")

    entity_catalog = _merge(entity_profiles, relationships, potential_duplicate_entities)
    save_result    = save_output(entity_catalog, "entity_catalog.json")
    context["entity_catalog"] = entity_catalog

    if verbose:
        print(f"  + Saved to: {save_result.get('saved_to')}")
        print("\n" + "=" * 60)
        print("  DISCOVERY AGENT COMPLETE")
        print("=" * 60)
        s = entity_catalog["summary"]
        print(f"  Entities      : {s['total_entities']}")
        print(f"  Fields        : {s['total_fields']}")
        print(f"  Relationships : {s['relationships_detected']}")
        print(f"  Dup pairs     : {s['duplicate_entity_pairs']}")
        if s["failed_tables"]:
            print(f"  Failed tables : {s['failed_tables']}")
        print(f"\n  Per-table checkpoints saved in: {config.OUTPUT_DIR}/phase1_*.json")
        print(f"  To rerun from scratch, delete: {config.OUTPUT_DIR}/phase1_*.json")

    return context
