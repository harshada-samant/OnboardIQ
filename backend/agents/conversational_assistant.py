"""
conversational_assistant.py
-----------------------------
Agent 7 — Conversational Onboarding Assistant

A Groq-powered chat agent that can answer any question about the
onboarding pipeline, AND lets the user confirm/override/add field
mappings in real time through natural language.

Key behaviours:
  - Answers questions about entity catalog, quality report, mappings.
  - Detects mapping intent ("map asset_no to asset_id") and calls
    mapping_agent.add_user_mapping() immediately, saving to disk.
  - Re-runs mapping_agent.run_mapping_agent() after user changes so
    the mapping document is always up to date for downstream agents.
  - Maintains full conversation history so context is never lost.
  - Type 'exit' or 'quit' to end the session.

Usage (standalone):
    python -m agents.conversational_assistant

Usage (from pipeline):
    from agents.conversational_assistant import start_chat
    start_chat(context)
"""

import os
import json
import re
import boto3
from pathlib import Path
from botocore.exceptions import ClientError, NoCredentialsError
from agents.mapping_agent import (
    add_user_mapping,
    remove_user_mapping,
    get_user_mappings,
    run_mapping_agent
)
from agents.planning_agent import run_planning_agent, _plan_summary_text
from agents.specification_agent import run_specification_agent
from tools.output_tools import load_output
from context import save_snapshot

import config



# ── system prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are OnboardIQ Assistant, an expert in enterprise data migration and onboarding.

You have access to the full pipeline context: entity catalog, data quality report,
field mappings, and migration planning data. The user may:

1. Ask questions about any pipeline output (quality issues, entities, relationships, mappings).
2. Manually confirm, override, or add a field mapping using natural language.
3. Ask you to remove a mapping they previously added.

MAPPING DETECTION — When the user clearly states a mapping, extract:
  source_entity, source_field, target_entity, target_field, transformation (optional)

Mapping phrases to watch for:
  "map [source_field] to [target_field]"
  "map [entity].[field] to [entity].[field]"
  "[source_field] should map to [target_field]"
  "override [source_field] → [target_field]"
  "use [source_field] as [target_field]"
  "remove mapping for [source_field]"

When you detect a mapping intent, respond with this EXACT JSON block embedded in your reply:
  <<MAPPING_ACTION>>
  {
    "action": "add",
    "source_entity": "Assets",
    "source_field": "asset_no",
    "target_entity": "Asset",
    "target_field": "asset_id",
    "transformation": "uppercase(trim(asset_no))",
    "note": "user confirmed"
  }
  <</MAPPING_ACTION>>

For remove:
  <<MAPPING_ACTION>>
  {"action": "remove", "source_entity": "Assets", "source_field": "asset_no"}
  <</MAPPING_ACTION>>

Then explain what you did in plain English after the JSON block.

IMPORTANT:
- Only emit <<MAPPING_ACTION>> when you are confident the user intends a mapping change.
- For questions/analysis, respond normally without the JSON block.
- Always be concise and specific. Reference actual field names and entity names from the context.
- If asked about the 10 expected user interactions (Bronze-Silver-Gold pipelines, confidence scores,
  data quality issues, etc.) answer using the loaded context data.
