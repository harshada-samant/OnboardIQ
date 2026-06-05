"""
sql_parser.py
--------------
Parses SQL DDL files into the same structured payload format
that payload_builder.py produces for CSV files.

Uses sqlglot — handles MySQL, PostgreSQL, BigQuery, Oracle, SQLite,
Snowflake, DuckDB, Spark, Redshift, T-SQL (MSSQL) and more.

Output format matches CSV payload exactly so the rest of the
pipeline (Phase 1 LLM call, Phase 2, merge) needs zero changes.

{
  "file_name": "workorders.sql",
  "source_type": "sql_ddl",
  "dialect": "mysql",
  "row_count": null,          <- no actual data in DDL, always null
  "fields": [
    {
      "name": "wo_id",
      "dtype": "INT",
      "null_pct": null,       <- no data to compute this
      "unique_count": null,
      "samples": [],          <- no data
      "nullable": false,
      "is_primary_key": true,
      "is_foreign_key": false,
      "fk_references": null
    },
    {
      "name": "asset_no",
      "dtype": "VARCHAR(20)",
      "null_pct": null,
      "unique_count": null,
      "samples": [],
      "nullable": false,
      "is_primary_key": false,
      "is_foreign_key": true,
      "fk_references": {
        "table": "assets",
        "field": "asset_no"
      }
    }
  ]
}
"""

import os
import re
import sqlglot
import sqlglot.expressions as exp


# -------------------------------------------------------
# SUPPORTED DIALECTS
# sqlglot dialect name → human label
# -------------------------------------------------------
SUPPORTED_DIALECTS = {
    "mysql":      "MySQL",
    "postgres":   "PostgreSQL",
    "bigquery":   "BigQuery",
    "oracle":     "Oracle",
    "sqlite":     "SQLite",
    "snowflake":  "Snowflake",
    "duckdb":     "DuckDB",
    "spark":      "Spark SQL",
    "redshift":   "Redshift",
    "tsql":       "SQL Server (T-SQL)",
}


# -------------------------------------------------------
# DIALECT AUTO-DETECTION
# Looks for dialect-specific keywords in the DDL text
# Falls back to "mysql" which sqlglot parses most leniently
# -------------------------------------------------------

def _detect_dialect(sql_text: str) -> str:
    """
    Tries to auto-detect the SQL dialect from the DDL text.
    Returns a sqlglot dialect string.
    """
    text_lower = sql_text.lower()

    # BigQuery: project.dataset.table pattern or STRUCT/ARRAY types
    if re.search(r'\w+\.\w+\.\w+', sql_text) or "struct<" in text_lower or "array<" in text_lower:
        return "bigquery"

    # Snowflake: VARIANT, OBJECT, ARRAY types or $$ quoting
    if any(kw in text_lower for kw in ["variant", " object ", "$$"]):
        return "snowflake"

    # T-SQL: square bracket identifiers or NVARCHAR/UNIQUEIDENTIFIER
    if re.search(r'\[\w+\]', sql_text) or any(kw in text_lower for kw in ["nvarchar", "uniqueidentifier", "getdate()"]):
        return "tsql"

    # Oracle: VARCHAR2, NUMBER, SYSDATE
    if any(kw in text_lower for kw in ["varchar2", "number(", "sysdate"]):
        return "oracle"

    # PostgreSQL: SERIAL, BIGSERIAL, TEXT (no length), pg-specific types
    if any(kw in text_lower for kw in ["serial", "bigserial", "::text", "::integer"]):
        return "postgres"

    # MySQL: backtick identifiers or ENGINE=
    if "`" in sql_text or "engine=" in text_lower or "auto_increment" in text_lower:
        return "mysql"

    # Default — mysql is most lenient in sqlglot
    return "mysql"


# -------------------------------------------------------
# SINGLE TABLE PARSER
# -------------------------------------------------------

