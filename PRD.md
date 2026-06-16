# Product Requirements Document (PRD)
## OnboardIQ: Agentic Customer Data Onboarding Platform

**Hackathon:** Data Engineering Hackathon  
**Date:** May 2026  
**Version:** 1.0  
**Status:** Draft

---

## 1. Overview

### 1.1 Product Summary

OnboardIQ is an Agentic AI and Data Engineering platform that automates customer data onboarding preparation. It replaces manual, spreadsheet-driven onboarding processes with intelligent agents that perform data discovery, profiling, mapping generation, specification creation, and migration readiness assessment.

### 1.2 Problem Statement

Enterprise software companies spend weeks or months onboarding new customers due to:

- Fragmented source systems (SAP, Oracle, Maximo, custom DBs, CSV exports)
- Undocumented data structures and schemas
- Manual field mapping exercises in spreadsheets
- Late discovery of data quality issues (duplicates, nulls, orphan records)
- No standardized migration specifications or validation rules

This results in delayed customer value realization, high operational cost, and a process that does not scale.

### 1.3 Proposed Solution

A multi-agent AI platform that automates the end-to-end onboarding preparation pipeline:

```
Input Data (CSV / JSON / Schema) 
    → Discovery Agent 
    → Profiling Agent 
    → Mapping Agent 
    → Specification Agent 
    → Readiness Agent 
    → Planning Agent 
    → Onboarding Report
```

---

## 2. Goals & Success Metrics

### 2.1 Hackathon Goals

| Goal | Target |
|------|--------|
| Automate entity discovery from raw files | Identify ≥ 5 business entities per dataset |
| Generate field mappings automatically | ≥ 80% of source fields mapped |
| Produce data quality report | Null %, duplicate %, orphan record counts |
| Output migration specification | Structured contract per entity |
| Compute migration readiness score | Single score with risk breakdown |
| Generate onboarding plan | Wave-based roadmap with effort estimates |

### 2.2 Success Metrics

- Reduction in onboarding analysis effort (hours saved vs. manual baseline)
- Number of field mappings auto-generated
- Data quality issues surfaced before migration
- Accuracy of migration readiness score
- End-to-end pipeline execution time

---

## 3. Scope

### 3.1 In Scope (MVP — 5 Days)

| Area | Details |
|------|---------|
| Input formats | CSV files, JSON files, Database schema exports |
| Agent pipeline | All 6 agents (Discovery → Planning) |
| Output artifacts | Entity report, Quality report, Mapping doc, Migration spec, Readiness score, Onboarding plan |
| Target personas | Onboarding engineers, data migration analysts |

### 3.2 Out of Scope

- Real-time database connectors (JDBC, ODBC)
- UI/Frontend dashboard (CLI or API output is acceptable for hackathon)
- Production deployment / security hardening
- Support for unstructured documents (PDFs, emails)

---

## 4. Functional Requirements

### 4.1 Agent 1 — Data Discovery Agent

**Purpose:** Analyze uploaded files and identify business entities and relationships.

**Inputs:** Raw CSV/JSON files or schema exports  
**Outputs:** List of discovered entities with field inventory

| Requirement | Description |
|-------------|-------------|
| FR-1.1 | Parse CSV and JSON files and extract column names, sample values, and data types |
| FR-1.2 | Identify business entities: Assets, Work Orders, Users, Locations, Maintenance Plans |
| FR-1.3 | Detect relationships between entities (e.g., Work Order → Asset, Asset → Location) |
| FR-1.4 | Output a structured entity catalog with field-level metadata |

---

### 4.2 Agent 2 — Data Profiling Agent

**Purpose:** Perform automated data quality assessment on source data.

**Inputs:** Raw source data files  
**Outputs:** Data quality report per entity and field

| Requirement | Description |
|-------------|-------------|
| FR-2.1 | Compute null/missing value percentage per column |
| FR-2.2 | Detect duplicate records based on key fields |
| FR-2.3 | Identify orphan records (foreign key references with no matching parent) |
| FR-2.4 | Assess data completeness per entity |
| FR-2.5 | Validate referential integrity across related entities |
| FR-2.6 | Produce a structured quality summary (pass/fail/warning per check) |

---

### 4.3 Agent 3 — AI Mapping Agent

