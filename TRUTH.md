# OnboardIQ — Project Truth File
> Single source of truth for design decisions, agent responsibilities, and implementation.
> Refer to this whenever you feel out of sync with the project direction.
> Only accepted and implemented decisions are recorded here.

---

## 1. What OnboardIQ Does

Automates enterprise data onboarding preparation.
Replaces manual spreadsheet-driven processes with a pipeline of AI agents.

**Input:** Customer data files (CSV, JSON, SQL DDL)
**Output:** Entity catalog, quality report, field mappings, migration spec, readiness score, onboarding plan

---

## 2. The Pipeline

```
Input Files
    ↓
[Agent 1] Discovery Agent      → entity_catalog.json
    ↓
[Agent 2] Profiling Agent      → quality_report.json
    ↓
[Agent 3] Mapping Agent        → mapping_document.json
    ↓
[Agent 4] Specification Agent  → migration_spec.json
    ↓
[Agent 5] Readiness Agent      → readiness_report.json
    ↓
[Agent 6] Planning Agent       → onboarding_plan.json
    ↓
Final Output Package
```

**Rule:** Each agent reads from `context` dict, does its job, writes output back to `context` and to disk.
**Rule:** Agents are sequential. No dynamic routing. No agent-to-agent negotiation.

---

## 3. Shared Context Store

All agents read from and write to one shared Python dict:

```python
context = {
    "source_files":   [],     # input file paths
    "file_registry":  None,   # file_registry.json — set by payload_builder
    "entity_catalog": None,   # set by Discovery Agent
    "quality_report": None,   # set by Profiling Agent
    "mappings":       None,   # set by Mapping Agent
    "specification":  None,   # set by Specification Agent
    "readiness":      None,   # set by Readiness Agent
    "plan":           None,   # set by Planning Agent
}
```

---

## 4. Why No Agentic Framework (LangGraph, CrewAI, AutoGen)

**Decision:** Plain Python. No framework.

**Reason:**
- Pipeline order is fixed: Discovery → Profiling → ... → Planning. Never changes.
- No dynamic decision making — LLM does not decide what to do next.
- No agent-to-agent negotiation or debate.
- Frameworks (LangGraph, CrewAI) solve the problem of "LLM needs to figure out what to do next." Our pipeline already knows.
- Plain Python is simpler, more debuggable, and has no hidden magic or unstable framework APIs.

---

## 5. LLM Choice

**Decision:** AWS Bedrock (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) via `boto3` SDK.

**Config:**
```python
temperature=0.0       # deterministic — same input = same output
max_tokens=2048 (default/configurable)
```

---

## 6. Agent 1 — Discovery Agent

### Responsibility
Understand WHAT the data is.
- Identify business entities (Assets, WorkOrders, Users, Locations...)
- Identify primary keys and field roles
- Detect relationships between entities

### What It Does NOT Do
- Compute null %, duplicate counts, orphan records → Profiling Agent
- Merge split data files → Profiling Agent
- Generate field mappings → Mapping Agent

### Approach: Two-Phase

**Phase 1 — Per-table LLM call (parallel)**
- One focused LLM call per logical table
- Input: field names + dtypes + sample values (schema understanding only)
- Output: entity name, PK, field roles, FK candidates + value pattern
- Runs in parallel via `ThreadPoolExecutor`
- Each result saved immediately to `outputs/phase1_<name>.json`

**Phase 2 — Relationship resolution (single tiny LLM call)**
- Input: FK signatures (entity + PK + FK candidates) plus all field names
- No raw data, no samples — prompt stays tiny regardless of table count
- LLM reasons semantically: `workorders.asset_no` pattern `A00x` matches `assets.asset_no`
- Output:
    - `relationships` with confidence + reasoning
    - `potential_duplicate_entities` with confidence + reasoning

**Why two phases:**
- 10+ tables in one prompt = too large, expensive, unreliable
- Phase 1 runs in parallel = fast
- Phase 2 prompt stays tiny forever = scales to 100+ tables

### Checkpointing + Retry

