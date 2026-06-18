#!/usr/bin/env python3
"""Fetch and print records from a DuckDB table.

Examples:
    python scripts/fetch_duckdb_table.py --table Asset
    python scripts/fetch_duckdb_table.py --table Asset --limit 50
    python scripts/fetch_duckdb_table.py --db-path data/crm_platform.duckdb --table Asset --output json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import duckdb
import pandas as pd


def connect_duckdb(db_path: str) -> duckdb.DuckDBPyConnection:
    path = Path(db_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"DuckDB file not found: {path}")
    return duckdb.connect(str(path))


def fetch_table(con: duckdb.DuckDBPyConnection, table_name: str, limit: int | None = None) -> pd.DataFrame:
    quoted_table = '"' + table_name.replace('"', '""') + '"'
    sql = f"SELECT * FROM {quoted_table}"
    params: list[object] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return con.execute(sql, params).df()


def list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
    ).fetchall()
    return [row[0] for row in rows]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch records from a DuckDB table.")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("DUCKDB_PATH", "data/crm_platform.duckdb"),
        help="Path to the DuckDB database file. Defaults to DUCKDB_PATH or data/crm_platform.duckdb.",
    )
    parser.add_argument(
        "--table",
        required=False,
        help="Table name to fetch. If omitted, the script lists available tables.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of rows to return.",
    )
    parser.add_argument(
        "--output",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format for the fetched records.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    con = connect_duckdb(args.db_path)
    try:
        if not args.table:
            print("Available tables:")
            for table_name in list_tables(con):
                print(f"- {table_name}")
            return

        df = fetch_table(con, args.table, args.limit)

        if args.output == "json":
            print(json.dumps(df.to_dict(orient="records"), indent=2, default=str))
        elif args.output == "csv":
            print(df.to_csv(index=False))
        else:
            if df.empty:
                print(f"No rows found in table '{args.table}'.")
            else:
                print(df.to_string(index=False))
    finally:
        con.close()


if __name__ == "__main__":
    main()