**Purpose:** Generate source-to-target field mappings with transformation recommendations.

**Inputs:** Source entity catalog, target schema definition  
**Outputs:** Mapping document per entity

| Requirement | Description |
|-------------|-------------|
| FR-3.1 | Use semantic similarity to match source fields to target fields |
| FR-3.2 | Suggest transformation logic (e.g., `uppercase(trim(asset_no))`) |
| FR-3.3 | Flag unmapped source fields and unmapped required target fields |
| FR-3.4 | Assign confidence score to each mapping |
| FR-3.5 | Output mappings in structured format (source, target, transformation, confidence) |

**Example Mapping:**

| Source Field | Target Field | Transformation | Confidence |
|---|---|---|---|
| `asset_no` | `asset_id` | `uppercase(trim(asset_no))` | 94% |
| `loc_code` | `location_id` | `lookup(loc_code, location_ref)` | 88% |

---

### 4.4 Agent 4 — Specification Generation Agent

**Purpose:** Auto-generate migration data contracts and specifications.

**Inputs:** Mapping document, profiling results  
**Outputs:** Migration specification document per entity

| Requirement | Description |
|-------------|-------------|
| FR-4.1 | Generate a specification record per mapped field |
| FR-4.2 | Specify source field, target field, data type, validation rules, and transformation logic |
| FR-4.3 | Include business constraints (e.g., NOT NULL, unique, foreign key) |
| FR-4.4 | Output spec as a structured document (JSON or Markdown table) |

**Spec Schema per Field:**

```
source_field       → string
target_field       → string
data_type          → string
nullable           → boolean
validation_rule    → string
transformation     → string
business_constraint → string
```

---

### 4.5 Agent 5 — Migration Readiness Agent

**Purpose:** Compute an overall migration readiness score and identify blockers.

**Inputs:** Profiling report, mapping coverage, specification completeness  
**Outputs:** Readiness score (0–100%) with categorized risks

| Requirement | Description |
|-------------|-------------|
| FR-5.1 | Compute readiness score as weighted aggregate of quality, mapping, and spec completeness |
| FR-5.2 | Categorize risks as Critical, High, Medium, Low |
| FR-5.3 | List specific risk items with root cause and recommended action |
| FR-5.4 | Output readiness report with score and risk register |

**Example Output:**

```
Migration Readiness Score: 72%

Critical Risks:
  - Missing Asset IDs (affects 18% of records)

High Risks:
  - Duplicate Work Orders detected (342 duplicates)

Medium Risks:
  - Invalid Location References (orphan records: 87)
```

---

### 4.6 Agent 6 — Onboarding Planning Agent

**Purpose:** Generate a structured onboarding roadmap with migration waves and effort estimates.

**Inputs:** Readiness score, risk register, entity dependency graph  
**Outputs:** Onboarding plan with phases, dependencies, and effort

| Requirement | Description |
|-------------|-------------|
| FR-6.1 | Sequence entities into migration waves based on dependencies |
| FR-6.2 | Estimate effort (days) per wave based on data volume and quality |
| FR-6.3 | Surface risk mitigation recommendations per wave |
| FR-6.4 | Output plan as structured document (phases, entities, effort, risks) |

---

## 5. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Pipeline execution time | Full pipeline completes in < 2 minutes for datasets up to 100K rows |
| Scalability | Handles CSV files up to 500MB |
| Reproducibility | Same input always produces same output (deterministic agents) |
| Observability | Each agent logs its actions and decisions |
| Modularity | Each agent is independently runnable and testable |

---

## 6. Technical Architecture

### 6.1 Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11+ |
| Agent Framework | LangChain / LangGraph (or custom agent loop) |
| LLM | OpenAI GPT-4o / Azure OpenAI |
| Data Processing | Pandas, DuckDB |
| Schema Analysis | SQLGlot / custom parsers |
| Output Format | JSON, Markdown, CSV |
| Orchestration | Sequential agent pipeline with shared context store |

### 6.2 Data Flow

```
[Input Files]
      │
      ▼
[Discovery Agent] ──→ Entity Catalog
      │
      ▼
[Profiling Agent] ──→ Quality Report
      │
      ▼
[Mapping Agent]   ──→ Mapping Document
      │
      ▼
[Spec Agent]      ──→ Migration Specification
      │
      ▼
[Readiness Agent] ──→ Readiness Score + Risk Register
      │
      ▼
[Planning Agent]  ──→ Onboarding Roadmap
      │
      ▼
[Final Output Package]
```

