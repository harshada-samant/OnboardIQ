"""
readiness_agent.py
-------------------
Agent 5 — Migration Readiness Agent

Two-layer design (Python for mechanics, LLM for intelligence):

  LAYER 1 — DETERMINISTIC SCORING (pure Python, always runs)
    Four sub-scores:
      Data Quality   35% — from quality_report (nulls, dupes, orphans, completeness)
      Mapping Cover  35% — from mapping_document (coverage %, low-confidence, req gaps)
      Spec Complete  20% — from migration_spec (data_type / validation_rule / transform filled)
      Rel Clarity    10% — from entity_catalog (failed tables, unresolved FKs, dup entities)

    Builds a raw risk_items list (CRITICAL/HIGH/MEDIUM/LOW) from numbers alone.

  LAYER 2 — LLM RISK NARRATIVE (Bedrock, single call)
    Sends only the compact risk_items list to Bedrock.
    Bedrock enriches each item with root_cause, impact, action.
    If Bedrock fails → raw items saved as-is (degraded_mode=True).
    Agent NEVER blocks the pipeline.

Edge cases handled:
  - Missing upstream outputs → each sub-score degrades to 0, risk flagged
  - Empty entity list        → score=0, CRITICAL added
  - Zero-field mapping       → coverage=0%, CRITICAL added
  - All checks PASS          → no risks, score=100, clean report
  - Bedrock failure          → degraded mode, raw items saved
  - spec stored as list/dict → both handled
  - Missing null/orphan counts in quality report → treated as 0 (safe default)
"""

import os
import json
import time
import re
import boto3
from tools.output_tools import save_output, load_output

import config

MAX_RETRIES = 2
RETRY_DELAY = 3


WEIGHTS = {
    "data_quality":  0.35,
    "mapping_cover": 0.35,
    "spec_complete": 0.20,
    "rel_clarity":   0.10,
}

SEVERITY_RULES = {
    "CRITICAL": [
        "duplicate PKs > 10",
        "mapping coverage < 70%",
        "entities failed in discovery",
    ],
    "HIGH": [
        "completeness < 90%",
        "duplicate PKs <= 10",
        "orphans > 5",
        "mapping coverage < 85%",
    ],
    "MEDIUM": [
        "confidence score < 70%",
        "unresolved FKs",
        "orphans <= 5",
    ],
    "LOW": [
        "incomplete spec fields (missing data_type, validation_rule, or transformation)",
    ],
}

# ── Bedrock helper ─────────────────────────────────────────────────────────────

def _call_bedrock(prompt, system, label="", max_tokens=2048, temperature=0.0):
    last_error = None
    aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    model_id   = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            client = config.get_bedrock_client()
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


# ── Risk helper ────────────────────────────────────────────────────────────────

def _risk(severity, entity, title, impact="", action=""):
    return {"severity": severity, "entity": entity, "title": title,
            "impact": impact, "action": action}

