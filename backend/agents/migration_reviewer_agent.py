"""
migration_reviewer_agent.py
------------------------------
Agent 8 — Migration Reviewer  (3-pass staged review)

Pass 1 — Per-entity:   one LLM call per entity reviewing migrate + rollback + validate together.
          Checks: correct source filename, all mappings applied, quality rules enforced,
                  env vars used, log stages present, transaction blocks, DuckDB syntax.

Pass 2 — Cross-entity: one LLM call across all migration scripts together.
          Checks: FK references match silver-layer table names, wave N scripts reference
                  wave N-1 tables correctly, no circular deps, consistent table naming.

Pass 3 — Orchestrator: one LLM call on run_migration_*.py only.
          Checks: script paths exist on disk, wave order matches plan, fail-fast on error,
                  DUCKDB_PATH validated at startup, subprocess env forwarded.

Each pass has its own repair loop via Agent 9. All three passes must clear before
status is set to APPROVED. Agent 10 (Execution) requires APPROVED.

Reads:  context.migration, context.specification, context.mappings, context.plan
Writes: context["review"]

Output shape:
  {
  "status":       "APPROVED | APPROVED WITH WARNINGS | REJECTED",
    "risk_level":   "LOW | MEDIUM | HIGH",
    "pass_results": { "pass1": {...}, "pass2": {...}, "pass3": {...} },
    "issues":       [...],          <- merged across all passes
    "fix_required": [...],          <- merged across all passes
    "summary":      "...",
    "llm_trace":    { tokens_in, tokens_out, latency_ms, ... }
  }

Failure codes: SCHEMA_MISMATCH | BUSINESS_RULE_ERROR | HIGH_RISK_DETECTED
               | UNSUPPORTED_TARGET_DATABASE | LLM_UNAVAILABLE
"""

import os
import json
import time
import re
from pathlib import Path

import config
from context import append_audit_event

MAX_RETRIES = 2
RETRY_DELAY = 3
AGENT_NAME  = "MigrationReviewer"
PROMPT_ID   = "migration.reviewer.v2"


# ── Bedrock ────────────────────────────────────────────────────────────────────

def _call_bedrock(prompt: str, system: str, label: str = "",
                  max_tokens: int = 4096, temperature: float = 0.0) -> tuple[str, dict]:
    last_error = None
    model_id   = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    start_ms   = time.time() * 1000
    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client  = config.get_bedrock_client()
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens":        max_tokens,
                "system":            system,
                "messages":          [{"role": "user", "content": prompt}],
                "temperature":       temperature,
            }
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            body    = json.loads(response["body"].read())
            text    = body["content"][0]["text"]
            latency = int(time.time() * 1000 - start_ms)
            usage   = body.get("usage", {})
            return text, {
                "model": model_id, "prompt_id": PROMPT_ID,
                "temperature": temperature,
                "tokens_in":  usage.get("input_tokens", 0),
                "tokens_out": usage.get("output_tokens", 0),
                "latency_ms": latency,
            }
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


# ── artifact loader ────────────────────────────────────────────────────────────

def _read_artifact(art: dict, char_limit: int = 4000) -> str | None:
    path = art.get("path", "")
    for candidate in [Path(path), Path(config.OUTPUT_DIR).parent / path]:
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8")[:char_limit]
            except Exception:
                pass
    return None


def _load_entity_scripts(artifacts: list, entity: str) -> dict:
    """Load all three scripts for one entity. Returns {artifact_type: content}."""
    result = {}
    for art in artifacts:
        if art.get("entity") == entity:
            content = _read_artifact(art)
            if content:
                result[art["artifact_type"]] = content
    return result


def _load_all_migration_scripts(artifacts: list) -> dict:
    """Load migration_script content for every entity. Returns {entity: content}."""
    result = {}
    for art in artifacts:
        if art.get("artifact_type") == "migration_script":
            content = _read_artifact(art)
            if content:
                result[art["entity"]] = content
    return result


# ── static safety checks (deterministic, no LLM) ─────────────────────────────