**Checkpointing (resume on crash):**
- Before calling Bedrock, check if `outputs/phase1_<table>.json` exists
- If yes and checkpoint status is not FAILED -> load from disk, skip API call
- If yes and checkpoint status is FAILED -> reprocess table via Bedrock
- If no -> call Bedrock, save result immediately after
- Crash after 6/10 tables = resume from table 7 on next run

**Retry logic:**
- `MAX_RETRIES = 2` (3 total attempts)
- `RETRY_DELAY = 3` seconds between retries
- All retries exhausted -> mark table as `FAILED`, continue with remaining tables
- Failed tables tracked in `entity_catalog.summary.failed_tables`

**To reset and rerun from scratch:**
```bash
rm outputs/phase1_*.json
python run_discovery.py
```

### Scalability

| Tables | Phase 1 | Phase 2 | Bottleneck |
|--------|---------|---------|------------|
| 10     | 10 parallel calls | 1 tiny call | none |
| 50     | 50 parallel calls | 1 tiny call | API rate limits |
| 100+   | 100 parallel calls | 1 tiny call | API rate limits → checkpointing saves you |

---

## 7. File Handling

### Supported Input Formats

| Format | Handler | What we get |
|--------|---------|-------------|
| `.csv` | pandas | fields + dtypes + samples + null % |
| `.json` | pandas | fields + dtypes + samples + null % |
| `.sql` (DDL) | sqlglot | fields + dtypes + PK/FK constraints |
| `.sql` (DDL + data) | sqlglot (DDL only) | DDL parsed, INSERT data ignored (**known gap, handle later**) |

### SQL Dialect Support (via sqlglot)
MySQL, PostgreSQL, BigQuery, Oracle, SQLite, Snowflake, DuckDB, Spark SQL, Redshift, T-SQL (MSSQL).
Auto-detected from DDL text patterns (backticks → MySQL, SERIAL → Postgres, VARCHAR2 → Oracle etc.)

### Why sqlglot over manual parsing
- Every dialect has different syntax — regex parsers break on edge cases
- sqlglot handles ALL dialects, inline/table-level constraints, FK REFERENCES, NOT NULL
- Zero dialect-specific code needed

---

## 8. File Registry (`outputs/file_registry.json`)

### Why It Exists
Customers often provide the same table split across multiple files or exported from multiple sources:
- `asset_part1.csv` + `asset_part2.csv` — same schema, split data
- `assets.csv` + `assets_mysql.sql` — same schema, data + DDL reference
- `schema_v1.sql` + `schema_v2.sql` — duplicate DDL exports

Without tracking this, downstream agents don't know which files belong together.

### What It Contains
One record per **logical table** (not per physical file):

```json
{
  "logical_table":       "Assets",
  "schema_fingerprint":  "asset_no|asset_name|cost|loc_code|status",
  "phase1_checkpoint":   "phase1_Assets.json",
  "representative_file": "assets.csv",
  "has_duplicates":      true,
  "source_files": [
    {"file_name": "assets.csv",       "source_type": "csv", "row_count": 10,   "has_data": true},
    {"file_name": "asset_part2.csv",  "source_type": "csv", "row_count": 3,    "has_data": true},
    {"file_name": "assets_mysql.sql", "source_type": "sql_ddl", "row_count": null, "has_data": false}
  ]
}
```

### Duplicate Detection
Schema fingerprint = `frozenset` of lowercased column names.
Two files with identical column sets = same logical table.

### Representative File
Discovery Agent only needs ONE file per logical table for schema understanding.
We pick the data file with most rows (best sample coverage).
No data merging in Discovery Agent — that is Profiling Agent's job.

### Logical Name Inference
Strips common suffixes from file names: `_part1`, `_part2`, `_mysql`, `_pg`, `_export`, `_bak`, `_v2`, timestamps.
`asset_part1.csv` → `Asset`, `workorders_export_2024.csv` → `Workorders`

