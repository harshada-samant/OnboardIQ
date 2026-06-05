"""
planning_agent.py
------------------
Agent 6 — Onboarding Planning Agent

Generates a structured onboarding roadmap from the readiness report and
entity catalog.  Addresses the GAP-03 finding from the gap analysis by
producing Bronze-Silver-Gold (BSG) pipeline output explicitly.

Two-layer design (Python for mechanics, LLM for intelligence):

  LAYER 1 — DETERMINISTIC SILVER WAVE SEQUENCING (pure Python, always runs)
    Builds a dependency-aware entity graph, then sequences entities into Silver waves:
      Wave 1 — Reference / lookup tables (no FK dependencies) → first transformation pass
      Wave 2 — Entities with FKs pointing only to Wave 1 entities
      Wave 3 — Entities with FKs pointing to Wave 1 or Wave 2 entities
      ...repeats until all entities are placed

    Each Silver wave gets:
      - Entity list
      - Combined risk items from readiness_report for those entities
      - Planned CSV outputs for downstream loading

  LAYER 2 — LLM ENRICHMENT (Bedrock, single call)
    Sends the compact Silver wave plan (no raw data) to Bedrock.
    Bedrock enriches each wave with:
      - description          : what this wave achieves
      - migration_approach   : recommended ETL strategy
      - risk_mitigations     : per-wave actionable mitigations

    If Bedrock fails → raw wave plan saved as-is (degraded_mode=True).
    Agent NEVER blocks the pipeline.

  BRONZE-SILVER-GOLD MAPPING (always produced, addresses GAP-03):
    Bronze : all source entities ingested raw, no waves
    Silver : wave-sequenced transformation output as CSV files
    Gold   : load Silver CSVs into the target DB

Output files:
  outputs/onboarding_plan.json   — full machine-readable plan
  outputs/onboarding_plan.md     — human-readable roadmap

Edge cases handled:
  - No readiness report         → uses entity_catalog directly for Silver wave ordering
  - Circular FK dependencies    → detected and broken; circular entities placed last
  - Single entity               → plan with one Silver wave
  - All entities failed         → CRITICAL Silver wave with remediation steps
  - Bedrock failure             → degraded mode, raw plan saved
  - Entity names that differ    → case-insensitive FK resolution
"""

import os
import json
import time
import re
import boto3
from collections import defaultdict, deque
from tools.output_tools import save_output, load_output

import config

MAX_RETRIES = 2
RETRY_DELAY = 3



# ── Bedrock helper ─────────────────────────────────────────────────────────────

def _call_bedrock(prompt, system, label="", max_tokens=3000, temperature=0.0):
    last_error = None
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id   = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

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
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
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


def _parse_json(raw):
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


# ── LAYER 1 — Dependency graph + wave sequencing ──────────────────────────────

def _build_dependency_graph(entities):
    """
    Returns:
      deps   : {entity_name: set of entity_names it depends on (parents)}
      all_names: set of all known entity names (lower-cased for matching)
    """
    name_set = {e["entity_name"].lower() for e in entities}
    deps     = {e["entity_name"]: set() for e in entities}

    for entity in entities:
        for rel in entity.get("relationships", []):
            to_entity = rel.get("to_entity", "")
            # Only add as dependency if the parent is in our upload set
            if to_entity.lower() in name_set and to_entity != entity["entity_name"]:
                deps[entity["entity_name"]].add(to_entity)

    return deps