def _static_checks(artifacts: list, target: str) -> list:
    issues = []
    for art in artifacts:
        path, atype, entity = art.get("path",""), art.get("artifact_type",""), art.get("entity","")
        content = _read_artifact(art, char_limit=999999)

        if content is None:
            issues.append({
                "entity": entity, "artifact_type": atype, "pass": "static",
                "severity": "CRITICAL", "type": "CODE_GENERATION_ERROR",
                "description": f"Artifact file not found: {path}", "line_reference": "",
            })
            continue

        low = content.lower()
        entity_slug = (entity or "").strip().lower()
        expected_duckdb_tables = {
            "user": "users",
            "users": "users",
            "asset": "asset",
            "assets": "asset",
            "location": "location",
            "locations": "location",
            "workorder": "workorder",
            "workorders": "workorder",
        }
        expected_table = expected_duckdb_tables.get(entity_slug, entity_slug)

        if target == "duckdb" and atype == "migration_script":
            for danger in ("drop table ", "truncate "):
                if danger in low and "rollback" not in path:
                    issues.append({
                        "entity": entity, "artifact_type": atype, "pass": "static",
                        "severity": "HIGH", "type": "BUSINESS_RULE_ERROR",
                        "description": f"Destructive statement '{danger.strip()}' in migration script (not rollback).",
                        "line_reference": "",
                    })
            delete_matches = re.findall(r"\bdelete\s+from\s+([A-Za-z_][A-Za-z0-9_]*)", content, flags=re.IGNORECASE)
            for table_name in delete_matches:
                if table_name.strip().lower() != expected_table:
                    issues.append({
                        "entity": entity, "artifact_type": atype, "pass": "static",
                        "severity": "HIGH", "type": "BUSINESS_RULE_ERROR",
                        "description": f"Destructive statement 'delete from {table_name}' targets the wrong table for {entity}.",
                        "line_reference": "",
                    })
            if "begin" not in low and "con.begin" not in low:
                issues.append({
                    "entity": entity, "artifact_type": atype, "pass": "static",
                    "severity": "HIGH", "type": "BUSINESS_RULE_ERROR",
                    "description": "Missing transaction block (BEGIN/COMMIT). DuckDB requires explicit transactions.",
                    "line_reference": "",
                })
            for bad in ("delimited by", "load data infile", "bulk insert"):
                if bad in low:
                    issues.append({
                        "entity": entity, "artifact_type": atype, "pass": "static",
                        "severity": "HIGH", "type": "SCHEMA_MISMATCH",
                        "description": f"Unsupported DuckDB syntax: '{bad.upper()}'. Use READ_CSV or COPY.",
                        "line_reference": "",
                    })
            if "DUCKDB_PATH" not in content:
                issues.append({
                    "entity": entity, "artifact_type": atype, "pass": "static",
                    "severity": "HIGH", "type": "BUSINESS_RULE_ERROR",
                    "description": "Script does not read DUCKDB_PATH from environment variables.",
                    "line_reference": "",
                })

        if target == "dynamodb" and atype == "migration_script":
            if "batch_writer" not in low and "batch_write_item" not in low:
                issues.append({
                    "entity": entity, "artifact_type": atype, "pass": "static",
                    "severity": "HIGH", "type": "BUSINESS_RULE_ERROR",
                    "description": "DynamoDB script does not use batch_writer / batch_write_item.",
                    "line_reference": "",
                })

    return issues


# ── pass system prompts ────────────────────────────────────────────────────────

_PASS1_SYSTEM = """You are a senior migration code reviewer.

Review ONE entity's three scripts (migrate, rollback, validate) in isolation.

Check every item below — flag anything missing or wrong:
  1. Source filename matches Source file exactly (not invented).
  2. Every field mapping is applied with the correct transformation.
  3. All QUALITY REQUIREMENTS are enforced in validate script.
  4. DUCKDB_PATH read from os.environ / environment variables — never hardcoded.
  5. Transaction BEGIN/COMMIT present in migrate script.
  6. DuckDB-native syntax only (READ_CSV / COPY — not LOAD DATA INFILE etc.).
  7. Structured JSON log lines emitted for every OPERATIONAL stage.
  8. Connection closed in finally block.
  9. Rollback script undoes exactly what migrate creates.
  10. Validate script raises on failure, not just prints.

Severity: CRITICAL / HIGH / MEDIUM / LOW
Status: REJECTED if any CRITICAL; APPROVED WITH WARNINGS if any HIGH or MEDIUM; else APPROVED.

Return ONLY valid JSON:
{
  "status": "APPROVED | APPROVED WITH WARNINGS | REJECTED",
  "risk_level": "LOW | MEDIUM | HIGH",
  "issues": [{"entity":"","artifact_type":"","severity":"","type":"","description":"","line_reference":""}],
  "fix_required": [{"entity":"","artifact_type":"","instruction":""}],
  "summary": ""
}"""