### 6.3 Shared Context Store

All agents read from and write to a shared context object:

```python
context = {
    "source_files": [...],
    "entity_catalog": {...},
    "quality_report": {...},
    "mappings": [...],
    "specification": [...],
    "readiness": {...},
    "plan": {...}
}
```

---

## 7. Input / Output Specification

### 7.1 Accepted Inputs

| Format | Description |
|--------|-------------|
| `.csv` | Raw data exports from source systems |
| `.json` | Structured data or API exports |
| `.sql` | DDL schema exports (CREATE TABLE statements) |
| `.xlsx` | Spreadsheet exports (bonus support) |

### 7.2 Output Artifacts

| Artifact | Format | Description |
|----------|--------|-------------|
| Entity Catalog | JSON / Markdown | Discovered entities and fields |
| Quality Report | JSON / Markdown | Per-field quality checks and scores |
| Mapping Document | CSV / Markdown | Source-to-target field mappings |
| Migration Specification | JSON / Markdown | Data contracts per entity |
| Readiness Report | JSON / Markdown | Score, risks, and recommendations |
| Onboarding Plan | Markdown | Wave-based roadmap with effort |

---

## 8. User Stories

| ID | As a... | I want to... | So that... |
|----|---------|-------------|------------|
| US-1 | Onboarding engineer | Upload raw customer files and get an entity inventory | I don't have to manually review schemas |
| US-2 | Data analyst | See a data quality report with null %, duplicates, and orphans | I can identify blockers before migration starts |
| US-3 | Migration consultant | Get auto-generated source-to-target mappings | I reduce manual mapping effort from days to minutes |
| US-4 | Project manager | Receive a migration readiness score with risks | I can communicate confidence to stakeholders |
| US-5 | Onboarding team lead | Get a phased onboarding plan with effort estimates | I can plan the migration timeline |

---

## 9. Hackathon Delivery Plan

### Day-by-Day Breakdown

| Day | Focus | Deliverable |
|-----|-------|-------------|
| Day 1 | Setup + Discovery Agent | Working entity extraction from CSV/JSON |
| Day 2 | Profiling Agent | Quality report with null, duplicate, orphan checks |
| Day 3 | Mapping Agent + Spec Agent | AI-generated mappings + migration spec |
| Day 4 | Readiness Agent + Planning Agent | Readiness score + onboarding roadmap |
| Day 5 | Integration + Demo | End-to-end pipeline, sample output, presentation |

### Demo Dataset

Use a synthetic or public dataset representing:
- Assets table (asset_no, asset_name, location, status)
- Work Orders table (wo_id, asset_no, assigned_to, status, created_date)
- Users table (user_id, name, role, email)
- Locations table (loc_code, loc_name, parent_loc)

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LLM produces inconsistent mappings | High | Add confidence thresholds and fallback heuristics |
| Large files slow down profiling | Medium | Process in chunks using DuckDB or Pandas chunking |
| Schema exports vary by source system | Medium | Build flexible DDL parsers for common formats |
| Agent pipeline fails mid-run | Medium | Persist intermediate outputs; allow resume from checkpoint |
| Demo dataset too simple | Low | Use realistic synthetic data with known quality issues |

---

## 11. Appendix

### Glossary

| Term | Definition |
|------|------------|
| Entity | A business object such as Asset, Work Order, User, or Location |
| Mapping | A link between a source field and a target field with transformation logic |
| Migration Spec | A data contract defining rules, types, and constraints for a migration field |
| Readiness Score | A 0–100% score reflecting how ready a dataset is for migration |
| Migration Wave | A logical grouping of entities to be migrated together in sequence |
| Orphan Record | A record referencing a parent ID that does not exist in the parent table |
| Data Contract | A formal agreement on the structure, quality, and semantics of a dataset |

### Target System Context

OnboardIQ is designed to support onboarding into industrial SaaS platforms, asset management systems, and enterprise maintenance solutions. Source systems commonly include SAP, Oracle, IBM Maximo, custom databases, and legacy CSV-based systems.