def _parse_single_create(statement, dialect: str) -> dict:
    """
    Parses one CREATE TABLE statement.
    Returns a structured table dict.
    """

    # --- Table name ---
    table_node = statement.find(exp.Table)
    if not table_node:
        return None
    table_name = table_node.name

    # --- Primary key columns ---
    pk_cols = set()

    # Inline: col INT PRIMARY KEY
    for col_def in statement.find_all(exp.ColumnDef):
        for constraint in col_def.find_all(exp.ColumnConstraint):
            if isinstance(constraint.args.get("kind"), exp.PrimaryKeyColumnConstraint):
                pk_cols.add(col_def.name)

    # Table-level: PRIMARY KEY (col1, col2)
    for pk in statement.find_all(exp.PrimaryKey):
        for ident in pk.find_all(exp.Identifier):
            pk_cols.add(ident.name)

    # --- Foreign key map: field → {table, field} ---
    fk_map = {}
    for fk in statement.find_all(exp.ForeignKey):
        fk_fields = [i.this for i in fk.args.get("expressions", [])]
        ref       = fk.args.get("reference")
        if ref and fk_fields:
            ref_schema = ref.args.get("this")   # Schema node
            if ref_schema:
                ref_table  = ref_schema.args.get("this")
                ref_fields = ref_schema.args.get("expressions", [])
                ref_table_name = ref_table.name if ref_table else None
                ref_field_name = ref_fields[0].this if ref_fields else None
                for field in fk_fields:
                    fk_map[field] = {
                        "table": ref_table_name,
                        "field": ref_field_name
                    }

    # --- Columns ---
    fields = []
    for col_def in statement.find_all(exp.ColumnDef):
        col_name = col_def.name
        dtype    = str(col_def.args.get("kind", "UNKNOWN"))

        # Nullable: NOT NULL constraint present?
        not_null = any(
            isinstance(c.args.get("kind"), exp.NotNullColumnConstraint)
            for c in col_def.find_all(exp.ColumnConstraint)
        )
        # Also treat PK columns as not null
        if col_name in pk_cols:
            not_null = True

        # Default value
        default_constraint = col_def.find(exp.DefaultColumnConstraint)
        default_val = str(default_constraint.this) if default_constraint else None

        fields.append({
            "name":           col_name,
            "dtype":          dtype,
            "null_pct":       None,      # no data in DDL
            "unique_count":   None,
            "samples":        [],
            "nullable":       not not_null,
            "is_primary_key": col_name in pk_cols,
            "is_foreign_key": col_name in fk_map,
            "fk_references":  fk_map.get(col_name),
            "default":        default_val
        })

    return {
        "table_name": table_name,
        "fields":     fields,
        "pk_cols":    list(pk_cols),
        "fk_map":     fk_map
    }


# -------------------------------------------------------
# MAIN PUBLIC FUNCTION
# Called by payload_builder for .sql files
# -------------------------------------------------------

def parse_sql_file(file_path: str, dialect: str = None) -> list:
    """
    Reads a .sql file and parses all CREATE TABLE statements in it.

    One .sql file can contain multiple CREATE TABLE statements
    (e.g. a full schema dump). Each becomes its own entry.

    Args:
        file_path : path to the .sql file
        dialect   : sqlglot dialect string (auto-detected if None)

    Returns:
        List of file-entry dicts in the same format as payload_builder:
        [
          {
            "file_name":   "workorders__from__schema.sql",
            "source_type": "sql_ddl",
            "dialect":     "mysql",
            "row_count":   null,
            "fields":      [...]
          },
          ...   one entry per CREATE TABLE found
        ]
    """

    if not os.path.exists(file_path):
        return [{"error": f"File not found: {file_path}"}]

    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        sql_text = f.read()

    if not sql_text.strip():
        return [{"error": f"Empty file: {file_path}"}]

    # Auto-detect dialect if not provided
    if not dialect:
        dialect = _detect_dialect(sql_text)

    base_name = os.path.basename(file_path)

    # Parse — sqlglot handles multiple statements in one file
    try:
        statements = sqlglot.parse(sql_text, dialect=dialect)
    except Exception as e:
        return [{"error": f"sqlglot parse failed on {file_path}: {e}"}]

    results = []

    for statement in statements:
        if not isinstance(statement, exp.Create):
            continue                        # skip non-CREATE statements
        if statement.args.get("kind") != "TABLE":
            continue                        # skip CREATE INDEX, CREATE VIEW etc.

        parsed = _parse_single_create(statement, dialect)
        if not parsed:
            continue

        # Build entry in the same format as payload_builder CSV output
        entry = {
            "file_name":   f"{parsed['table_name']}__from__{base_name}",
            "source_type": "sql_ddl",
            "dialect":     SUPPORTED_DIALECTS.get(dialect, dialect),
            "row_count":   None,
            "fields":      parsed["fields"]
        }
        results.append(entry)

    if not results:
        return [{"error": f"No CREATE TABLE statements found in {file_path}"}]

    return results