_PASS2_SYSTEM = """You are a senior migration code reviewer specialising in cross-entity consistency.

You will receive all migration scripts together. Check:
  1. Every FK reference (e.g. SELECT ... FROM silver_layer.table1) names a table
     that is actually created by an earlier entity's migrate script.
  2. Silver-layer table names are consistent — if entity A creates 'silver_layer.assets',
     entity B must reference exactly 'silver_layer.assets', not 'silver.assets' or 'assets'.
  3. Wave ordering is respected — no wave-N script reads from a table created in wave N+1.
  4. No circular dependencies between entities.
  5. Shared column names referenced across scripts exist in the source entity's spec.

Return ONLY valid JSON:
{
  "status": "APPROVED | APPROVED WITH WARNINGS | REJECTED",
  "risk_level": "LOW | MEDIUM | HIGH",
  "issues": [{"entity":"","artifact_type":"","severity":"","type":"","description":"","line_reference":""}],
  "fix_required": [{"entity":"","artifact_type":"","instruction":""}],
  "summary": ""
}"""

_PASS3_SYSTEM = """You are a senior migration code reviewer specialising in execution orchestration.

Review the orchestrator script (run_migration_*.py). Check:
  1. All script_path values point to files that exist (listed in ARTIFACT PATHS).
  2. Steps execute in ascending wave order matching the PLAN.
  3. Fail-fast: orchestrator stops and exits non-zero on first failed step.
  4. DUCKDB_PATH is validated at startup before any step runs.
  5. os.environ.copy() is passed to every subprocess so env vars are forwarded.
  6. Structured JSON log lines emitted at orchestrator_start, step_start, step_end, orchestrator_end.
  7. No hardcoded file paths or credentials in the orchestrator itself.

Return ONLY valid JSON:
{
  "status": "APPROVED | APPROVED WITH WARNINGS | REJECTED",
  "risk_level": "LOW | MEDIUM | HIGH",
  "issues": [{"entity":"orchestrator","artifact_type":"orchestrator","severity":"","type":"","description":"","line_reference":""}],
  "fix_required": [{"entity":"orchestrator","artifact_type":"orchestrator","instruction":""}],
  "summary": ""
}"""


# ── pass runners ───────────────────────────────────────────────────────────────

