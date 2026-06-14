"""
migration_repair_agent.py
--------------------------
Agent 9 — Migration Repair Agent

Runs conditionally when:
  - context.review.status == "REJECTED"
  - context.review.fix_required is non-empty

Reads:  context.review.fix_required, context.migration.artifacts
Writes: context["repair"] (and updates context.migration.artifacts with new hashes)

Output shape:
  {
    "status":              "COMPLETED | FAILED | PARTIAL",
    "fixed_files":         0,
    "repaired_artifacts":  [...],
    "issues":              [...],
    "llm_trace":           { ... }
  }

Failure codes: REPAIR_INSTRUCTION_INVALID | PATCH_WRITE_FAILURE | REPAIR_FAILED | LLM_UNAVAILABLE
"""

import os
import json
import time
import re
import hashlib
from pathlib import Path

import config
from context import append_audit_event

MAX_RETRIES = 2
RETRY_DELAY = 3

AGENT_NAME = "MigrationRepairAgent"
PROMPT_ID  = "migration.repair.v1"


# ── Bedrock helper ─────────────────────────────────────────────────────────────

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


SYSTEM_PROMPT = """You are a senior migration code repair engineer.

You will be given:
- existing code
- a list of issues
- fix instructions

RULES:
- DO NOT invent new features
- DO NOT change schema unless instructed
- ONLY fix what is requested
- preserve structure and logging

Return ONLY valid JSON:
{
  "fixed_code": "<complete corrected file>",
  "summary": "<what was fixed>"
}
"""


# ── main agent entry point ─────────────────────────────────────────────────────

def run_migration_repair_agent(context: dict, verbose: bool = True) -> dict:
    """
    Agent 9 — Migration Repair Agent.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION REPAIR AGENT  (Agent 9)")
        print("=" * 60)

    review       = context.get("review", {})
    fixes        = review.get("fix_required", [])
    migration    = context.get("migration", {})
    artifacts    = migration.get("artifacts", [])
    
    # Check precondition: Only run if review status is REJECTED and there are fixes required
    if review.get("status") != "REJECTED" or not fixes:
        if verbose:
            print("  Preconditions not met: Review is not REJECTED or no fixes requested. Skipping.")
        return context

    repaired_artifacts = []
    issues             = []
    fixed_count        = 0
    total_tokens_in    = 0
    total_tokens_out   = 0
    total_latency_ms   = 0
    model_used         = ""

    for fix in fixes:
        entity        = fix.get("entity")
        instruction   = fix.get("instruction")
        artifact_type = fix.get("artifact_type")

        # Find matching artifact
        target_art = None
        for art in artifacts:
            if art.get("entity") == entity and art.get("artifact_type") == artifact_type:
                target_art = art
                break

        if not target_art:
            msg = f"REPAIR_INSTRUCTION_INVALID: No matching artifact found for entity {entity} / type {artifact_type}"
            issues.append(msg)
            print(f"  ! {msg}")
            continue

        rel_path = target_art.get("path", "")
        # Resolve path
        abs_candidates = [
            Path(rel_path),
            Path(config.OUTPUT_DIR).parent / rel_path,
        ]
        abs_path = None
        current_code = None
        for candidate in abs_candidates:
            if candidate.exists():
                try:
                    current_code = candidate.read_text(encoding="utf-8")
                    abs_path = candidate
                    break
                except Exception:
                    pass

        if abs_path is None or current_code is None:
            msg = f"PATCH_WRITE_FAILURE: Could not read source code of artifact at {rel_path}"
            issues.append(msg)
            print(f"  ! {msg}")
            continue

        prompt = f"""ENTITY: {entity}
FILE: {rel_path}

FIX INSTRUCTION:
{instruction}

CURRENT CODE:
{current_code}
"""

        try:
            if verbose:
                print(f"  Repairing {entity} {artifact_type} at {rel_path}...")
            
            raw, llm_trace = _call_bedrock(prompt, SYSTEM_PROMPT, label=AGENT_NAME)
            
            total_tokens_in  += llm_trace.get("tokens_in", 0)
            total_tokens_out += llm_trace.get("tokens_out", 0)
            total_latency_ms += llm_trace.get("latency_ms", 0)
            model_used        = llm_trace.get("model", "")

            result     = _parse_json(raw)
            fixed_code = result.get("fixed_code")

            if not fixed_code:
                raise ValueError("LLM returned empty fixed_code in JSON.")

            # Write file back
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(fixed_code, encoding="utf-8")
            
            # Recalculate hash and update context artifact record
            new_sha = hashlib.sha256(fixed_code.encode()).hexdigest()
            target_art["sha256"]  = new_sha
            target_art["version"] = target_art.get("version", 1) + 1

            repaired_artifacts.append(target_art["artifact_id"])
            fixed_count += 1
            if verbose:
                print(f"  ✔ Successfully patched {rel_path}. New SHA: {new_sha[:8]}")

        except Exception as e:
            msg = f"REPAIR_FAILED: Failed repairing {rel_path} — {e}"
            issues.append(msg)
            print(f"  x {msg}")

    # Set repair status
    if len(issues) == 0:
        repair_status = "COMPLETED"
    elif fixed_count > 0:
        repair_status = "PARTIAL"
    else:
        repair_status = "FAILED"

    context["repair"] = {
        "status":             repair_status,
        "fixed_files":         fixed_count,
        "repaired_artifacts":  repaired_artifacts,
        "issues":              issues,
        "llm_trace": {
            "model":       model_used,
            "prompt_id":   PROMPT_ID,
            "temperature": 0.0,
            "tokens_in":   total_tokens_in,
            "tokens_out":  total_tokens_out,
            "latency_ms":  total_latency_ms,
        }
    }

    append_audit_event(context, AGENT_NAME, "repair_artifacts", "completed", {
        "status":             repair_status,
        "fixed_files_count":  fixed_count,
        "issues_count":       len(issues),
    })

    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION REPAIR COMPLETE")
        print("=" * 60)
        print(f"  Status             : {repair_status}")
        print(f"  Patched files count: {fixed_count}")
        print(f"  Errors encountered : {len(issues)}")
        print("=" * 60)

    return context
