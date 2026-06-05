"""
payload_builder.py
-------------------
Reads all uploaded files and builds a single clean payload for the LLM.

Handles:
  .csv  → pandas → field + sample values + null stats
  .json → pandas → field + sample values + null stats
  .sql  → sqlglot → field + dtype + constraints (no samples, no null stats)

All three produce the same output format so Phase 1 LLM call
and the rest of the pipeline need zero changes.
"""

import os
import sys
import json
import pandas as pd


from sql_parser import parse_sql_file


def build_context_payload(file_paths: list) -> dict:
    """
    Reads all files and returns a structured payload ready for the LLM.

    Returns:
    {
      "files": [
        {
          "file_name":   "assets.csv",
          "source_type": "csv",          <- "csv" | "json" | "sql_ddl"
          "dialect":     null,           <- only set for sql_ddl
          "row_count":   10,             <- null for sql_ddl
          "fields": [
            {
              "name":          "asset_no",
              "dtype":         "object",
              "null_pct":      0.0,       <- null for sql_ddl
              "unique_count":  10,        <- null for sql_ddl
              "samples":       ["A001"],  <- [] for sql_ddl
              "nullable":      false,     <- always present
              "is_primary_key": true,     <- always present
              "is_foreign_key": false,    <- always present
              "fk_references": null       <- {table, field} if FK
            }
          ]
        }
      ]
    }
    """

    payload = {"files": []}

    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"  ! File not found: {file_path}, skipping.")
            continue

        ext = os.path.splitext(file_path)[-1].lower()

        # ------------------------------------------------
        # CSV / JSON  — use pandas
        # ------------------------------------------------
        if ext in (".csv", ".json"):
            try:
                df = pd.read_csv(file_path) if ext == ".csv" else pd.read_json(file_path)
            except Exception as e:
                print(f"  ! Failed to read {file_path}: {e}")
                continue

            fields = []
            for col in df.columns:
                samples = (
                    df[col].dropna().head(5).tolist()
                )
                samples = [s.item() if hasattr(s, "item") else s for s in samples]

                fields.append({
                    "name":           col,
                    "dtype":          str(df[col].dtype),
                    "null_pct":       round(df[col].isnull().mean() * 100, 1),
                    "unique_count":   int(df[col].nunique()),
                    "samples":        samples,
                    "nullable":       bool(df[col].isnull().any()),
                    "is_primary_key": False,   # LLM figures this out from samples
                    "is_foreign_key": False,
                    "fk_references":  None
                })

            payload["files"].append({
                "file_name":   os.path.basename(file_path),
                "source_type": ext.lstrip("."),   # "csv" or "json"
                "dialect":     None,
                "row_count":   len(df),
                "fields":      fields
            })

        # ------------------------------------------------
        # SQL DDL — use sqlglot via sql_parser
        # ------------------------------------------------
        elif ext == ".sql":
            entries = parse_sql_file(file_path)

            for entry in entries:
                if "error" in entry:
                    print(f"  ! SQL parse error in {file_path}: {entry['error']}")
                    continue
                payload["files"].append(entry)

        else:
            print(f"  ! Unsupported file type: {file_path} (supported: .csv .json .sql)")

    return payload


# -------------------------------------------------------
# Quick test
# -------------------------------------------------------
if __name__ == "__main__":
    file_paths = [r"D:\onboardingIQ\onboardiq\data\sample\assets_mysql.sql", r"D:\onboardingIQ\onboardiq\data\sample\locations.csv"]
    if len(sys.argv) > 1:
        file_paths = sys.argv[1:]
    payload = build_context_payload(file_paths)
    print(json.dumps(payload, indent=2, default=str))