### Logical Name Deduplication
Two files can have different schemas but infer to the same logical name.
Example: `work_orders.csv` and `workorders.csv` both → `WorkOrders` but have different columns.
Fix: `_deduplicate_logical_names()` detects collisions and appends the first unique column as suffix.
`WorkOrders` + `WorkOrders` → `WorkOrders_Closeddate` + `WorkOrders_Assetno`
`name_disambiguated: true` and `original_name` recorded in registry for traceability.

Collision detection is case-insensitive (e.g., `WorkOrders` and `Workorders` collide).

### Semantic Duplicate Entity Detection (Phase 2)
Schema fingerprinting catches structurally identical files but misses semantically identical ones.
Example: `equip_id` vs `asset_no` — different names, same business meaning.
This is detected in Phase 2 by the LLM, which receives all field names across all entities.
Output: `potential_duplicate_entities` in entity catalog as entity pairs (`entity_a`, `entity_b`) with confidence and reasoning.

---

## 9. Database Schema and Authentication

OnboardIQ uses a local SQLite database for credentials, session management, and target schema selection persistence.

### SQLite Database (`data/onboardiq.db`)
Exposes the `users` table:
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    target_schema TEXT DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Password Security & Seeding
* Passwords are encrypted using `bcrypt` and verified using `bcrypt.checkpw()`. Plaintext credentials are never saved.
* Seed scripts define two baseline demo accounts:
  * `user1` / `password123`
  * `user2` / `password123`

### Target Schema Persistence Rules
* The `target_schema` database column stores **only** the filename of the schema (e.g. `maximo.json`), never absolute paths or file contents.
* Updates via `update_user_target_schema` validate:
  - Non-empty string filename format.
  - Suffix ending with `.json`.
  - Existence of the schema file inside the `schemas/` directory.
  - Path traversal checks preventing directory escapes (`Path(schema_name).name == schema_name`).
  - Active existence of the `user_id` in the database.

---

## 10. Multi-User Workspace Routing & Isolation

To support secure isolated concurrent workloads, the system routes folders dynamically.

### Workspace Directory Layout
Every authenticated user is assigned a separate folder:
```text
workspaces/
└── users/
    ├── {username}/
    │   ├── uploads/          <- Input CSV/JSON source files (maps to config.INPUT_DIR)
    │   ├── outputs/          <- Generated reports and snapshots (maps to config.OUTPUT_DIR)
    │   └── chat_history.json <- Persistent chat context file
```

### Request-Time Middleware Reconfiguration
* NICEGUI session cookies store `authenticated` (bool), `user_id` (int), and `username` (str).
* **ASGI Middleware** (`frontend/middleware.py`) intercepts every incoming HTTP request. If the session is authenticated, it calls:
  - `config.set_user_workspace(username)` to map all report path constants to the user's isolated `outputs/` folder.
  - `configure_user_schema(user_id)` to verify and load the correct target schema file.
* **Concurrency Model & Limitation:** Since NiceGUI processes ASGI request handlers sequentially in its main loop, this request-time reconfiguration dynamically refreshes global variables safely. For high-volume production, separate worker processes or thread-local context variables are required to achieve full thread-safe request isolation.

### Target Schema Service Layer (`backend/schema_service.py`)
Provides the public orchestrator API for future dashboard/UI integrations:
* `get_schema_options() -> list[str]`: Lists alphabetically sorted available schema filenames from `schemas/`.
* `get_user_schema_selection(user_id: int) -> str | None`: Retrieves the active user's selection filename.
* `update_user_schema_selection(user_id: int, schema_name: str) -> bool`: Coordinates updates.
  - Calls database persistence helpers.
  - Calls configuration helpers.
  - **Option A Recovery Logic:** If the schema file is deleted or missing from disk, path configuration fails (returns `False`), logs a warning, and preserves the previously loaded valid target schema path without corrupting the configuration.
  - Logs selections: `[SCHEMA] Updated schema selection for {username}: {schema_name}`.

---

## 11. Outputs Folder Structure

