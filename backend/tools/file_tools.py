"""
Tool 1: file_tools.py
-----------------------
Handles reading CSV and JSON files.
Returns clean, LLM-readable summaries of the file content.
"""

import pandas as pd
import json
import os


def read_file(file_path: str) -> dict:
    """
    Reads a CSV or JSON file and returns:
    - column names
    - data types
    - sample rows (first 5)
    - row count
    - column count

    This is the first tool the Discovery Agent will call.
    """

    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    file_ext = os.path.splitext(file_path)[-1].lower()

    try:
        # --- Read the file ---
        if file_ext == ".csv":
            df = pd.read_csv(file_path)
        elif file_ext == ".json":
            df = pd.read_json(file_path)
        else:
            return {"error": f"Unsupported file type: {file_ext}. Only CSV and JSON supported."}

        # --- Build summary ---
        summary = {
            "file_name": os.path.basename(file_path),
            "file_path": file_path,
            "row_count": len(df),
            "column_count": len(df.columns),
            "columns": [],
            "sample_rows": df.head(5).fillna("NULL").to_dict(orient="records")
        }

        # --- Per column metadata ---
        for col in df.columns:
            col_info = {
                "name": col,
                "dtype": str(df[col].dtype),
                "null_count": int(df[col].isnull().sum()),
                "null_pct": round(df[col].isnull().mean() * 100, 2),
                "unique_count": int(df[col].nunique()),
                "sample_values": df[col].dropna().head(5).tolist()
            }
            summary["columns"].append(col_info)

        return summary

    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}


def load_dataframe(file_path: str) -> pd.DataFrame:
    """
    Helper: loads a CSV or JSON file into a pandas DataFrame.
    Used internally by other tools.
    """
    file_ext = os.path.splitext(file_path)[-1].lower()
    if file_ext == ".csv":
        return pd.read_csv(file_path)
    elif file_ext == ".json":
        return pd.read_json(file_path)
    else:
        raise ValueError(f"Unsupported file type: {file_ext}")