def _run_pass1(artifacts, context, verbose) -> tuple[dict, dict]:
    """
    Pass 1: review each entity's three scripts independently.
    Returns (merged_result, aggregated_trace).
    """
    target        = context.get("target_database")
    spec_data     = context.get("specification", {})
    mappings_data = context.get("mappings", {})
    compact_spec  = spec_data.get("entity_specification", spec_data) if isinstance(spec_data, dict) else spec_data
    compact_maps  = mappings_data.get("mappings", mappings_data) if isinstance(mappings_data, dict) else mappings_data
    file_registry = context.get("file_registry") or []

    entities    = list({a["entity"] for a in artifacts})
    all_issues  = []
    all_fixes   = []
    trace       = {"tokens_in": 0, "tokens_out": 0, "latency_ms": 0, "model": ""}
    any_rejected = False
    any_warning   = False

    for entity in entities:
        scripts      = _load_entity_scripts(artifacts, entity)
        entity_spec  = (compact_spec.get(entity, []) if isinstance(compact_spec, dict) else [])
        entity_maps  = next((m.get("field_mappings", []) for m in
                             (compact_maps if isinstance(compact_maps, list) else [])
                             if m.get("source_entity") == entity or m.get("entity") == entity), [])
        entity_reg   = next((e for e in file_registry if e.get("logical_table") == entity), {})

        prompt = f"""Review scripts for entity: {entity}
TARGET: {target}

SCRIPTS:
{json.dumps(scripts, indent=2)}

FIELD MAPPINGS:
{json.dumps(entity_maps, indent=2)}

SPECIFICATION:
{json.dumps(entity_spec, indent=2)}

FILE REGISTRY ENTRY (source filename must match exactly):
{json.dumps(entity_reg, indent=2)}

QUALITY REQUIREMENTS:
{json.dumps(context.get("quality_requirements", {}).get(entity, []), indent=2)}

OPERATIONAL REQUIREMENTS:
{json.dumps(context.get("operational_requirements", {}), indent=2)}
"""
        if verbose:
            print(f"    Pass 1 → reviewing '{entity}'...")
        try:
            raw, t = _call_bedrock(prompt, _PASS1_SYSTEM, label=f"pass1:{entity}", max_tokens=4096)
            trace["tokens_in"]  += t.get("tokens_in", 0)
            trace["tokens_out"] += t.get("tokens_out", 0)
            trace["latency_ms"] += t.get("latency_ms", 0)
            trace["model"]       = t["model"]
            result = _parse_json(raw)
            for iss in result.get("issues", []):
                iss["pass"] = "pass1"
                all_issues.append(iss)
            for fix in result.get("fix_required", []):
                all_fixes.append(fix)
            if result.get("status") == "REJECTED":
                any_rejected = True
            if result.get("status") == "APPROVED WITH WARNINGS":
                any_warning = True
        except Exception as e:
            all_issues.append({
                "entity": entity, "artifact_type": "all", "pass": "pass1",
                "severity": "HIGH", "type": "CODE_GENERATION_ERROR",
                "description": f"Pass 1 LLM error: {e}", "line_reference": "",
            })
            any_warning = True

    severities   = {i["severity"] for i in all_issues}
    risk_level   = "HIGH" if "CRITICAL" in severities or "HIGH" in severities else (
                   "MEDIUM" if "MEDIUM" in severities else "LOW")
    if any_rejected:
        status = "REJECTED"
    elif any_warning or "HIGH" in severities or "MEDIUM" in severities:
        status = "APPROVED WITH WARNINGS"
    else:
        status = "APPROVED"
    return {
        "status":       status,
        "risk_level":   risk_level,
        "issues":       all_issues,
        "fix_required": all_fixes,
    }, trace


def _run_pass2(artifacts, context, verbose) -> tuple[dict, dict]:
    """
    Pass 2: cross-entity consistency — all migration scripts together.
    """
    target         = context.get("target_database")
    plan           = context.get("plan", {})
    all_mig_scripts = _load_all_migration_scripts(artifacts)

    prompt = f"""Check cross-entity consistency of all migration scripts.
TARGET: {target}

ALL MIGRATION SCRIPTS:
{json.dumps(all_mig_scripts, indent=2)}

PLAN (wave ordering):
{json.dumps(plan.get("waves", []), indent=2)}

SPECIFICATION (all entities):
{json.dumps(context.get("specification", {}).get("entity_specification", {}), indent=2)}
"""
    if verbose:
        print("    Pass 2 → cross-entity consistency check...")
    try:
        raw, trace = _call_bedrock(prompt, _PASS2_SYSTEM, label="pass2", max_tokens=4096)
        result = _parse_json(raw)
        for iss in result.get("issues", []):
            iss["pass"] = "pass2"
        return result, trace
    except Exception as e:
        return {
            "status": "REJECTED", "risk_level": "HIGH",
            "issues": [{"entity": "cross-entity", "artifact_type": "all", "pass": "pass2",
                        "severity": "HIGH", "type": "CODE_GENERATION_ERROR",
                        "description": f"Pass 2 LLM error: {e}", "line_reference": ""}],
            "fix_required": [],
        }, {}