```text
workspaces/users/{username}/outputs/
  file_registry.json          <- physical file -> logical table map (set by payload_builder)
  phase1_Assets.json          <- Phase 1 profile per logical table (set by Discovery Agent)
  phase1_WorkOrders.json
  phase1_Locations.json
  ...
  entity_catalog.json         <- final merged catalog (set by Discovery Agent)
                                 includes entities, summary, and potential_duplicate_entities
  quality_report.json         <- set by Profiling Agent
  mapping_document.json       <- set by Mapping Agent
  migration_spec.json         <- set by Specification Agent
  readiness_report.json       <- set by Readiness Agent
  onboarding_plan.json        <- set by Planning Agent
```

---

## 12. Implementation Status

| Component | Status | Notes |
|-----------|--------|-------|
| `tools/file_tools.py` | ✅ Done | read_file, load_dataframe |
| `tools/stats_tools.py` | ✅ Done | get_column_stats, get_all_column_stats |
| `tools/output_tools.py` | ✅ Done | save_output, load_output (uses config.OUTPUT_DIR dynamically) |
| `tools/sql_parser.py` | ✅ Done | sqlglot-based DDL parser, auto dialect detection |
| `database.py` | ✅ Done | SQLite connection initialization, bcrypt password checking, target schema persistence, username lookups |
| `schema_manager.py` | ✅ Done | Available schemas listing, path resolution, path traversal checks, Option A configuration recovery |
| `schema_service.py` | ✅ Done | Options listing, retrieval, no-op updates, validation, and error log orchestration |
| `agents/payload_builder.py` | ✅ Done | Reads all files, deduplicates schemas, deduplicates logical names, builds file registry |
| `agents/discovery_agent.py` | ✅ Done | Two-phase, parallel, checkpointing, retry, semantic duplicate-entity detection, Bedrock client integration |
| `agents/profiling_agent.py` | ✅ Done | Computes null stats, unique value counts, validates PK uniqueness, referential integrity check |
| `agents/mapping_agent.py` | ✅ Done | AI-generated source-to-target field mapping, merges manual interactive overrides |
| `agents/specification_agent.py` | ✅ Done | Merges mappings and profiling reports to auto-generate data contracts (.json and .md specs) |
| `agents/readiness_agent.py` | ✅ Done | Computes aggregate readiness score, categorizes risks, and enriches risk register via Bedrock |
| `agents/planning_agent.py` | ✅ Done | Sequences entities into Silver waves based on dependency graph, enriches wave details via Bedrock |
| `agents/conversational_assistant.py` | ✅ Done | Chat backend that answers queries and executes natural language mapping actions/overrides |
| `pipeline.py` | ✅ Done | Loads .env, validates AWS credentials, lists supported files, runs all agents in sequence (Discovery -> Planning) |
| `main.py` | ✅ Done | Typer CLI runner for pipeline and interactive chat assistant (`run` and `chat` commands) |
| `middleware.py` | ✅ Done | ASGI http middleware reconfiguring workspace routes and active schemas on every authenticated request |
| `pages/login.py` | ✅ Done | NiceGUI user login screen. Stores user session storage keys and configures active workspaces |
| `pages/dashboard.py` | ✅ Done | NiceGUI welcome dashboard. Displays logged in username and workspace isolation paths |

---

## 13. Known Gaps (Deferred)

| Gap | Where | Plan |
|-----|-------|------|
| `.sql` files with INSERT data ignored | `sql_parser.py` | Parse INSERT statements in later pass |
| `.xlsx` support | `payload_builder.py` | Add openpyxl reader when needed |

---

## 12. Key Principles

1. **Each agent does one job.** No agent does another agent's work.
2. **Python for mechanics, LLM for intelligence.** File reading, stats, parsing = Python. Understanding, naming, relating = LLM.
3. **Prompts stay small.** Never send raw data to LLM when a schema summary is enough.
4. **Fail gracefully.** One bad table never stops the pipeline. Mark as FAILED, continue.
5. **Checkpoint everything.** Any intermediate result that cost an API call gets saved to disk immediately.
6. **File registry is the source of truth.** Any agent that needs to know which files map to which table reads `file_registry.json`.
