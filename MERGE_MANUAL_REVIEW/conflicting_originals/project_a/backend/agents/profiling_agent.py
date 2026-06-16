"""
profiling_agent.py
-------------------
Agent 2 — Data Profiling Agent.
Performs automated data quality assessment on source data files.
Computes null percentage, detects duplicate records, and validates referential integrity (orphan checks).
Uses python/pandas for deterministic, accurate calculation.
"""

import os
import sys
import pandas as pd
from tools.output_tools import save_output

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config


def _load_dataframe(file_ref: str, context: dict):
    """Returns (df, error_string). Never raises. df is None on failure."""
    storage = context.get('_storage')
    ext = os.path.splitext(file_ref)[1].lower()
    try:
        if storage is None:
            if ext == '.csv':
                return pd.read_csv(file_ref, dtype=str, keep_default_na=False), None
            elif ext == '.json':
                return pd.read_json(file_ref, dtype=str), None
            return None, f'No storage backend for {file_ref}'
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
        return None, f'Unsupported extension: {ext}'
    except Exception as e:
        return None, str(e)


def _resolve_full_key(filename: str, context: dict) -> str:
    """
    Resolves a short filename like 'assets.csv' to its full key
    like 'inputs/user1/test_job_1/assets.csv' using context['source_files'].
    Falls back to filename if no match found.
    """
    source_files = context.get('source_files', [])
    for key in source_files:
        if key.endswith('/' + filename) or key == filename:
            return key
    return filename


def _load_logical_table_df(logical_table_record: dict, context: dict) -> pd.DataFrame:
    """
    Concatenates all data source files mapped to a logical table
    into a single pandas DataFrame.
    """
    dfs = []
    for sf in logical_table_record.get("source_files", []):
        if not sf.get("has_data"):
            continue
        file_name = sf["file_name"]
        file_ref = _resolve_full_key(file_name, context)
        df, error = _load_dataframe(file_ref, context)
        if df is None:
            if error:
                print(f"  ! [profiling] Failed to load physical file {file_name} for logical table: {error}")
            continue
        try:
            dfs.append(df)
        except Exception as e:
            print(f"  ! [profiling] Failed to load physical file {file_name} for logical table: {e}")
            
    if not dfs:
        return pd.DataFrame()
    if len(dfs) == 1:
        return dfs[0]
    return pd.concat(dfs, ignore_index=True)