"""


# ── context summariser ────────────────────────────────────────────────────────

def _build_context_summary(context: dict) -> str:
    """
    Creates a compact text summary of all pipeline outputs to include
    in every Groq call. Keeps the prompt lean but informative.
    """
    lines = ["=== PIPELINE CONTEXT ===\n"]

    # Entity catalog
    catalog = context.get("entity_catalog", {})
    entities = catalog.get("entities", [])
    if entities:
        lines.append("ENTITIES:")
        for e in entities:
            pk   = e.get("primary_key", "?")
            flds = [f.get("name") for f in e.get("fields", [])]
            rels = [f"{r['from_field']}→{r['to_entity']}.{r['to_field']}"
                    for r in e.get("relationships", [])]
            lines.append(f"  {e['entity_name']} | PK:{pk} | Fields:{flds}")
            if rels:
                lines.append(f"    Relationships: {rels}")

    # Quality report summary
    qr = context.get("quality_report", {})
    summary = qr.get("profile_summary", {})
    if summary:
        lines.append(f"\nQUALITY REPORT:")
        lines.append(f"  Overall completeness : {summary.get('overall_data_completeness', '?')}%")
        lines.append(f"  Total records        : {summary.get('total_records_analyzed', '?')}")
        eq = qr.get("entity_quality", {})
        for ent_name, eq_data in eq.items():
            dups    = eq_data.get("duplicate_records_count", 0)
            orphans = eq_data.get("orphan_records_count", 0)
            comp    = eq_data.get("completeness_score", "?")
            lines.append(f"  {ent_name}: completeness={comp}%, dups={dups}, orphans={orphans}")

    # Current mappings
    mappings = context.get("mappings", {})
    mapping_list = mappings.get("mappings", [])
    if mapping_list:
        lines.append(f"\nCURRENT MAPPINGS:")
        for m in mapping_list:
            src = m.get("source_entity")
            tgt = m.get("target_entity")
            fms = m.get("field_mappings", [])
            lines.append(f"  {src} → {tgt}: {len(fms)} field mappings")
            for fm in fms[:5]:  # show first 5 per entity
                conf   = int(fm.get("confidence_score", 0) * 100)
                origin = " [user]" if fm.get("origin") == "user" else ""
                lines.append(f"    {fm['source_field']} → {fm['target_field']} ({conf}%){origin}")
            if len(fms) > 5:
                lines.append(f"    ... and {len(fms)-5} more")
            unmapped = m.get("unmapped_source_fields", [])
            if unmapped:
                lines.append(f"    Unmapped source fields: {unmapped}")

    # User confirmed mappings
    user_maps = get_user_mappings()
    if user_maps:
        lines.append(f"\nUSER-CONFIRMED MAPPINGS ({len(user_maps)}):")
        for um in user_maps:
            lines.append(
                f"  {um['source_entity']}.{um['source_field']} "
                f"→ {um['target_entity']}.{um['target_field']} "
                f"[{um.get('transformation', 'direct')}]"
            )

    lines.append("\n=== END CONTEXT ===")
    return "\n".join(lines)


# ── mapping action parser ─────────────────────────────────────────────────────

def _extract_mapping_action(reply: str) -> tuple[dict | None, str]:
    """
    Parses <<MAPPING_ACTION>>...<</ MAPPING_ACTION>> block from LLM reply.
    Returns (action_dict, clean_reply_without_block).
    """
    pattern = r"<<MAPPING_ACTION>>(.*?)(?:<<?/MAPPING_ACTION>>?)"
    match   = re.search(pattern, reply, re.DOTALL)
    if not match:
        return None, reply

    try:
        action = json.loads(match.group(1).strip())
    except json.JSONDecodeError:
        return None, reply

    clean_reply = re.sub(pattern, "", reply, flags=re.DOTALL).strip()
    return action, clean_reply


def is_safe_output_path(path) -> bool:
    """Verifies that the target path is strictly within the user's output folder."""
    try:
        abs_target = Path(path).resolve()
        abs_output = Path(config.OUTPUT_DIR).resolve()
        return abs_output in abs_target.parents or abs_target == abs_output
    except Exception:
        return False


def load_target_schema() -> dict:
    """Helper to load user target schema from TARGET_SCHEMA_PATH."""
    schema_path = str(config.TARGET_SCHEMA_PATH)
    if os.path.exists(schema_path):
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def is_modification_questionable(action: dict, context: dict) -> list[str]:
    """
    Analyzes proposed mapping modifications to check if they are questionable.
    Questionable criteria:
      1. Action is 'remove' (destructive).
      2. Target entity does not exist in target schema.
      3. Target field does not exist in target entity.
      4. Type mismatch between source field and target field.
    Returns a list of reasons if questionable, or an empty list if not.
    """
    reasons = []
    act = action.get("action", "add")
    
    if act == "remove":
        reasons.append("Removing an existing mapping is destructive and may leave target fields unmapped.")
        return reasons
        
    source_entity = action.get("source_entity", "")
    source_field = action.get("source_field", "")
    target_entity = action.get("target_entity", "")
    target_field = action.get("target_field", "")
    
    # Load target schema
    target_schema = load_target_schema()
    if not target_schema:
        return reasons
        
    # Check target entity
    if target_entity not in target_schema:
        reasons.append(f"Target entity '{target_entity}' does not exist in the target schema.")
        return reasons
        
    # Check target field
    entity_fields = target_schema[target_entity]
    if target_field not in entity_fields:
        reasons.append(f"Target field '{target_field}' does not exist in target entity '{target_entity}'.")
        return reasons
        
    # Check type mismatch
    source_type = None
    entities = context.get("entity_catalog", {}).get("entities", [])
    for e in entities:
        if e.get("entity_name") == source_entity:
            for f in e.get("fields", []):
                if f.get("name") == source_field:
                    source_type = f.get("dtype")
                    break
            break
            
    target_info = entity_fields[target_field]
    target_type = target_info.get("type")
    
    if source_type and target_type:
        src_norm = "string" if source_type.lower() in ("str", "string", "text") else source_type.lower()
        tgt_norm = "string" if target_type.lower() in ("str", "string", "text") else target_type.lower()
        if src_norm != tgt_norm:
            reasons.append(f"Type mismatch: source field '{source_field}' has type '{source_type}', but target field '{target_field}' expects type '{target_type}'.")
            
    return reasons


