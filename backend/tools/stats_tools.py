"""
Tool 2: stats_tools.py
-----------------------
Deep column-level statistics.
Helps the LLM understand what each column contains and its quality.
"""

import pandas as pd
from tools.file_tools import load_dataframe


def get_column_stats(file_path: str, column_name: str) -> dict:
    """
    Returns deep stats for a single column:
    - null percentage
    - unique value count
    - top 10 most frequent values
    - min / max (for numeric or date columns)
    - whether it looks like an ID column

    The LLM calls this when it wants to understand a specific column better.
    """
    try:
        df = load_dataframe(file_path)

        if column_name not in df.columns:
            return {"error": f"Column '{column_name}' not found. Available: {list(df.columns)}"}

        col = df[column_name]

        stats = {
            "column_name": column_name,
            "dtype": str(col.dtype),
            "total_rows": len(col),
            "null_count": int(col.isnull().sum()),
            "null_pct": round(col.isnull().mean() * 100, 2),
            "unique_count": int(col.nunique()),
            "uniqueness_pct": round(col.nunique() / len(col) * 100, 2),
            "top_values": col.value_counts().head(10).to_dict(),
            "is_likely_id": False,
            "is_likely_foreign_key": False,
        }

        # --- Numeric stats ---
        if pd.api.types.is_numeric_dtype(col):
            stats["min"] = float(col.min()) if not col.isnull().all() else None
            stats["max"] = float(col.max()) if not col.isnull().all() else None
            stats["mean"] = round(float(col.mean()), 2) if not col.isnull().all() else None

        # --- Date stats ---
        if col.dtype == "object":
            try:
                parsed = pd.to_datetime(col, infer_datetime_format=True, errors="coerce")
                if parsed.notnull().mean() > 0.8:  # 80%+ parsed as date
                    stats["likely_date_column"] = True
                    stats["date_min"] = str(parsed.min())
                    stats["date_max"] = str(parsed.max())
            except Exception:
                pass

        # --- ID detection heuristic ---
        # A column is likely an ID if:
        # - uniqueness > 90%
        # - name contains "id", "no", "code", "num", "key"
        id_keywords = ["id", "no", "code", "num", "key", "ref", "uuid"]
        col_lower = column_name.lower()
        if stats["uniqueness_pct"] > 90 and any(kw in col_lower for kw in id_keywords):
            stats["is_likely_id"] = True

        # --- Foreign key heuristic ---
        # If column name contains id/ref keywords but NOT the primary table name context
        fk_keywords = ["_id", "_no", "_code", "_ref", "_key"]
        if any(col_lower.endswith(kw) for kw in fk_keywords) and not stats["is_likely_id"]:
            stats["is_likely_foreign_key"] = True

        return stats

    except Exception as e:
        return {"error": f"Failed to compute stats: {str(e)}"}


def get_all_column_stats(file_path: str) -> dict:
    """
    Runs get_column_stats on ALL columns in a file.
    Returns a dict keyed by column name.
    Useful when the LLM wants a full picture of the file at once.
    """
    try:
        df = load_dataframe(file_path)
        result = {}
        for col in df.columns:
            result[col] = get_column_stats(file_path, col)
        return result
    except Exception as e:
        return {"error": str(e)}