def run_profiling_agent(context: dict, verbose: bool = True) -> dict:
    """
    Executes Agent 2 profiling audits using the shared context store.
    
    Checks:
      - Field null counts & percentages
      - Row count validation
      - Duplicate records relative to identified primary keys
      - Referential integrity orphan records based on discovery relationship graph
      - Overall data completeness
      
    Saves to context["quality_report"] and writes outputs/quality_report.json.
    """
    if verbose:
        print("\n" + "=" * 60)
        print("  DATA PROFILING AGENT")
        print("=" * 60)

    entity_catalog = context.get("entity_catalog", {})
    file_registry  = context.get("file_registry", [])
    if not entity_catalog or not file_registry:
        print("  x Error: Discovery metadata missing in context. Run Discovery Agent first.")
        return context

    # Index entity catalog records by logical name for fast lookup
    entity_map = {e["entity_name"].lower(): e for e in entity_catalog.get("entities", [])}
    
    # Store profiles per entity
    entity_quality = {}
    total_records = 0
    total_possible_cells = 0
    total_null_cells = 0

    for reg_entry in file_registry:
        logical_name = reg_entry["logical_table"]

        # 1. Load merged dataframe
        df = _load_logical_table_df(reg_entry, context)
        if df.empty:
            if verbose:
                print(f"\n  Profiling logical table: {logical_name}...")
                print(f"    ~ Inferred schema-only logical table (no physical data files to profile).")
            continue

        row_count = len(df)
        total_records += row_count
        
        if verbose:
            print(f"\n  Profiling logical table: {logical_name} ({row_count} rows)...")
        
        # Look up primary key in catalog
        entity_info = entity_map.get(logical_name.lower(), {})
        pk = entity_info.get("primary_key")

        # 2. Setup audit schema
        table_audit = {
            "logical_table":           logical_name,
            "representative_file":     reg_entry.get("representative_file"),
            "total_rows":              row_count,
            "completeness_score":      100.0,
            "duplicate_records_count": 0,
            "orphan_records_count":    0,
            "fields":                  {},
            "checks":                  []
        }

        # 3. Column-level profiling
        for col in df.columns:
            null_count   = int(df[col].isnull().sum())
            null_pct     = round((null_count / row_count) * 100, 2) if row_count > 0 else 0.0
            unique_count = int(df[col].nunique())

            total_possible_cells += row_count
            total_null_cells     += null_count

            # Null check assertion
            if null_pct == 0.0:
                chk_status = "PASS"
                chk_msg    = f"Field '{col}' has no missing values."
            elif null_pct < 10.0:
                chk_status = "WARNING"
                chk_msg    = f"Field '{col}' contains {null_pct}% null values."
            else:
                chk_status = "FAIL"
                chk_msg    = f"Field '{col}' contains high null percentage ({null_pct}%)."

            table_audit["checks"].append({
                "check_type": "NULL_CHECK",
                "field":      col,
                "status":     chk_status,
                "message":    chk_msg
            })

            table_audit["fields"][col] = {
                "null_count":      null_count,
                "null_pct":        null_pct,
                "unique_count":    unique_count,
                "issues_detected": [chk_msg] if chk_status != "PASS" else []
            }

            if verbose:
                indicator = "[PASS]" if chk_status == "PASS" else f"[{chk_status}]"
                print(f"    - {col:18s} | Null: {null_pct:5.1f}% | Unique: {unique_count:5d}  {indicator}")

        # 4. Duplicate checks relative to Primary Key
        if pk:
            if pk in df.columns:
                pk_unique_count = df[pk].nunique()
                duplicate_count = row_count - pk_unique_count
                table_audit["duplicate_records_count"] = int(duplicate_count)

                if duplicate_count == 0:
                    dup_status = "PASS"
                    dup_msg    = f"Primary key '{pk}' uniqueness verified."
                else:
                    dup_status = "FAIL"
                    dup_msg    = f"Primary key '{pk}' contains {duplicate_count} duplicate value(s)."
                    table_audit["fields"][pk]["issues_detected"].append(dup_msg)

                table_audit["checks"].append({
                    "check_type": "PRIMARY_KEY_DUPLICATES",
                    "field":      pk,
                    "status":     dup_status,
                    "message":    dup_msg
                })

                if verbose:
                    indicator = "[PASS]" if dup_status == "PASS" else f"[{dup_status}]"
                    print(f"    - ID Uniqueness     | PK: {pk:14s} | Dup Count: {duplicate_count:3d}  {indicator}")
            else:
                if verbose:
                    print(f"    ! Primary key '{pk}' from catalog not found in physical DataFrame columns.")
        else:
            if verbose:
                print("    - ID Uniqueness     | No primary key defined in catalog.")

        # 5. Referential Integrity (Orphan) Checks
        relationships = entity_info.get("relationships", [])
        if relationships:
            for rel in relationships:
                from_field = rel["from_field"]
                to_entity  = rel["to_entity"]
                to_field   = rel["to_field"]

                # Resolve target table DataFrame
                target_reg = next((r for r in file_registry if r["logical_table"].lower() == to_entity.lower()), None)
                if not target_reg:
                    continue

                to_df = _load_logical_table_df(target_reg, context)
                if to_df.empty:
                    continue

                if from_field in df.columns and to_field in to_df.columns:
                    valid_from_vals = df[from_field].dropna()
                    target_vals     = set(to_df[to_field].dropna().unique())
                    orphans         = valid_from_vals[~valid_from_vals.isin(target_vals)]
                    orphan_count    = len(orphans)

                    table_audit["orphan_records_count"] += int(orphan_count)

                    if orphan_count == 0:
                        ref_status = "PASS"
                        ref_msg    = f"Referential integrity verified: {logical_name}.{from_field} -> {to_entity}.{to_field}."
                    else:
                        ref_status = "FAIL"
                        ref_msg    = f"Referential integrity check failed: {orphan_count} orphan records reference invalid '{to_entity}.{to_field}' values."
                        table_audit["fields"][from_field]["issues_detected"].append(ref_msg)

                    table_audit["checks"].append({
                        "check_type": "REFERENTIAL_INTEGRITY",
                        "field":      from_field,
                        "status":     ref_status,
                        "message":    ref_msg
                    })

                    if verbose:
                        indicator = "[PASS]" if ref_status == "PASS" else f"[{ref_status}]"
                        print(f"    - Referential link  | {from_field} -> {to_entity}.{to_field} | Orphans: {orphan_count:2d}  {indicator}")

        # 6. Overall completeness score
        total_possible = row_count * len(df.columns)
        total_null     = sum(df[c].isnull().sum() for c in df.columns)
        completeness = round((1.0 - (total_null / total_possible)) * 100, 2) if total_possible > 0 else 100.0
        table_audit["completeness_score"] = completeness

        entity_quality[logical_name] = table_audit

    # 7. Overall dataset completeness
    overall_completeness = (
        round((1.0 - (total_null_cells / total_possible_cells)) * 100, 2)
        if total_possible_cells > 0
        else 100.0
    )

    entity_row_counts = {name: info["total_rows"] for name, info in entity_quality.items()}

    quality_report = {
        "profile_summary": {
            "assessed_entities":         list(entity_quality.keys()),
            "entity_row_counts":         entity_row_counts,
            "total_records_analyzed":    total_records,
            "overall_data_completeness": overall_completeness
        },
        "entity_quality": entity_quality
    }

    # Save output
    save_result = save_output(quality_report, "quality_report.json")
    context["quality_report"] = quality_report

    if verbose:
        print(f"\n  + Quality report saved to: {save_result.get('saved_to')}")
        print("\n" + "=" * 60)
        print("  DATA PROFILING COMPLETE")
        print("=" * 60)
        print(f"  Overall Completeness : {overall_completeness}%")
        print(f"  Total Records        : {total_records}")
        print(f"  Audit Report         : outputs/quality_report.json")
        print("=" * 60)

    return context