def check_pending_confirmation(user_input: str, context: dict, verbose: bool = True) -> str | None:
    """
    Checks if there is a pending questionable mapping action that needs confirmation.
    If the user input matches a confirmation (e.g. 'yes'), advances the confirmation state.
    Returns the response message if handled, or None if the normal LLM flow should run.
    """
    pending_path = Path(config.OUTPUT_DIR) / "pending_mapping_action.json"
    if not pending_path.exists():
        return None
        
    confirm_words = {"yes", "y", "confirm", "sure", "proceed"}
    cleaned_input = user_input.strip().lower().rstrip('.!')
    
    if cleaned_input not in confirm_words:
        # If user typed something else, they aborted/ignored the confirmation.
        try:
            pending_path.unlink()
        except Exception:
            pass
        return None
        
    try:
        with open(pending_path, "r", encoding="utf-8") as f:
            pending = json.load(f)
    except Exception:
        return None
        
    confirmations = pending.get("confirmations_received", 0)
    action = pending.get("action")
    
    if not action:
        try:
            pending_path.unlink()
        except Exception:
            pass
        return None
        
    if confirmations == 1:
        # Increment to 2
        pending["confirmations_received"] = 2
        try:
            with open(pending_path, "w", encoding="utf-8") as f:
                json.dump(pending, f, indent=2)
        except Exception as e:
            return f"Error updating confirmation: {e}"
        return "⚠️  [CONFIRMATION 2/2] Please confirm once more (reply 'yes' or 'confirm' again) to apply the mapping."
        
    elif confirmations == 2:
        # Actually execute
        try:
            pending_path.unlink()
        except Exception:
            pass
        # Perform action
        status_msg = _handle_mapping_action(action, context, verbose)
        return status_msg
        
    return None


def _extract_and_process_mapping_action(reply: str, context: dict, verbose: bool = True) -> tuple[str, str]:
    """
    Extracts mapping action from LLM reply.
    If questionable, prompts for the first confirmation and saves to pending file.
    Otherwise, handles it immediately.
    Returns (clean_reply, status_msg).
    """
    action, clean_reply = _extract_mapping_action(reply)
    if not action:
        return clean_reply, ""
        
    reasons = is_modification_questionable(action, context)
    if reasons:
        # Save to pending file
        pending_path = Path(config.OUTPUT_DIR) / "pending_mapping_action.json"
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)
        pending_data = {
            "action": action,
            "confirmations_received": 1
        }
        try:
            with open(pending_path, "w", encoding="utf-8") as f:
                json.dump(pending_data, f, indent=2)
        except Exception as e:
            return clean_reply, f"Error saving pending action: {e}"
            
        status_msg = "\n\n⚠️  [CONFIRMATION 1/2] The proposed mapping change has the following questionable aspects:\n" + \
                     "\n".join(f"  - {r}" for r in reasons) + \
                     "\n\nAre you sure you want to apply this change? Please reply with 'yes' or 'confirm' to proceed."
        return clean_reply, status_msg
        
    # Not questionable, execute immediately
    status_msg = _handle_mapping_action(action, context, verbose)
    return clean_reply, status_msg