def _severity_order(item):
    return {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(item.get("severity", "LOW"), 4)


# ── LAYER 1 sub-scorers ────────────────────────────────────────────────────────

def _score_data_quality(quality_report):
    if not quality_report:
        # CRITICAL because the profiling report is missing entirely, so there is no basis to assess
        # data quality and the readiness score would be unreliable.
        return 0.0, [_risk("CRITICAL", "Data Quality", "quality_report is missing",
            "Cannot assess data quality — Profiling Agent output absent.",
            "Re-run Profiling Agent before Readiness assessment.")]

    entity_quality = quality_report.get("entity_quality", {})
    if not entity_quality:
        # CRITICAL because the profiling output exists but contains no entity-level quality data,
        # which means the pipeline has no actual quality measurements to work with.
        return 0.0, [_risk("CRITICAL", "Data Quality", "No entity quality data found",
            "quality_report.entity_quality is empty.",
            "Ensure source files contain data rows.")]

    score      = 100.0
    risk_items = []

    for entity_name, eq in entity_quality.items():
        checks  = eq.get("checks", [])
        fail_ct = sum(1 for c in checks if c.get("status") == "FAIL")
        warn_ct = sum(1 for c in checks if c.get("status") == "WARNING")
        dups    = int(eq.get("duplicate_records_count") or 0)
        orphans = int(eq.get("orphan_records_count") or 0)
        compl   = float(eq.get("completeness_score") or 100.0)

        score -= min(fail_ct * 5, 20)
        score -= min(warn_ct * 2, 10)

        if compl < 90:
            # HIGH because completeness below 90% means the entity is missing enough source data
            # to create migration defects, but it is still a scoped data-quality fix rather than a total failure.
            score -= 10
            risk_items.append(_risk("HIGH", entity_name,
                f"Low data completeness: {compl:.1f}%",
                f"{entity_name} has {100-compl:.1f}% missing values across fields.",
                "Identify mandatory fields with high null rates and cleanse before migration."))

        if dups > 0:
            if dups > 10:
                # CRITICAL because more than 10 duplicate PKs usually means the target load will
                # hit repeated key violations, not just an isolated cleanup item.
                sev = "CRITICAL"
            else:
                # HIGH because duplicate PKs at 10 or fewer are still blocking, but the cleanup
                # is bounded enough to treat as urgent remediation rather than a systemic failure.
                sev = "HIGH"
            score -= 5
            risk_items.append(_risk(sev, entity_name,
                f"{dups} duplicate primary key record(s)",
                f"Duplicate PKs in {entity_name} will cause constraint violations on load.",
                "Deduplicate records or assign surrogate keys before migration."))

        if orphans > 0:
            if orphans > 5:
                # HIGH because more than 5 orphan rows indicates a broader referential-integrity problem
                # that can break the load unless the missing parents are restored or handled first.
                sev = "HIGH"
            else:
                # MEDIUM because 5 or fewer orphans still need attention, but the issue is small enough
                # to correct as a controlled cleanup instead of a major blocking remediation.
                sev = "MEDIUM"
            score -= 5
            risk_items.append(_risk(sev, entity_name,
                f"{orphans} orphan record(s) (broken FK references)",
                f"Records in {entity_name} reference parent IDs that do not exist.",
                "Resolve missing parent records or nullify FK before loading."))

        for chk in checks:
            if chk.get("status") == "FAIL":
                # MEDIUM because an individual failed check is actionable and important, but it is
                # already captured at the field level and does not necessarily imply the entity is blocked.
                risk_items.append(_risk("MEDIUM", entity_name,
                    chk.get("message", "Check failed"),
                    f"Check type {chk.get('check_type')} failed on field '{chk.get('field')}'.",
                    "Review source data for this field and apply appropriate cleansing."))

    return round(max(0.0, min(100.0, score)), 1), risk_items


def _score_mapping_coverage(mapping_doc):
    if not mapping_doc:
        # CRITICAL because there is no mapping document at all, so mapping coverage cannot be measured
        # and the downstream specification/planning stages have nothing to validate against.
        return 0.0, [_risk("CRITICAL", "Mapping", "mapping_document is missing",
            "Cannot assess mapping coverage — Mapping Agent output absent.",
            "Re-run Mapping Agent before Readiness assessment.")]

    mappings = mapping_doc.get("mappings", [])
    if not mappings:
        # CRITICAL because an empty mapping list means the source-to-target translation is absent, which
        # blocks migration readiness rather than just leaving a minor gap.
        return 0.0, [_risk("CRITICAL", "Mapping", "No mappings found in mapping_document",
            "Mapping Agent produced an empty mapping list.",
            "Check entity_catalog and target_schema and re-run Mapping Agent.")]

    total_source = 0
    total_mapped = 0
    risk_items   = []

    for m in mappings:
        entity       = m.get("source_entity", "Unknown")
        field_maps   = m.get("field_mappings", [])
        unmapped_src = m.get("unmapped_source_fields", [])
        unmapped_req = m.get("unmapped_required_target_fields", [])

        total_source += len(field_maps) + len(unmapped_src)
        total_mapped += len(field_maps)

        if unmapped_req:
            # CRITICAL because unmapped required target fields block the migration contract itself;
            # the target schema cannot be satisfied until these mappings exist.
            risk_items.append(_risk("CRITICAL", entity,
                f"{len(unmapped_req)} required target field(s) unmapped: {unmapped_req}",
                "Required fields in target schema have no corresponding source data.",
                "Provide default values, derive from other fields, or clarify with source owner."))

        for fm in field_maps:
            conf   = float(fm.get("confidence_score") or 1.0)
            origin = fm.get("origin", "")
            if conf < 0.70 and origin != "user":
                # MEDIUM because low-confidence mappings are suspicious and should be reviewed,
                # but the mapping exists and can still be corrected without stopping the pipeline.
                risk_items.append(_risk("MEDIUM", entity,
                    f"Low-confidence mapping: {fm.get('source_field')} → {fm.get('target_field')} ({int(conf*100)}%)",
                    "Semantic similarity score below 70% — mapping may be incorrect.",
                    "Manually verify this mapping in the Conversational Assistant."))

    coverage = (total_mapped / total_source * 100) if total_source > 0 else 0.0

    if coverage < 70:
        # CRITICAL because coverage below 70% means too much of the source is unmapped to trust the
        # migration plan; the missing scope is large enough to threaten the project outcome.
        risk_items.insert(0, _risk("CRITICAL", "Mapping",
            f"Overall mapping coverage is only {coverage:.1f}%",
            "More than 30% of source fields are unmapped.",
            "Run AI Mapping Agent with updated target schema or map remaining fields manually."))
    elif coverage < 85:
        # HIGH because coverage below 85% is still materially incomplete and requires focused remediation,
        # but enough mapping exists that the plan can be refined rather than rebuilt.
        risk_items.insert(0, _risk("HIGH", "Mapping",
            f"Mapping coverage {coverage:.1f}% below 85% threshold",
            "A significant portion of source fields are not mapped to any target field.",
            "Review unmapped_source_fields in mapping_document.json."))

    return round(coverage, 1), risk_items


def _score_spec_completeness(specification):
    if not specification:
        # HIGH because the specification artifact is missing, which prevents contract validation but is
        # usually recoverable by regenerating the spec from the mapping and quality inputs.
        return 0.0, [_risk("HIGH", "Specification", "migration_spec is missing",
            "Specification Agent output absent — data contracts not generated.",
            "Re-run Specification Agent.")]

    entity_spec = (specification.get("entity_specification")
                   if isinstance(specification, dict) else None)
    if entity_spec is None:
        entity_spec = specification if isinstance(specification, dict) else {}

    if not entity_spec:
        # HIGH because the specification container exists but has no field records, so the contract is
        # unusable even though the upstream spec step did run.
        return 0.0, [_risk("HIGH", "Specification", "entity_specification is empty",
            "Specification Agent produced no field specifications.",
            "Check mapping_document and quality_report inputs to Spec Agent.")]

    total_fields    = 0
    complete_fields = 0
    risk_items      = []

    for entity_name, fields in entity_spec.items():
        if not isinstance(fields, list):
            continue
        for f in fields:
            total_fields += 1
            missing = [attr for attr in ("data_type", "validation_rule", "transformation")
                       if not f.get(attr)]
            if not missing:
                complete_fields += 1
            else:
                # LOW because missing spec fields weaken the contract, but they do not by themselves
                # block discovery or mapping completion; they are a documentation and completeness gap.
                risk_items.append(_risk("LOW", entity_name,
                    f"Incomplete spec for '{f.get('target_field', '?')}': missing {missing}",
                    "Specification record is missing required contract attributes.",
                    f"Manually fill {missing} for {entity_name}.{f.get('target_field')}."))

    if total_fields == 0:
        # HIGH because no spec fields were produced at all, which means the Specification Agent output
        # is effectively unusable and needs immediate regeneration.
        return 0.0, [_risk("HIGH", "Specification", "No spec fields found",
            "entity_specification contains no field records.",
            "Re-run Specification Agent with valid mapping inputs.")]

    return round((complete_fields / total_fields) * 100, 1), risk_items


def _score_relationship_clarity(entity_catalog):
    if not entity_catalog:
        # HIGH because discovery output is missing, which prevents relationship review, but the source
        # catalog may still be recoverable without treating the whole discovery stage as failed.
        return 0.0, [_risk("HIGH", "Discovery", "entity_catalog is missing",
            "Discovery Agent output absent.", "Re-run Discovery Agent.")]

    entities = entity_catalog.get("entities", [])
    if not entities:
        # CRITICAL because discovery found zero entities, so there is nothing to migrate and the upstream
        # ingestion/discovery stage has effectively failed.
        return 0.0, [_risk("CRITICAL", "Discovery", "No entities found in catalog",
            "Discovery Agent identified zero business entities.",
            "Verify source files contain recognisable business data.")]

    score      = 100.0
    risk_items = []

    failed = [e for e in entities if e.get("status") == "FAILED"]
    if failed:
        score -= len(failed) * 15
        # HIGH because failed discovery entities are serious and need intervention, but the catalog still
        # exists and the rest of the plan may continue once those failures are resolved.
        risk_items.append(_risk("HIGH", "Discovery",
            f"{len(failed)} table(s) failed during discovery: {[e['entity_name'] for e in failed]}",
            f"{config.get_provider_name()} call failed — entity profiles are incomplete.",
            "Delete phase1 checkpoint files for failed tables and re-run Discovery Agent."))

    for entity in entities:
        fk_candidates     = entity.get("fk_candidates", [])
        relationships     = entity.get("relationships", [])
        resolved_fields   = {r["from_field"] for r in relationships}
        unresolved        = [fk["field"] for fk in fk_candidates
                             if fk.get("field") not in resolved_fields]
        if unresolved:
            score -= len(unresolved) * 5
            # MEDIUM because unresolved FKs indicate a relationship gap that needs attention, but the issue
            # is often solvable by adding the missing parent or confirming the relationship is external.
            risk_items.append(_risk("MEDIUM", entity.get("entity_name", "?"),
                f"Unresolved FK candidate(s): {unresolved}",
                "These fields look like foreign keys but no matching parent entity was found.",
                "Upload the referenced parent table or confirm the FK is to an external system."))

    for dup in entity_catalog.get("potential_duplicate_entities", []):
        score -= 10
        # MEDIUM because duplicate-entity candidates are a structural warning that deserves review, but it
        # is still a candidate pair rather than a confirmed migration blocker.
        risk_items.append(_risk("MEDIUM", f"{dup.get('entity_a')} / {dup.get('entity_b')}",
            f"Potential duplicate entities ({dup.get('confidence')} confidence)",
            dup.get("reasoning", ""),
            "Confirm whether these are the same entity and consolidate if so."))

    return round(max(0.0, min(100.0, score)), 1), risk_items


# ── LAYER 2 — LLM risk narrative enrichment ───────────────────────────────────

READINESS_SYSTEM = """
You are a senior data migration risk analyst.

You receive a list of raw risk items identified from a data onboarding pipeline.
Each item has: severity, entity, title, impact (may be empty), action (may be empty).

Your job:
  1. Enrich items with empty or weak impact/action with concise root_cause, impact, action.
  2. Do NOT invent new risk items — only enrich what is provided.
  3. Keep each field under 2 sentences.
  4. Return ONLY valid JSON. No markdown. No text outside JSON.

Output:
{
  "enriched_risks": [
    {
      "severity": "CRITICAL",
      "entity": "Assets",
      "title": "...",
      "root_cause": "...",
      "impact": "...",
      "action": "..."
    }
  ]
}

Preserve original severity and title exactly. Do not reclassify severity.
"""


def _enrich_risks_with_llm(risk_items, verbose):
    if not risk_items:
        return risk_items
    prompt = f"Enrich these migration risk items with root_cause, impact, and action.\n\n{json.dumps(risk_items, indent=2)}"
    try:
        raw      = _call_bedrock(prompt, READINESS_SYSTEM, label="ReadinessAgent")
        result   = _parse_json(raw)
        enriched = result.get("enriched_risks", [])
        if len(enriched) != len(risk_items):
            if verbose:
                print(f"  ! LLM returned {len(enriched)} items vs {len(risk_items)} — using raw risks.")
            return risk_items
        return enriched
    except Exception as e:
        if verbose:
            print(f"  ! Risk enrichment failed: {e}. Using raw risk items.")
        return risk_items


# ── Markdown generator ─────────────────────────────────────────────────────────

def _generate_markdown(report, output_path):
    score = report["readiness_score"]
    grade = report["readiness_grade"]
    sub   = report["sub_scores"]
    risks = report["risk_register"]
    by_sev = {"CRITICAL": [], "HIGH": [], "MEDIUM": [], "LOW": []}
    for r in risks:
        by_sev.setdefault(r["severity"], []).append(r)

    lines = [
        "# Migration Readiness Report\n",
        f"## Overall Score: {score}/100  —  Grade: {grade}\n",
        "### Sub-scores\n",
        "| Dimension | Score | Weight |",
        "|---|---|---|",
        f"| Data Quality        | {sub['data_quality']:.1f}%  | 35% |",
        f"| Mapping Coverage    | {sub['mapping_cover']:.1f}%  | 35% |",
        f"| Spec Completeness   | {sub['spec_complete']:.1f}%  | 20% |",
        f"| Relationship Clarity | {sub['rel_clarity']:.1f}% | 10% |",
        "\n## Risk Register\n",
    ]
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        items = by_sev.get(sev, [])
        if not items:
            continue
        lines.append(f"### {sev} ({len(items)})\n")
        for r in items:
            lines.append(f"**[{r['entity']}]** {r['title']}")
            for attr in ("root_cause", "impact", "action"):
                if r.get(attr):
                    lines.append(f"- {attr.replace('_',' ').title()}: {r[attr]}")
            lines.append("")
    if report.get("degraded_mode"):
        lines.append(f"> Warning: LLM risk enrichment skipped ({config.get_provider_name()} unavailable).")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Main entry point ───────────────────────────────────────────────────────────

def run_readiness_agent(context, verbose=True):
    """
    Agent 5 — Migration Readiness Agent.
    Reads: entity_catalog, quality_report, mappings, specification from context.
    Writes: context["readiness"] + outputs/readiness_report.json + .md
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION READINESS AGENT")
        print("=" * 60)

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # Load inputs — fall back to disk if context keys empty
    entity_catalog = context.get("entity_catalog") or {}
    quality_report = context.get("quality_report") or {}
    mapping_doc    = context.get("mappings")        or {}
    specification  = context.get("specification")   or {}

    for fname, key in [
        ("entity_catalog.json",   "entity_catalog"),
        ("quality_report.json",   "quality_report"),
        ("mapping_document.json", "mappings"),
        ("migration_spec.json",   "specification"),
    ]:
        current = locals()[key.replace("mappings", "mapping_doc")
                              .replace("entity_catalog", "entity_catalog")
                              .replace("quality_report", "quality_report")
                              .replace("specification", "specification")]
        # simpler: use a dict lookup
        refs = {
            "entity_catalog": entity_catalog,
            "quality_report": quality_report,
            "mappings":       mapping_doc,
            "specification":  specification,
        }
        if not refs[key]:
            loaded = load_output(fname)
            if "error" not in loaded:
                if key == "entity_catalog":   entity_catalog = loaded
                elif key == "quality_report": quality_report = loaded
                elif key == "mappings":       mapping_doc    = loaded
                elif key == "specification":  specification  = loaded
                if verbose:
                    print(f"  ~ Loaded {fname} from disk.")
            else:
                if verbose:
                    print(f"  ! {fname} not found — sub-score will degrade.")

    # Layer 1
    if verbose:
        print("\n[Layer 1] Computing deterministic sub-scores...")

    q_score,  q_risks  = _score_data_quality(quality_report)
    m_score,  m_risks  = _score_mapping_coverage(mapping_doc)
    sp_score, sp_risks = _score_spec_completeness(specification)
    r_score,  r_risks  = _score_relationship_clarity(entity_catalog)

    sub_scores = {
        "data_quality":  q_score,
        "mapping_cover": m_score,
        "spec_complete": sp_score,
        "rel_clarity":   r_score,
    }

    if verbose:
        for dim, sc in sub_scores.items():
            print(f"    {dim:22s} : {sc:.1f}%")

    overall = round(sum(WEIGHTS[k] * sub_scores[k] for k in WEIGHTS), 1)
    grade   = ("A" if overall >= 90 else "B" if overall >= 75 else
               "C" if overall >= 60 else "D" if overall >= 40 else "F")

    all_risks = sorted(q_risks + m_risks + sp_risks + r_risks, key=_severity_order)

    if verbose:
        print(f"\n  Preliminary score : {overall}/100  Grade: {grade}")
        counts = {}
        for r in all_risks:
            counts[r["severity"]] = counts.get(r["severity"], 0) + 1
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if counts.get(sev):
                print(f"    {sev:8s}: {counts[sev]} risk(s)")

    # Layer 2
    degraded = False
    if all_risks:
        if verbose:
            print(f"\n[Layer 2] Enriching {len(all_risks)} risk item(s) via {config.get_provider_name()}...")
        try:
            all_risks = _enrich_risks_with_llm(all_risks, verbose)
        except Exception as e:
            if verbose:
                print(f"  ! LLM enrichment failed: {e}. Continuing degraded.")
            degraded = True

    report = {
        "readiness_score": overall,
        "readiness_grade": grade,
        "sub_scores":      sub_scores,
        "risk_register":   all_risks,
        "risk_summary":    {sev: sum(1 for r in all_risks if r["severity"] == sev)
                            for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]},
        "degraded_mode":   degraded,
        "score_weights":   WEIGHTS,
    }

    save_output(report, "readiness_report.json")
    context["readiness"] = report
    _generate_markdown(report, str(config.READINESS_REPORT_MD_PATH))

    if verbose:
        print("\n" + "=" * 60)
        print("  MIGRATION READINESS COMPLETE")
        print("=" * 60)
        print(f"  Overall Score : {overall}/100  (Grade {grade})")
        print(f"  Risk Items    : {len(all_risks)}")
        crit = report["risk_summary"]["CRITICAL"]
        if crit:
            print(f"  !! {crit} CRITICAL risk(s) — resolve before migration.")
        print(f"  JSON : outputs/readiness_report.json")
        print(f"  MD   : outputs/readiness_report.md")
        print("=" * 60)

    return context