def _topological_waves(deps):
    """
    Kahn's algorithm for topological sort → produces wave list.
    Each wave = entities whose all dependencies are in earlier waves.

    Circular dependencies are detected: any remaining nodes after
    exhausting Kahn's queue are grouped into a final "circular" wave.
    """
    in_degree  = {node: len(parents) for node, parents in deps.items()}
    dependents = defaultdict(set)  # reverse graph: parent → children
    for node, parents in deps.items():
        for parent in parents:
            dependents[parent].add(node)

    queue  = deque(n for n, d in in_degree.items() if d == 0)
    waves  = []
    placed = set()

    while queue:
        # All nodes currently at zero in-degree go into one wave
        wave_nodes = list(queue)
        queue.clear()
        waves.append(wave_nodes)
        placed.update(wave_nodes)

        for node in wave_nodes:
            for child in dependents[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    # Detect circular dependency remainders
    circular = [n for n in deps if n not in placed]
    if circular:
        waves.append(circular)   # placed last

    return waves, bool(circular)


def _collect_entity_risks(entity_name, risk_register):
    """Returns risk items relevant to this entity from the risk register."""
    return [r for r in risk_register
            if r.get("entity", "").lower() in (entity_name.lower(), "mapping",
                                               "data quality", "specification", "discovery")]


def _slugify(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _silver_csv_files(wave_number, wave_entities):
    from pathlib import Path
    wave_dir = Path(config.OUTPUT_DIR) / "silver" / f"wave_{wave_number:02d}"
    return [str(wave_dir / f"{_slugify(entity)}.csv") for entity in wave_entities]



def _wave_row_count(wave_entities, quality_report):
    entity_quality = (quality_report or {}).get("entity_quality", {})
    row_count_map = {
        str(name).lower(): int(info.get("total_rows", 0) or 0)
        for name, info in entity_quality.items()
        if isinstance(info, dict)
    }
    return sum(row_count_map.get(entity.lower(), 0) for entity in wave_entities)


def _wave_uses_sql_sources(wave_entities, entity_catalog, file_registry):
    entities = {e.get("entity_name", "").lower(): e for e in (entity_catalog or {}).get("entities", [])}
    registry_map = {
        str(reg.get("logical_table", "")).lower(): reg
        for reg in (file_registry or [])
        if isinstance(reg, dict)
    }

    for entity_name in wave_entities:
        entity = entities.get(entity_name.lower(), {})
        source_file = str(entity.get("source_file", "") or "").lower()
        if source_file.endswith(".sql"):
            return True

        reg = registry_map.get(entity_name.lower())
        if reg:
            for sf in reg.get("source_files", []):
                file_name = str(sf.get("file_name", "") or "").lower()
                if file_name.endswith(".sql"):
                    return True

    return False


def _recommend_tool_stack(wave_entities, quality_report, entity_catalog, file_registry):
    total_rows = _wave_row_count(wave_entities, quality_report)
    uses_sql = _wave_uses_sql_sources(wave_entities, entity_catalog, file_registry)
    engine = "PySpark" if total_rows > 100_000 else "Pandas"
    stack = ["DuckDB"] if uses_sql else []
    stack.append(engine)
    return {
        "tool_stack": stack,
        "total_rows": total_rows,
        "source_mode": "sql" if uses_sql else "file",
    }


def _normalize_plan(plan, entities, entity_catalog, quality_report, file_registry):
    wave_plan = plan.get("waves", []) if isinstance(plan, dict) else []
    normalized_waves = []
    for wave in wave_plan:
        if not isinstance(wave, dict):
            continue
        wave_number = wave.get("wave_number")
        wave_entities = wave.get("entities", [])
        if not isinstance(wave_number, int):
            try:
                wave_number = int(wave_number)
            except Exception:
                wave_number = len(normalized_waves) + 1

        rec = _recommend_tool_stack(wave_entities, quality_report, entity_catalog, file_registry)
        normalized_wave = dict(wave)
        normalized_wave.setdefault("csv_files", _silver_csv_files(wave_number, wave_entities))
        normalized_wave["tool_stack"] = rec["tool_stack"]
        normalized_wave["total_rows"] = rec["total_rows"]
        normalized_wave["source_mode"] = rec["source_mode"]
        normalized_waves.append(normalized_wave)

    plan = dict(plan or {})
    plan["waves"] = normalized_waves
    plan["silver_waves"] = normalized_waves
    plan["total_waves"] = len(normalized_waves)
    plan["bronze_silver_gold"] = _build_bsg_mapping(entities, normalized_waves)
    return plan


def _plan_summary_text(plan):
    lines = []
    lines.append("ONBOARDING PLAN SUMMARY")
    lines.append(f"Readiness Score: {plan.get('readiness_score', 'N/A')}")
    lines.append(f"Silver Waves: {len(plan.get('waves', []))}")

    bsg = plan.get("bronze_silver_gold", {})
    bronze = bsg.get("Bronze", {})
    silver = bsg.get("Silver", {})
    gold = bsg.get("Gold", {})

    lines.append("")
    lines.append("Bronze")
    lines.append(f"  Entities: {', '.join(bronze.get('entities', [])) or 'None'}")
    if bronze.get("source_entities"):
        lines.append("  Raw ingest items:")
        for item in bronze["source_entities"]:
            lines.append(f"    - {item['entity_name']} ({item.get('status', 'RAW')})")

    lines.append("")
    lines.append("Silver")
    for wave in silver.get("waves", []):
        lines.append(f"  Wave {wave.get('wave_number')}: {', '.join(wave.get('entities', [])) or 'None'}")
        lines.append(f"    Rows: {wave.get('total_rows', 0)}")
        lines.append(f"    Tool stack: {', '.join(wave.get('tool_stack', [])) or 'None'}")
        lines.append(f"    CSV files: {', '.join(wave.get('csv_files', [])) or 'None'}")

    lines.append("")
    lines.append("Gold")
    for load in gold.get("loads", []):
        lines.append(f"  Load wave {load.get('wave_number')}: {', '.join(load.get('target_entities', [])) or 'None'}")
        lines.append(f"    Source CSVs: {', '.join(load.get('source_csv_files', [])) or 'None'}")
        lines.append(f"    Target: {load.get('load_target', 'target_db')}")
        lines.append(f"    Strategy: {load.get('load_strategy', '')}")

    return "\n".join(lines)


def _print_plan_summary(plan):
    print("\n" + _plan_summary_text(plan) + "\n")


def _save_final_plan(plan, output_dir, context):
    save_output(plan, "onboarding_plan.json")
    context["plan"] = plan
    _generate_markdown(plan, os.path.join(output_dir, "onboarding_plan.md"))


def _regenerate_plan_with_feedback(plan, feedback, entities, entity_catalog, quality_report, file_registry, verbose):
    prompt = f"""
Revise this onboarding plan according to the user feedback.

USER FEEDBACK:
{feedback}

CURRENT PLAN:
{json.dumps(plan, indent=2)}
"""
    try:
        raw = _call_bedrock(prompt, PLANNING_REGEN_SYSTEM, label="PlanningAgent-Regenerate")
        result = _parse_json(raw)
        revised_plan = result.get("plan", result) if isinstance(result, dict) else result
        if not isinstance(revised_plan, dict):
            raise ValueError("Bedrock did not return a plan object.")
        return _normalize_plan(revised_plan, entities, entity_catalog, quality_report, file_registry)
    except Exception as e:
        if verbose:
            print(f"  ! Plan regeneration failed: {e}. Keeping current plan.")
        return plan


def _review_plan_with_user(plan, context, entities, entity_catalog, quality_report, file_registry, verbose):
    while True:
        _print_plan_summary(plan)
        try:
            approval = input("Approve this plan? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Review cancelled. Plan not saved.")
            return plan, False

        if approval in {"y", "yes"}:
            _save_final_plan(plan, config.OUTPUT_DIR, context)
            return plan, True

        if approval not in {"n", "no"}:
            print("  Please answer with y or n.")
            continue

        try:
            feedback = input("Enter feedback for regeneration: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Review cancelled. Plan not saved.")
            return plan, False

        if not feedback:
            print("  Feedback is required to regenerate the plan.")
            continue

        if verbose:
            print("  Regenerating plan with Bedrock using your feedback...")
        plan = _regenerate_plan_with_feedback(plan, feedback, entities, entity_catalog, quality_report, file_registry, verbose)


def _build_bsg_mapping(entities, wave_plan):
    """
    Maps the raw ingest inventory, Silver transformation waves, and Gold load jobs.

    Always produced — addresses GAP-03.
    """
    bsg = {
        "Bronze": {
            "description": "Raw ingest layer — all source entities are captured as-is with no wave sequencing.",
            "entities": [e["entity_name"] for e in entities],
            "source_entities": [
                {"entity_name": e["entity_name"], "status": e.get("status", "RAW")}
                for e in entities
            ],
        },
        "Silver": {
            "description": "Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.",
            "waves": [],
            "entities": [],
            "csv_files": [],
        },
        "Gold": {
            "description": "Target load layer — Silver CSV outputs are loaded into the target database.",
            "loads": [],
            "target_entities": [],
            "source_csv_files": [],
        },
    }

    for w in wave_plan:
        wn = w["wave_number"]
        csv_files = w.get("csv_files") or _silver_csv_files(wn, w["entities"])

        silver_wave = {
            "wave_number": wn,
            "entities": w["entities"],
            "csv_files": csv_files,
            "tool_stack": w.get("tool_stack", []),
            "total_rows": w.get("total_rows", 0),
            "source_mode": w.get("source_mode", "file"),
            "risk_items": w.get("risk_items", []),
            "description": w.get("description", ""),
            "migration_approach": w.get("migration_approach", ""),
            "risk_mitigations": w.get("risk_mitigations", []),
        }
        bsg["Silver"]["waves"].append(silver_wave)
        bsg["Silver"]["entities"].extend(w["entities"])
        bsg["Silver"]["csv_files"].extend(csv_files)

        gold_load = {
            "wave_number": wn,
            "source_csv_files": csv_files,
            "target_entities": w["entities"],
            "load_target": "target_db",
            "load_strategy": "bulk load from Silver CSVs",
            "risk_items": w.get("risk_items", []),
        }
        bsg["Gold"]["loads"].append(gold_load)
        bsg["Gold"]["target_entities"].extend(w["entities"])
        bsg["Gold"]["source_csv_files"].extend(csv_files)

    return bsg


# ── LAYER 2 — LLM enrichment ──────────────────────────────────────────────────

PLANNING_SYSTEM = """
You are a senior data migration project manager and architect.

You will receive a structured Silver wave-based onboarding plan. Each wave has:
  - wave_number, entities, risk_items (may be empty)
  - planned CSV outputs for downstream loading

Your job: enrich each wave with three fields:
  1. description        : 1-2 sentences on what this wave achieves and why these entities are grouped together.
  2. migration_approach : the recommended ETL strategy for this wave (e.g., full load to CSV, incremental, CDC, lookup-first).
  3. risk_mitigations   : a list of 2-3 concrete, actionable steps to address the wave's risk_items.

Return ONLY valid JSON. No markdown. No text outside the JSON.

Output structure:
{
  "enriched_waves": [
    {
      "wave_number": 1,
      "description": "...",
      "migration_approach": "...",
      "risk_mitigations": ["...", "..."]
    }
  ]
}

Rules:
- One entry per wave in the same order as input.
- Keep migration_approach to 1 sentence.
- risk_mitigations must be specific to the entities in the wave, not generic advice.
- If risk_items is empty for a wave, still provide a migration_approach and set risk_mitigations to [].
"""


PLANNING_REGEN_SYSTEM = """
You are a senior data migration project manager and architect.

You receive an existing onboarding plan and specific user feedback requesting changes.
Revise the plan to address the feedback while preserving the required output schema.

Return ONLY valid JSON. No markdown. No text outside the JSON.

Required output schema:
{
  "readiness_score": "N/A",
  "total_waves": 3,
  "has_circular_dependencies": false,
  "waves": [
    {
      "wave_number": 1,
      "entities": ["Users"],
      "csv_files": ["outputs/silver/wave_01/users.csv"],
      "tool_stack": ["Pandas"],
      "total_rows": 12345,
      "source_mode": "file",
      "risk_items": [],
      "description": "",
      "migration_approach": "",
      "risk_mitigations": []
    }
  ],
  "silver_waves": [],
  "bronze_silver_gold": {},
  "degraded_mode": false
}

Rules:
- Keep Bronze as raw source inventory with no waves.
- Keep Silver as dependency-aware transformation waves that emit CSV files.
- Keep Gold as DB load jobs consuming the Silver CSVs.
- Preserve the user-approved structural intent unless the feedback explicitly requests a change.
- Do not invent unsupported fields.
- Return the whole revised plan object, not a wrapper.
"""


def _enrich_waves_with_llm(wave_plan, verbose):
    if not wave_plan:
        return wave_plan

    compact = [
        {
            "wave_number":  w["wave_number"],
            "entities":     w["entities"],
            "risk_items":   [{k: v for k, v in r.items() if k in ("severity", "entity", "title")}
                             for r in w.get("risk_items", [])],
        }
        for w in wave_plan
    ]

    prompt = f"Enrich the following wave plan with description, migration_approach, and risk_mitigations.\n\n{json.dumps(compact, indent=2)}"

    try:
        raw      = _call_bedrock(prompt, PLANNING_SYSTEM, label="PlanningAgent")
        result   = _parse_json(raw)
        enriched = result.get("enriched_waves", [])

        if len(enriched) != len(wave_plan):
            if verbose:
                print(f"  ! LLM returned {len(enriched)} waves vs {len(wave_plan)} — using raw plan.")
            return wave_plan

        # Merge enrichment back into wave plan
        enriched_map = {e["wave_number"]: e for e in enriched}
        for w in wave_plan:
            e = enriched_map.get(w["wave_number"], {})
            w["description"]        = e.get("description", "")
            w["migration_approach"] = e.get("migration_approach", "")
            w["risk_mitigations"]   = e.get("risk_mitigations", [])

        return wave_plan

    except Exception as e:
        if verbose:
            print(f"  ! Wave enrichment failed: {e}. Using raw wave plan.")
        return wave_plan


# ── Markdown generator ─────────────────────────────────────────────────────────

def _generate_markdown(plan, output_path):
    readiness_score = plan.get("readiness_score", "N/A")
    lines = [
        "# Onboarding Plan\n",
        f"**Migration Readiness Score:** {readiness_score}/100\n",
        f"**Silver Waves:** {len(plan['waves'])}\n",
    ]

    if plan.get("has_circular_dependencies"):
        lines.append("> Warning: Circular FK dependencies detected. Affected entities placed in the final Silver wave.\n")

    # BSG summary
    bsg = plan.get("bronze_silver_gold", {})
    if bsg:
        lines.append("\n## Bronze-Silver-Gold Pipeline\n")

        bronze = bsg.get("Bronze", {})
        lines += [
            "### Bronze",
            bronze.get("description", ""),
            f"**Entities:** {', '.join(bronze.get('entities', [])) or '—'}",
        ]
        if bronze.get("source_entities"):
            lines.append("**Raw Ingest Items:**")
            for item in bronze["source_entities"]:
                lines.append(f"- {item['entity_name']} ({item.get('status', 'RAW')})")

        silver = bsg.get("Silver", {})
        lines += ["", "### Silver", silver.get("description", "")]
        for wave in silver.get("waves", []):
            lines.append(f"#### Wave {wave['wave_number']}")
            lines.append(f"**Entities:** {', '.join(wave.get('entities', [])) or '—'}")
            lines.append(f"**CSV Files:** {', '.join(wave.get('csv_files', [])) or '—'}")
            lines.append(f"**Tool Stack:** {', '.join(wave.get('tool_stack', [])) or '—'}")
            lines.append(f"**Wave Rows:** {wave.get('total_rows', 0)}")
            if wave.get("description"):
                lines.append(wave["description"])
            if wave.get("migration_approach"):
                lines.append(f"**Approach:** {wave['migration_approach']}")
            if wave.get("risk_mitigations"):
                lines.append("**Risk Mitigations:**")
                for rm in wave["risk_mitigations"]:
                    lines.append(f"- {rm}")
            if wave.get("risk_items"):
                lines.append(f"**Risks ({len(wave['risk_items'])}):**")
                for r in wave["risk_items"][:5]:
                    lines.append(f"- [{r['severity']}] {r.get('title', '')}")

        gold = bsg.get("Gold", {})
        lines += ["", "### Gold", gold.get("description", "")]
        for load in gold.get("loads", []):
            lines.append(f"#### Load Wave {load['wave_number']}")
            lines.append(f"**Source CSVs:** {', '.join(load.get('source_csv_files', [])) or '—'}")
            lines.append(f"**Target Entities:** {', '.join(load.get('target_entities', [])) or '—'}")
            lines.append(f"**Target:** {load.get('load_target', 'target_db')}")
            lines.append(f"**Strategy:** {load.get('load_strategy', '')}")

    # Silver wave details
    lines.append("\n## Silver Wave Detail\n")
    for w in plan["waves"]:
        lines += [
            f"### Wave {w['wave_number']} — {', '.join(w['entities'])}",
            f"**CSV Files:** {', '.join(w.get('csv_files', [])) or '—'}",
            f"**Tool Stack:** {', '.join(w.get('tool_stack', [])) or '—'}",
            f"**Wave Rows:** {w.get('total_rows', 0)}",
        ]
        if w.get("description"):
            lines.append(f"\n{w['description']}\n")
        if w.get("migration_approach"):
            lines.append(f"**Approach:** {w['migration_approach']}\n")
        if w.get("risk_mitigations"):
            lines.append("**Risk Mitigations:**")
            for rm in w["risk_mitigations"]:
                lines.append(f"- {rm}")
        if w.get("risk_items"):
            lines.append(f"\n**Risks ({len(w['risk_items'])}):**")
            for r in w["risk_items"][:5]:
                lines.append(f"- [{r['severity']}] {r.get('title', '')}")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Main entry point ───────────────────────────────────────────────────────────

def run_planning_agent(context, verbose=True, interactive_review=False):
    """
    Agent 6 — Onboarding Planning Agent.
    Reads: entity_catalog, readiness from context (falls back to disk).
    Writes: context["plan"] + outputs/onboarding_plan.json + .md
    Produces: Silver wave roadmap + Bronze-Silver-Gold pipeline structure.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  ONBOARDING PLANNING AGENT")
        print("=" * 60)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # Load inputs — fall back to disk
    entity_catalog  = context.get("entity_catalog")  or {}
    readiness_report = context.get("readiness")       or {}
    quality_report   = context.get("quality_report")  or {}
    file_registry    = context.get("file_registry")   or []

    for fname, key in [
        ("entity_catalog.json",    "entity_catalog"),
        ("readiness_report.json",  "readiness"),
        ("quality_report.json",     "quality_report"),
    ]:
        ref = entity_catalog if key == "entity_catalog" else readiness_report
        if key == "quality_report":
            ref = quality_report
        if not ref:
            loaded = load_output(fname)
            if "error" not in loaded:
                if key == "entity_catalog":   entity_catalog   = loaded
                elif key == "readiness":      readiness_report = loaded
                elif key == "quality_report": quality_report    = loaded
                if verbose:
                    print(f"  ~ Loaded {fname} from disk.")
            else:
                if verbose:
                    print(f"  ! {fname} not found — planning will proceed with reduced context.")

    entities = entity_catalog.get("entities", [])
    if not entities:
        if verbose:
            print("  x No entities found in catalog. Cannot generate plan.")
        context["plan"] = {"error": "No entities found in entity_catalog."}
        return context

    readiness_score = (readiness_report.get("readiness_score", "N/A")
                       if readiness_report else "N/A")

    plan = context.get("plan") if interactive_review else None
    if not (interactive_review and isinstance(plan, dict) and plan.get("waves")):
        if verbose:
            print(f"\n  Entities to plan : {[e['entity_name'] for e in entities]}")
            print(f"  Readiness score  : {readiness_score}")
            print(f"\n[Layer 1] Building dependency graph and Silver wave sequence...")

        # Layer 1 — deterministic Silver waves
        deps          = _build_dependency_graph(entities)
        waves_names, has_circular = _topological_waves(deps)

        if verbose:
            print(f"  Silver waves detected : {len(waves_names)}")
            if has_circular:
                print("  ! Circular FK dependencies detected — affected entities placed in final Silver wave.")

        risk_register = (readiness_report.get("risk_register", [])
                         if readiness_report else [])

        wave_plan = []
        for i, wave_entities in enumerate(waves_names, start=1):
            risks  = []
            for e in wave_entities:
                risks += [r for r in risk_register
                          if r.get("entity", "").lower() == e.lower()]
            # deduplicate
            seen, u_risks = set(), []
            for r in risks:
                k = r.get("title", "")
                if k not in seen:
                    seen.add(k)
                    u_risks.append(r)

            wave_plan.append({
                "wave_number":       i,
                "entities":          wave_entities,
                "risk_items":        u_risks,
                "csv_files":         _silver_csv_files(i, wave_entities),
                **_recommend_tool_stack(wave_entities, quality_report, entity_catalog, file_registry),
                "description":       "",
                "migration_approach": "",
                "risk_mitigations":  [],
            })

            if verbose:
                stack = wave_plan[-1]["tool_stack"]
                rows = wave_plan[-1]["total_rows"]
                print(f"    Silver Wave {i}: {wave_entities}  |  {rows} row(s)  |  {', '.join(stack)}  |  {len(u_risks)} risk(s)")

        # Layer 2 — LLM enrichment
        degraded = False
        if verbose:
            print(f"\n[Layer 2] Enriching {len(wave_plan)} Silver wave(s) via Bedrock...")
        try:
            wave_plan = _enrich_waves_with_llm(wave_plan, verbose)
        except Exception as e:
            if verbose:
                print(f"  ! Wave enrichment failed: {e}. Continuing degraded.")
            degraded = True

        # BSG mapping
        bsg = _build_bsg_mapping(entities, wave_plan)

        plan = {
            "readiness_score":          readiness_score,
            "total_waves":              len(wave_plan),
            "has_circular_dependencies": has_circular,
            "waves":                    wave_plan,
            "silver_waves":             wave_plan,
            "bronze_silver_gold":       bsg,
            "degraded_mode":            degraded,
        }

    plan = _normalize_plan(plan, entities, entity_catalog, quality_report, file_registry)
    context["plan"] = plan

    if interactive_review:
        plan, approved = _review_plan_with_user(plan, context, entities, entity_catalog, quality_report, file_registry, verbose)
        if not approved:
            return context
    else:
        _save_final_plan(plan, config.OUTPUT_DIR, context)

    bsg = plan.get("bronze_silver_gold", {})

    if verbose:
        print("\n" + "=" * 60)
        print("  ONBOARDING PLANNING COMPLETE")
        print("=" * 60)
        print(f"  Silver Waves     : {len(wave_plan)}")
        print(f"  Readiness Score  : {readiness_score}")
        print("\n  Bronze-Silver-Gold Summary:")
        print(f"    Bronze : {bsg.get('Bronze', {}).get('entities', [])}")
        print(f"    Silver : {len(bsg.get('Silver', {}).get('waves', []))} wave(s)")
        print(f"    Gold   : {len(bsg.get('Gold', {}).get('loads', []))} load(s)")
        print(f"\n  JSON : outputs/onboarding_plan.json")
        print(f"  MD   : outputs/onboarding_plan.md")
        print("=" * 60)

    return context
