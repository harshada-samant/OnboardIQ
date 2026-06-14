"""
payload_builder.py
-------------------
Reads all uploaded files, detects duplicate schemas,
builds a file registry, and returns one payload entry
per LOGICAL TABLE (not per physical file).

STEPS:
  1. Read all files → raw entries (one per file / per table in SQL)
  2. Build schema fingerprint for each entry
  3. Group entries by fingerprint → detect duplicates
  4. Assign logical table name per group
  5. Save file_registry.json → maps physical files to logical tables
  6. Return one merged payload entry per logical table

FILE REGISTRY (outputs/file_registry.json):
  Downstream agents use this to know:
    - which physical files belong to which logical table
    - which phase1 checkpoint covers that logical table
    - total row count across all source files
    - whether duplicate schemas were detected

DUPLICATE HANDLING:
  Same schema, multiple CSVs  → merge rows (split data files)
  Same schema, CSV + SQL      → keep CSV for data, SQL for schema reference
  Same schema, multiple SQLs  → keep first, skip rest (duplicate exports)
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime
from collections import defaultdict
import re

import sqlglot
import sqlglot.expressions as exp

import config


def _load_dataframe(file_ref: str, context: dict):
    """Returns (df, error_string). Never raises. df is None on failure."""
    storage = context.get('_storage')
    ext = os.path.splitext(file_ref)[1].lower()
    try:
        if ext == '.csv':
            buf = storage.read_file(file_ref)
            if buf is None:
                return None, f'Failed to read {file_ref}'
            return pd.read_csv(buf, dtype=str, keep_default_na=False), None
        elif ext == '.json':
            buf = storage.read_file(file_ref)
            if buf is None:
                return None, f'Failed to read {file_ref}'
            return pd.read_json(buf, dtype=str), None
        elif ext == '.sql':
            return None, None
        return None, f'Unsupported extension: {ext}'
    except Exception as e:
        return None, str(e)


def _load_sql_text(file_ref: str, context: dict) -> str | None:
    """Returns SQL file content as string. Returns None on failure. Never raises."""
    storage = context.get('_storage')
    if storage:
        return storage.read_text_file(file_ref)
    return None


def _detect_dialect(sql_text: str) -> str:
    text_lower = sql_text.lower()
    if re.search(r'\w+\.\w+\.\w+', sql_text) or "struct<" in text_lower or "array<" in text_lower:
        return "bigquery"
    if any(kw in text_lower for kw in ["variant", " object ", "$$"]):
        return "snowflake"
    if re.search(r'\[\w+\]', sql_text) or any(kw in text_lower for kw in ["nvarchar", "uniqueidentifier", "getdate()"]):
        return "tsql"
    if any(kw in text_lower for kw in ["varchar2", "number(", "sysdate"]):
        return "oracle"
    if any(kw in text_lower for kw in ["serial", "bigserial", "::text", "::integer"]):
        return "postgres"
    if "`" in sql_text or "engine=" in text_lower or "auto_increment" in text_lower:
        return "mysql"
    return "mysql"


def _parse_single_create(statement, dialect: str) -> dict:
    table_node = statement.find(exp.Table)
    if not table_node:
        return None
    table_name = table_node.name

    pk_cols = set()
    for col_def in statement.find_all(exp.ColumnDef):
        for constraint in col_def.find_all(exp.ColumnConstraint):
            if isinstance(constraint.args.get("kind"), exp.PrimaryKeyColumnConstraint):
                pk_cols.add(col_def.name)

    for pk in statement.find_all(exp.PrimaryKey):
        for ident in pk.find_all(exp.Identifier):
            pk_cols.add(ident.name)

    fk_map = {}
    for fk in statement.find_all(exp.ForeignKey):
        fk_fields = [i.this for i in fk.args.get("expressions", [])]
        ref = fk.args.get("reference")
        if ref and fk_fields:
            ref_schema = ref.args.get("this")
            if ref_schema:
                ref_table = ref_schema.args.get("this")
                ref_fields = ref_schema.args.get("expressions", [])
                ref_table_name = ref_table.name if ref_table else None
                ref_field_name = ref_fields[0].this if ref_fields else None
                for field in fk_fields:
                    fk_map[field] = {
                        "table": ref_table_name,
                        "field": ref_field_name
                    }

    fields = []
    for col_def in statement.find_all(exp.ColumnDef):
        col_name = col_def.name
        dtype = str(col_def.args.get("kind", "UNKNOWN"))
        not_null = any(
            isinstance(c.args.get("kind"), exp.NotNullColumnConstraint)
            for c in col_def.find_all(exp.ColumnConstraint)
        )
        if col_name in pk_cols:
            not_null = True

        default_constraint = col_def.find(exp.DefaultColumnConstraint)
        default_val = str(default_constraint.this) if default_constraint else None

        fields.append({
            "name": col_name,
            "dtype": dtype,
            "null_pct": None,
            "unique_count": None,
            "samples": [],
            "nullable": not not_null,
            "is_primary_key": col_name in pk_cols,
            "is_foreign_key": col_name in fk_map,
            "fk_references": fk_map.get(col_name),
            "default": default_val
        })

    return {
        "table_name": table_name,
        "fields": fields,
        "pk_cols": list(pk_cols),
        "fk_map": fk_map
    }


def _parse_sql_text(file_ref: str, sql_text: str) -> list:
    if not sql_text or not sql_text.strip():
        return [{"error": f"Empty file: {file_ref}"}]

    dialect = _detect_dialect(sql_text)
    base_name = os.path.basename(file_ref)

    try:
        statements = sqlglot.parse(sql_text, dialect=dialect)
    except Exception as e:
        return [{"error": f"sqlglot parse failed on {file_ref}: {e}"}]

    results = []
    for statement in statements:
        if not isinstance(statement, exp.Create):
            continue
        if statement.args.get("kind") != "TABLE":
            continue

        parsed = _parse_single_create(statement, dialect)
        if not parsed:
            continue

        results.append({
            "file_name": f"{parsed['table_name']}__from__{base_name}",
            "source_type": "sql_ddl",
            "dialect": dialect,
            "row_count": None,
            "fields": parsed["fields"]
        })

    if not results:
        return [{"error": f"No CREATE TABLE statements found in {file_ref}"}]

    return results



# -------------------------------------------------------
# STEP 1 — READ ALL FILES INTO RAW ENTRIES
# -------------------------------------------------------

def _read_all_files(file_paths: list, context: dict) -> list:
    """
    Reads every file and returns a flat list of raw entries.
    One entry per CSV/JSON file.
    One entry per CREATE TABLE found in a SQL file.
    """
    raw_entries = []

    for file_ref in file_paths:
        ext = os.path.splitext(file_ref)[-1].lower()

        # ---- CSV / JSON ----
        if ext in (".csv", ".json"):
            df, error = _load_dataframe(file_ref, context)
            if df is None:
                print(f"  ! Failed to read {file_ref}: {error}")
                continue

            fields = []
            for col in df.columns:
                samples = df[col].dropna().head(5).tolist()
                samples = [s.item() if hasattr(s, "item") else s for s in samples]
                fields.append({
                    "name":           col,
                    "dtype":          str(df[col].dtype),
                    "null_pct":       round(df[col].isnull().mean() * 100, 1),
                    "unique_count":   int(df[col].nunique()),
                    "samples":        samples,
                    "nullable":       bool(df[col].isnull().any()),
                    "is_primary_key": False,
                    "is_foreign_key": False,
                    "fk_references":  None
                })

            raw_entries.append({
                "file_name":     os.path.basename(file_ref),
                "file_path":     file_ref,
                "source_type":   ext.lstrip("."),
                "dialect":       None,
                "row_count":     len(df),
                "has_data":      True,
                "fields":        fields,
            })

        # ---- SQL ----
        elif ext == ".sql":
            sql_text = _load_sql_text(file_ref, context)
            if sql_text is None:
                print(f"  ! Failed to read {file_ref}: unable to load SQL text")
                continue
            entries = _parse_sql_text(file_ref, sql_text)
            for entry in entries:
                if "error" in entry:
                    print(f"  ! SQL parse error: {entry['error']}")
                    continue
                entry["file_path"]  = file_ref
                entry["has_data"]   = False   # DDL only for now
                raw_entries.append(entry)

        else:
            print(f"  ! Unsupported: {file_ref} (supported: .csv .json .sql)")

    return raw_entries


# -------------------------------------------------------
# STEP 2 — SCHEMA FINGERPRINT
# A frozenset of lowercased column names.
# Two files with the same fingerprint have the same schema.
# -------------------------------------------------------

def _fingerprint(entry: dict) -> frozenset:
    return frozenset(f["name"].lower() for f in entry["fields"])


def _fingerprint_str(entry: dict) -> str:
    """Human-readable sorted pipe-delimited string version."""
    return "|".join(sorted(f["name"].lower() for f in entry["fields"]))


# -------------------------------------------------------
# STEP 3+4 — GROUP BY FINGERPRINT, ASSIGN LOGICAL NAME
# -------------------------------------------------------

def _infer_logical_name(entries: list) -> str:
    """
    Given a group of files with the same schema,
    infer the best logical table name.

    Strategy:
      - Prefer the shortest file name (most likely the base name)
      - Strip part numbers: asset_part1 → asset
      - Strip suffixes: _mysql, _pg, _export, _bak, _v2 etc.
      - Titlecase the result
    """
    import re

    names = []
    for e in entries:
        name = e["file_name"]
        # Remove extension
        name = os.path.splitext(name)[0]
        # Remove SQL table suffix like __from__schema
        name = re.sub(r"__from__.*$", "", name)
        # Remove common suffixes
        name = re.sub(
            r"[_\-]?(part\d+|v\d+|bak|backup|export|mysql|pg|postgres|oracle|bigquery|old|new|final|temp|tmp|copy|\d{4,})$",
            "", name, flags=re.IGNORECASE
        )
        name = name.strip("_- ")
        names.append(name)

    # Pick shortest (most base-like) name, titlecase it
    best = min(names, key=len)
    return best.replace("_", " ").replace("-", " ").title().replace(" ", "")


def _group_by_schema(raw_entries: list) -> dict:
    """
    Groups raw entries by schema fingerprint.
    Returns dict: fingerprint_str → list of entries
    """
    groups = defaultdict(list)
    for entry in raw_entries:
        if not entry["fields"]:
            continue
        key = _fingerprint_str(entry)
        groups[key].append(entry)
    return dict(groups)


# -------------------------------------------------------
# STEP 5 — BUILD FILE REGISTRY
# -------------------------------------------------------

def _pick_representative(entries: list) -> dict:
    """
    Picks one file to represent the logical table for Phase 1 LLM call.
    Discovery Agent only needs schema understanding — not full data stats.

    Priority:
      1. Data file with most rows (best sample coverage)
      2. SQL DDL file (if no data files exist)
    """
    data_files = [e for e in entries if e["has_data"]]
    if data_files:
        return max(data_files, key=lambda e: e.get("row_count") or 0)
    return entries[0]   # fallback to first SQL entry


def _build_file_registry(groups: dict) -> list:
    """
    Builds the file registry — one record per logical table.

    Maps physical files → logical table → phase1 checkpoint.
    Data merging and profiling are NOT done here — that is
    Profiling Agent's responsibility.

    Each record contains:
      logical_table       → inferred business entity name
      schema_fingerprint  → pipe-delimited sorted column names
      phase1_checkpoint   → outputs/phase1_<name>.json
      representative_file → which file Phase 1 LLM will analyse
      has_duplicates      → True if more than one source file
      source_files        → all physical files in this group
    """
    registry = []

    for fingerprint, entries in groups.items():
        logical_name  = _infer_logical_name(entries)
        has_dupes     = len(entries) > 1
        representative = _pick_representative(entries)

        registry.append({
            "logical_table":      logical_name,
            "schema_fingerprint": fingerprint,
            "phase1_checkpoint":  f"phase1_{logical_name}.json",
            "representative_file": representative["file_name"],
            "has_duplicates":     has_dupes,
            "source_files": [
                {
                    "file_name":   e["file_name"],
                    "source_type": e["source_type"],
                    "row_count":   e.get("row_count"),
                    "has_data":    e["has_data"],
                    "dialect":     e.get("dialect")
                }
                for e in entries
            ]
        })

    registry = _deduplicate_logical_names(registry)
    return registry


# -------------------------------------------------------
# STEP 5b — DEDUPLICATE LOGICAL NAMES
# -------------------------------------------------------

def _deduplicate_logical_names(registry: list) -> list:
    """
    Ensures every logical table has a unique name in the registry.

    Problem: two files with different schemas but similar names
    e.g. work_orders.csv and workorders.csv both infer to "WorkOrders"
    but have different columns — they are genuinely different tables.

    Fix: when a name collision is detected, append a numeric suffix.
      WorkOrders   → WorkOrders_1, WorkOrders_2
      OR better: append the first unique column from each schema
      so the name is meaningful.

    Strategy:
      1. Find all name collisions
      2. For each colliding group, find the first column in each
         schema fingerprint that is NOT shared — use it as a suffix
      3. If no distinguishing column found, fall back to _1, _2
    """
    from collections import Counter

    # Count name occurrences case-insensitively
    def _norm(name: str) -> str:
        return (name or "").strip().casefold()

    name_counts = Counter(_norm(r["logical_table"]) for r in registry)
    collisions  = {name for name, count in name_counts.items() if count > 1}

    if not collisions:
        return registry   # nothing to do

    # For each collision group, disambiguate
    result = []
    seen_names = {}   # normalized logical_table → counter

    for record in registry:
        name = record["logical_table"]
        norm_name = _norm(name)

        if norm_name not in collisions:
            result.append(record)
            continue

        # Find a distinguishing column — first column NOT in other schemas of same name
        siblings = [r for r in registry if _norm(r["logical_table"]) == norm_name]
        all_fps  = [set(r["schema_fingerprint"].split("|")) for r in siblings]

        # Columns unique to THIS record's schema
        this_fp   = set(record["schema_fingerprint"].split("|"))
        other_fps = [fp for fp in all_fps if fp != this_fp]
        other_cols = set().union(*other_fps) if other_fps else set()
        unique_cols = sorted(this_fp - other_cols)

        if unique_cols:
            # Use first unique column as suffix — makes name meaningful
            suffix = unique_cols[0].replace("_", "").title()
            new_name = f"{name}_{suffix}"
        else:
            # Fallback: numeric suffix
            seen_names[norm_name] = seen_names.get(norm_name, 0) + 1
            new_name = f"{name}_{seen_names[norm_name]}"

        updated = record.copy()
        updated["logical_table"]     = new_name
        updated["phase1_checkpoint"] = f"phase1_{new_name}.json"
        updated["name_disambiguated"] = True
        updated["original_name"]      = name
        result.append(updated)

    return result


# -------------------------------------------------------
# STEP 6 — PICK REPRESENTATIVE ENTRY PER LOGICAL TABLE
# -------------------------------------------------------

def _build_payload_entry(logical_name: str, entries: list) -> dict:
    """
    Returns one representative entry per logical table for Phase 1 LLM.

    Discovery Agent only needs to understand SCHEMA:
      - field names and sample values   (to understand what the data means)
      - rough data types                (to classify fields)

    It does NOT need:
      - merged/combined rows            (Profiling Agent's job)
      - recomputed null %               (Profiling Agent's job)
      - full unique counts              (Profiling Agent's job)

    We just pick the best representative file and pass it through as-is.
    The file registry already records all source files for downstream agents.
    """
    rep = _pick_representative(entries)
    entry = rep.copy()
    entry.pop("_df", None)
    entry.pop("file_path", None)
    entry["file_name"] = logical_name   # use logical name so Phase 1 labels entity correctly
    return entry


# -------------------------------------------------------
# MAIN PUBLIC FUNCTION
# -------------------------------------------------------

def build_context_payload(file_paths: list, context: dict = None) -> dict:
    """
    Reads all files, detects duplicate schemas,
    saves file_registry.json, and returns one payload
    entry per logical table.

    Returns:
    {
      "files": [ one entry per logical table ],
      "registry": [ the file registry ]
    }
    """

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # Step 1 — read all files
    print("  [payload] Reading files...")
    if context is None:
        context = {}

    raw_entries = _read_all_files(file_paths, context)
    if not raw_entries:
        return {"files": [], "registry": []}

    # Step 2+3 — group by schema fingerprint
    groups = _group_by_schema(raw_entries)
    print(f"  [payload] {len(raw_entries)} file entries -> {len(groups)} logical table(s)")

    # Step 4 — log duplicates
    for fp, entries in groups.items():
        if len(entries) > 1:
            names = [e["file_name"] for e in entries]
            print(f"  [payload] Duplicate schema detected: {names}")

    # Step 5 — build and save registry
    registry = _build_file_registry(groups)
    registry_path = str(config.FILE_REGISTRY_PATH)
    with open(registry_path, "w") as f:
        json.dump({
            "created_at": datetime.utcnow().isoformat(),
            "total_logical_tables": len(registry),
            "total_source_files": len(raw_entries),
            "tables": registry
        }, f, indent=2, default=str)
    print(f"  [payload] File registry saved -> {registry_path}")

    # Step 6 — build one merged payload entry per logical table
    payload_files = []
    for reg_entry in registry:
        logical_name = reg_entry["logical_table"]
        fp           = reg_entry["schema_fingerprint"]
        entries      = groups[fp]

        merged = _build_payload_entry(logical_name, entries)
        payload_files.append(merged)

        if len(entries) > 1:
            print(f"  [payload] '{logical_name}' — {len(entries)} source files, representative: {reg_entry['representative_file']}")

    return {"files": payload_files, "registry": registry}



# -------------------------------------------------------
# Quick test
# -------------------------------------------------------
if __name__ == "__main__":
    file_paths = [r"D:\onboardingIQ\onboardiq\data\sample\assets_mysql.sql", 
                  r"D:\onboardingIQ\onboardiq\data\sample\locations.csv",
                  r"D:\onboardingIQ\onboardiq\data\sample\assets_postgres.sql",
                  r"D:\onboardingIQ\onboardiq\data\sample\work_orders.csv",
                  r"D:\onboardingIQ\onboardiq\data\workorders.csv"
                  ]
    if len(sys.argv) > 1:
        file_paths = sys.argv[1:]
    payload = build_context_payload(file_paths)
    print(json.dumps(payload, indent=2, default=str))
