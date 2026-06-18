"""
migration_approval_agent.py
----------------------------
Agent 12 — Approval Agent

Reads:  context.review, context.execution, context.validation
Writes: context["approval"]

Checks policies:
- Review must be APPROVED or APPROVED WITH WARNINGS.
- Execution must be SUCCESS.
- Validation must be PASS and quality_score >= 95.

Output shape:
  {
    "status":      "APPROVED | REJECTED | CONDITIONAL",
    "reason":      "...",
    "approved_by": "OnboardIQ Compliance Agent",
    "timestamp":   "...",
    "llm_trace":   { ... }
  }
"""

import os
import json
import time
import re
from datetime import datetime, timezone

import config
from context import append_audit_event

MAX_RETRIES = 2
RETRY_DELAY = 3

AGENT_NAME = "ApprovalAgent"
PROMPT_ID  = "migration.approval.v1"


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


# ── LLM system prompt ──────────────────────────────────────────────────────────

APPROVAL_SYSTEM = """You are a senior database migration compliance officer.

Based on the review, execution, and validation records, draft a comprehensive justification narrative for the final decision.
Summarise the outcomes and any warnings or recommendations.
Return ONLY valid JSON.

Output format:
{
  "reason": "<multi-line reasoning narrative summing up results and compliance check reasons>"
}
"""


# ── main agent entry point ─────────────────────────────────────────────────────

def run_migration_approval_agent(context: dict, verbose: bool = True) -> dict:
    """
    Agent 12 — Approval Agent.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION APPROVAL AGENT  (Agent 12)")
        print("=" * 60)

    review     = context.get("review", {})
    execution  = context.get("execution", {})
    validation = context.get("validation", {})

    violations = []
    
    # 1. Enforce hard Python policies
    if review.get("status") not in ("APPROVED", "APPROVED WITH WARNINGS"):
        violations.append(
            f"Review status is '{review.get('status')}', must be APPROVED or APPROVED WITH WARNINGS."
        )
    
    if execution.get("status") != "SUCCESS":
        violations.append(f"Execution status is '{execution.get('status')}', must be SUCCESS.")
        
    if validation.get("status") != "PASS":
        violations.append(f"Validation status is '{validation.get('status')}', must be PASS.")
        
    val_score = validation.get("quality_score", 0)
    if val_score < 95:
        violations.append(f"Validation quality score is {val_score}/100, must be >= 95.")

    status = "APPROVED"
    if violations:
        status = "REJECTED"
        if verbose:
            print("  x Policy violations detected:")
            for v in violations:
                print(f"    - {v}")
    
    # 2. Call LLM to draft reasoning narrative
    prompt = f"""Generate compliance justification.
DECISION STATUS: {status}
VIOLATIONS FOUND: {json.dumps(violations, indent=2)}

REVIEW RECORD:
- status: {review.get("status")}
- risk_level: {review.get("risk_level")}
- issues_count: {len(review.get("issues", []))}

EXECUTION RECORD:
- status: {execution.get("status")}
- rows_processed: {execution.get("rows_processed")}
- failed_tasks: {json.dumps(execution.get("failed_tasks"), indent=2)}

VALIDATION RECORD:
- status: {validation.get("status")}
- quality_score: {val_score}
- metrics: {json.dumps(validation.get("metrics"), indent=2)}
"""

    llm_trace = {}
    reason = ""
    try:
        raw, llm_trace = _call_bedrock(prompt, APPROVAL_SYSTEM, label=AGENT_NAME)
        res_data = json.loads(raw.strip().lstrip("```json").rstrip("```").strip())
        reason = res_data.get("reason", "")
    except Exception as e:
        if verbose:
            print(f"  ! LLM justification failed: {e}")
        reason = f"Drafted narrative unavailable. Decision based on policy checks: {status}."
        if violations:
            reason += " Violations: " + "; ".join(violations)

    timestamp = datetime.now(timezone.utc).isoformat()
    approval_record = {
        "status":      status,
        "reason":      reason,
        "approved_by": "OnboardIQ Compliance Agent",
        "timestamp":   timestamp,
        "llm_trace":   llm_trace
    }

    context["approval"] = approval_record

    append_audit_event(context, AGENT_NAME, "final_decision", "completed", {
        "status":      status,
        "approved_by": "OnboardIQ Compliance Agent",
        "violations_count": len(violations)
    })

    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION APPROVAL COMPLETE")
        print("=" * 60)
        print(f"  Final Status : {status}")
        print(f"  Approved By  : OnboardIQ Compliance Agent")
        print(f"  Reason       : {reason[:120]}...")
        print("=" * 60)

    return context