def _handle_mapping_action(action: dict, context: dict, verbose: bool) -> str:
    """Execute the mapping action and return a status message."""
    act = action.get("action", "add")
    schema_keys = {"source_files", "entity_catalog", "file_registry", "quality_report", "mappings", "specification", "readiness", "plan"}

    # Strict path permission checks: only allow modifications inside the user's isolated outputs folder
    target_paths = [
        str(config.MIGRATION_SPEC_PATH),
        os.path.join(config.OUTPUT_DIR, "user_mappings.json"),
        os.path.join(config.OUTPUT_DIR, "mapping_document.json"),
        os.path.join(config.OUTPUT_DIR, "context_snapshot.json")
    ]
    for p in target_paths:
        if not is_safe_output_path(p):
            raise PermissionError(f"Access denied: Modification of path '{p}' outside of user output directory is forbidden.")

    if act == "add":
        entry = add_user_mapping(
            source_entity  = action.get("source_entity", ""),
            source_field   = action.get("source_field", ""),
            target_entity  = action.get("target_entity", ""),
            target_field   = action.get("target_field", ""),
            transformation = action.get("transformation", "direct"),
            note           = action.get("note", "")
        )
        # Re-run mapping agent to merge this into the mapping document
        run_mapping_agent(context, verbose=False)
        
        # Remove cached specification to force rebuild
        spec_path = str(config.MIGRATION_SPEC_PATH)
        if os.path.exists(spec_path):
            try:
                os.remove(spec_path)
            except Exception:
                pass
        
        # Re-run specification agent to update data contracts based on new mappings
        run_specification_agent(context, verbose=False)
        
        # Sanitize context before saving to ensure schema/keys are strictly preserved
        for k in list(context.keys()):
            if k not in schema_keys:
                del context[k]
        save_snapshot(context)

        return (
            f"\n✅ Mapping saved and specification updated: "
            f"{entry['source_entity']}.{entry['source_field']} -> "
            f"{entry['target_entity']}.{entry['target_field']} "
            f"[{entry['transformation']}]\n"
            f"   mapping_document.json, migration_spec.json, and context_snapshot.json have been updated."
        )

    elif act == "remove":
        removed = remove_user_mapping(
            source_entity = action.get("source_entity", ""),
            source_field  = action.get("source_field", "")
        )
        if removed:
            run_mapping_agent(context, verbose=False)
            
            # Remove cached specification to force rebuild
            spec_path = str(config.MIGRATION_SPEC_PATH)
            if os.path.exists(spec_path):
                try:
                    os.remove(spec_path)
                except Exception:
                    pass
            
            # Re-run specification agent to update data contracts based on new mappings
            run_specification_agent(context, verbose=False)
            
            # Sanitize context before saving to ensure schema/keys are strictly preserved
            for k in list(context.keys()):
                if k not in schema_keys:
                    del context[k]
            save_snapshot(context)

            return (
                f"\n🗑️  Mapping removed and specification updated: "
                f"{action['source_entity']}.{action['source_field']}\n"
                f"   mapping_document.json, migration_spec.json, and context_snapshot.json have been updated."
            )
        else:
            return f"\n⚠️  No user-confirmed mapping found for {action.get('source_entity')}.{action.get('source_field')}."

    return ""