def _run_pass3(artifacts, context, verbose) -> tuple[dict, dict]:
    """
    Pass 3: orchestrator review.
    """
    migration    = context.get("migration", {})
    orchestrator = migration.get("orchestrator", {})
    orch_path    = orchestrator.get("path", "")
    orch_content = None

    for candidate in [Path(orch_path), Path(config.OUTPUT_DIR).parent / orch_path]:
        if candidate.exists():
            orch_content = candidate.read_text(encoding="utf-8")
            break

    if not orch_content:
        return {
            "status": "REJECTED", "risk_level": "HIGH",
            "issues": [{"entity": "orchestrator", "artifact_type": "orchestrator",
                        "pass": "pass3", "severity": "CRITICAL",
                        "type": "CODE_GENERATION_ERROR",
                        "description": f"Orchestrator not found at {orch_path}",
                        "line_reference": ""}],
            "fix_required": [{"entity": "orchestrator", "artifact_type": "orchestrator",
                              "instruction": "Re-run Agent 7b to regenerate the orchestrator."}],
        }, {}

    artifact_paths = [{"entity": a["entity"], "path": a["path"]} for a in artifacts
                      if a["artifact_type"] == "migration_script"]
    plan           = context.get("plan", {})

    prompt = f"""Review the orchestrator script.

ORCHESTRATOR SCRIPT:
{orch_content}

ARTIFACT PATHS (script_path values must match these):
{json.dumps(artifact_paths, indent=2)}

PLAN (wave ordering to verify):
{json.dumps(plan.get("waves", []), indent=2)}
"""
    if verbose:
        print("    Pass 3 → orchestrator review...")
    try:
        raw, trace = _call_bedrock(prompt, _PASS3_SYSTEM, label="pass3", max_tokens=4096)
        result = _parse_json(raw)
        for iss in result.get("issues", []):
            iss["pass"] = "pass3"
        return result, trace
    except Exception as e:
        return {
            "status": "REJECTED", "risk_level": "HIGH",
            "issues": [{"entity": "orchestrator", "artifact_type": "orchestrator", "pass": "pass3",
                        "severity": "HIGH", "type": "CODE_GENERATION_ERROR",
                        "description": f"Pass 3 LLM error: {e}", "line_reference": ""}],
            "fix_required": [],
        }, {}


# ── derive overall status from merged issues ───────────────────────────────────

def _derive_status(all_issues: list, all_fixes: list) -> tuple[str, str]:
    severities = {i["severity"] for i in all_issues}
    if "CRITICAL" in severities:
        return "REJECTED", "HIGH"
    if "HIGH" in severities:
        return "APPROVED WITH WARNINGS", "HIGH"
    if "MEDIUM" in severities:
        return "APPROVED WITH WARNINGS", "MEDIUM"
    return "APPROVED", "LOW"


# ── main entry point ───────────────────────────────────────────────────────────

def run_migration_reviewer_agent(context: dict, verbose: bool = True) -> dict:
    """
    Agent 8 — 3-pass staged reviewer.
    Pass 1: per-entity scripts.
    Pass 2: cross-entity consistency.
    Pass 3: orchestrator.
    Only CRITICAL findings block execution. HIGH and MEDIUM findings return
    APPROVED WITH WARNINGS.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION REVIEWER  (Agent 8 — 3-pass)")
        print("=" * 60)

    target = context.get("target_database")
    if target not in ("duckdb", "dynamodb"):
        msg = f"UNSUPPORTED_TARGET_DATABASE: '{target}'"
        context["review"] = {"status": "REJECTED", "error": msg, "llm_trace": {}}
        append_audit_event(context, AGENT_NAME, "target_validation", "failed", {"error": msg})
        return context

    migration = context.get("migration", {})
    artifacts = migration.get("artifacts", [])
    if not artifacts:
        msg = "No migration artifacts found. Run Agent 7 first."
        context["review"] = {"status": "REJECTED", "error": msg, "llm_trace": {}}
        append_audit_event(context, AGENT_NAME, "input_validation", "failed", {"error": msg})
        return context

    # ── static checks ──────────────────────────────────────────────────────────
    if verbose:
        print(f"  Static checks on {len(artifacts)} artifacts...")
    static_issues = _static_checks(artifacts, target)
    static_crits  = sum(1 for i in static_issues if i["severity"] == "CRITICAL")
    static_warns  = sum(1 for i in static_issues if i["severity"] in ("HIGH", "MEDIUM"))
    if verbose:
        print(f"  Static: {len(static_issues)} issue(s), {static_crits} critical, {static_warns} warning(s)")

    # ── pass 1 ─────────────────────────────────────────────────────────────────
    if verbose:
        print(f"\n  Pass 1 — per-entity script review ({len({a['entity'] for a in artifacts})} entities)...")
    p1_result, p1_trace = _run_pass1(artifacts, context, verbose)

    # ── pass 2 ─────────────────────────────────────────────────────────────────
    if verbose:
        print(f"\n  Pass 2 — cross-entity consistency...")
    p2_result, p2_trace = _run_pass2(artifacts, context, verbose)

    # ── pass 3 ─────────────────────────────────────────────────────────────────
    if verbose:
        print(f"\n  Pass 3 — orchestrator review...")
    p3_result, p3_trace = _run_pass3(artifacts, context, verbose)

    # ── merge all issues ───────────────────────────────────────────────────────
    all_issues = static_issues.copy()
    seen       = {(i["entity"], i["description"]) for i in static_issues}
    for iss in (p1_result.get("issues",[]) + p2_result.get("issues",[]) + p3_result.get("issues",[])):
        key = (iss.get("entity",""), iss.get("description",""))
        if key not in seen:
            all_issues.append(iss)
            seen.add(key)

    all_fixes = (p1_result.get("fix_required",[]) +
                 p2_result.get("fix_required",[]) +
                 p3_result.get("fix_required",[]))

    status, risk_level = _derive_status(all_issues, all_fixes)

    # ── aggregate trace ────────────────────────────────────────────────────────
    agg_trace = {
        "model":      p1_trace.get("model") or p2_trace.get("model") or p3_trace.get("model",""),
        "prompt_id":  PROMPT_ID,
        "tokens_in":  (p1_trace.get("tokens_in",0) + p2_trace.get("tokens_in",0)
                       + p3_trace.get("tokens_in",0)),
        "tokens_out": (p1_trace.get("tokens_out",0) + p2_trace.get("tokens_out",0)
                       + p3_trace.get("tokens_out",0)),
        "latency_ms": (p1_trace.get("latency_ms",0) + p2_trace.get("latency_ms",0)
                       + p3_trace.get("latency_ms",0)),
    }

    summary_parts = [
        f"Pass 1 ({p1_result['status']}): {p1_result.get('summary','')}",
        f"Pass 2 ({p2_result['status']}): {p2_result.get('summary','')}",
        f"Pass 3 ({p3_result['status']}): {p3_result.get('summary','')}",
    ]

    print(f'[debug] review status being written: {repr(status)}')
    context["review"] = {
        "status":       status,
        "risk_level":   risk_level,
        "pass_results": {
            "pass1": p1_result,
            "pass2": p2_result,
            "pass3": p3_result,
        },
        "issues":       all_issues,
        "fix_required": all_fixes,
        "summary":      " | ".join(summary_parts),
        "llm_trace":    agg_trace,
    }

    append_audit_event(context, AGENT_NAME, "review_completed", "completed", {
        "status":      status,
        "risk_level":  risk_level,
        "total_issues": len(all_issues),
        "pass1_status": p1_result["status"],
        "pass2_status": p2_result["status"],
        "pass3_status": p3_result["status"],
    })

    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION REVIEWER COMPLETE")
        print("=" * 60)
        print(f"  Pass 1 : {p1_result['status']}")
        print(f"  Pass 2 : {p2_result['status']}")
        print(f"  Pass 3 : {p3_result['status']}")
        print(f"  Overall: {status}  (risk: {risk_level})")
        print(f"  Issues : {len(all_issues)}  |  Fixes needed: {len(all_fixes)}")
        if all_issues:
            for iss in all_issues[:6]:
                print(f"    [{iss['severity']:8s}] [{iss.get('pass','?')}] "
                      f"{iss['entity']} — {iss['description'][:65]}")
        print("=" * 60)

    return context