def _to_ascii(text: str) -> str:
    """Replaces common non-ASCII characters and emojis with ASCII equivalents to prevent Windows console crashes."""
    if not text:
        return ""
    replacements = {
        "→": "->",
        "✅": "[OK]",
        "🗑️": "[REMOVED]",
        "🗑": "[REMOVED]",
        "⚠️": "[WARNING]",
        "✔": "[OK]",
        "❌": "[ERROR]",
        "•": "*",
        "—": "-",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.encode("ascii", errors="replace").decode("ascii")


# ── main chat loop ────────────────────────────────────────────────────────────

def start_chat(context: dict, verbose: bool = True):
    """
    Launches the interactive chat session.
    Blocks until the user types 'exit' or 'quit'.
    """
    print("\n" + "=" * 60)
    print("  ONBOARDIQ CONVERSATIONAL ASSISTANT")
    print("=" * 60)
    print("  Ask anything about your onboarding pipeline.")
    print("  You can also map fields: 'map asset_no to asset_id'")
    print("  Type 'show plan' to print the current saved plan.")
    print("  Type 'review plan' to review and approve the onboarding plan.")
    print("  Type 'show mappings' to see current mappings.")
    print("  Type 'exit' to quit.\n")

    # ── failsafe mechanism ───────────────────────────────────────────────────
    schema_keys = {"source_files", "entity_catalog", "file_registry", "quality_report", "mappings", "specification", "readiness", "plan"}
    snapshot_path = str(config.CONTEXT_SNAPSHOT_PATH)
    if not context or not context.get("entity_catalog"):
        if os.path.exists(snapshot_path):
            if verbose:
                print(f"  [Failsafe] Context is empty. Attempting recovery from {snapshot_path}...")
            try:
                with open(snapshot_path, "r", encoding="utf-8") as f:
                    restored = json.load(f)
                    for k in schema_keys:
                        if k in restored:
                            context[k] = restored[k]
                if verbose:
                    print("  [Failsafe] Recovery successful. Loaded context snapshot from disk.")
            except Exception as e:
                if verbose:
                    print(f"  [Failsafe] Failed to load snapshot: {e}")
        else:
            print("\n  ⚠️  [Failsafe WARNING] No onboarding pipeline context found on disk or in memory.")
            print("  Please run the pipeline first using 'python main.py run'. Some features may not work.\n")

    aws_region       = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id         = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    history          = []           # full conversation history
    context_summary  = _build_context_summary(context)

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Assistant] Session ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in {"exit", "quit", "bye"}:
            print("[Assistant] Goodbye! Your mappings have been saved.")
            break

        # Check for pending confirmations
        conf_response = check_pending_confirmation(user_input, context, verbose=verbose)
        if conf_response is not None:
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": conf_response})
            print(_to_ascii(f"\nAssistant: {conf_response}"))
            print()
            continue

        # Shortcut: show current mappings
        if user_input.lower() in {"show mappings", "list mappings", "mappings"}:
            user_maps = get_user_mappings()
            md        = context.get("mappings", {}).get("mappings", [])
            print("\n--- Current Mappings ---")
            for m in md:
                print(_to_ascii(f"  {m['source_entity']} → {m['target_entity']}"))
                for fm in m.get("field_mappings", []):
                    orig = " [user]" if fm.get("origin") == "user" else ""
                    print(_to_ascii(f"    {fm['source_field']:20s} → {fm['target_field']:20s} ({int(fm['confidence_score']*100)}%){orig}"))
            print(f"\n  User-confirmed: {len(user_maps)}")
            print("------------------------\n")
            continue

        if user_input.lower() in {"show plan", "plan", "view plan"}:
            plan = context.get("plan") or load_output("onboarding_plan.json")
            if not plan or "error" in plan:
                print("\n[Assistant] No saved onboarding plan found yet.\n")
            else:
                print("\n" + _to_ascii(_plan_summary_text(plan)) + "\n")
            continue

        if user_input.lower() in {"review plan", "plan review", "review onboarding plan"}:
            print("\n[Assistant] Starting onboarding plan review loop...")
            run_planning_agent(context, verbose=verbose, interactive_review=True)
            print("[Assistant] Plan review complete. You can continue chatting or type 'exit'.\n")
            continue

        # Add user message to history
        history.append({"role": "user", "content": user_input})

        # Rebuild context summary every turn (mappings may have changed)
        context_summary = _build_context_summary(context)

        # Build payload: system + messages
        system_content = SYSTEM_PROMPT + "\n\n" + context_summary
        
        # Failsafe LLM directive
        if not context.get("entity_catalog"):
            system_content += "\n\nFAILSAFE NOTICE: The onboarding pipeline context is currently empty. " \
                              "Please politely inform the user that you don't have schema details yet, " \
                              "and prompt them to run the pipeline first using: 'python main.py run' to analyze their data."

        try:
            client = config.get_bedrock_client()
            
            payload = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "system": system_content,
                "messages": history,
                "temperature": 0.3
            }
            
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(payload),
                contentType="application/json",
                accept="application/json",
            )
            
            body = json.loads(response["body"].read())
            reply = body["content"][0]["text"].strip()
        except Exception as e:
            reply = f"[Error calling {config.get_provider_name()}: {e}]"

        # Parse and execute any mapping action embedded in reply
        status_msg = ""
        try:
            clean_reply, status_msg = _extract_and_process_mapping_action(reply, context, verbose)
        except Exception as mapping_err:
            clean_reply, status_msg = reply, f"\n⚠️ Failed to execute mapping action: {mapping_err}"
            
        # Refresh context summary after mapping change
        context_summary = _build_context_summary(context)

        # Add assistant reply to history
        history.append({"role": "assistant", "content": clean_reply})

        print(_to_ascii(f"\nAssistant: {clean_reply}"))
        if status_msg:
            print(_to_ascii(status_msg))
        print()


# ── standalone entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from dotenv import load_dotenv
    load_dotenv()

    from context import fresh_context
    from tools.output_tools import load_output

    # Load whatever pipeline outputs exist
    ctx = fresh_context([])
    for fname, key in [
        ("entity_catalog.json",   "entity_catalog"),
        ("quality_report.json",   "quality_report"),
        ("mapping_document.json", "mappings"),
    ]:
        result = load_output(fname)
        if "error" not in result:
            ctx[key] = result

    start_chat(ctx)
