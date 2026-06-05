# OnboardIQ Agent Input/Output Specification

This document provides sample inputs and outputs for all agents in the OnboardIQ platform, excluding the Discovery Agent (Agent 1).

---

## Agent 2: Data Profiling Agent

*   **Inputs**:
    *   Physical raw files loaded into memory (CSVs / JSONs).
    *   `entity_catalog` (from the Discovery Agent) containing identified tables, primary keys, and foreign key relationships.

*   **Sample Output (`outputs/quality_report.json`)**:
```json
{
  "profile_summary": {
    "assessed_entities": ["Assets", "Locations", "Users", "Workorders"],
    "total_records_analyzed": 29,
    "overall_data_completeness": 92.5
  },
  "entity_quality": {
    "Assets": {
      "total_rows": 10,
      "completeness_score": 95.0,
      "duplicate_records_count": 0,
      "fields": {
        "asset_no": {
          "null_count": 0,
          "null_pct": 0.0,
          "uniqueness_pct": 100.0,
          "issues_detected": []
        },
        "loc_code": {
          "null_count": 2,
          "null_pct": 20.0,
          "uniqueness_pct": 50.0,
          "issues_detected": ["Missing referential values: 'LOC99' matches no Location primary key (Orphan record)"]
        }
      }
    },
    "Workorders": {
      "total_rows": 10,
      "completeness_score": 80.0,
      "duplicate_records_count": 1,
      "fields": {
        "wo_id": {
          "null_count": 0,
          "null_pct": 0.0,
          "uniqueness_pct": 90.0,
          "issues_detected": ["Duplicate primary key detected: 'WO001' is repeated twice"]
        },
        "completed_date": {
          "null_count": 7,
          "null_pct": 70.0,
          "uniqueness_pct": 30.0,
          "issues_detected": ["High percentage of null values (70.0%)"]
        }
      }
    }
  }
}
```

---

## Agent 3: AI Mapping Agent

*   **Inputs**:
    *   `entity_catalog` (logical schema definitions from Agent 1).
    *   `target_schema` (a reference target schema JSON defining the desired target columns, data types, and required fields for the system being migrated to).

*   **Sample Output (`outputs/mapping_document.json`)**:
```json
{
  "mappings": [
    {
      "source_entity": "Assets",
      "target_entity": "Equipment",
      "field_mappings": [
        {
          "source_field": "asset_no",
          "target_field": "equipment_id",
          "confidence_score": 0.95,
          "transformation_logic": "uppercase(trim(asset_no))",
          "reasoning": "Direct semantic match. Standard formatting matches the target structure of alpha-numeric ID."
        },
        {
          "source_field": "loc_code",
          "target_field": "location_id",
          "confidence_score": 0.88,
          "transformation_logic": "lookup(loc_code, LocationsRefTable)",
          "reasoning": "Points to location ID referencing the Locations reference master."
        }
      ],
      "unmapped_source_fields": ["purchase_date", "cost"],
      "unmapped_required_target_fields": ["warranty_status"]
    }
  ]
}
```

---

## Agent 4: Specification Generation Agent

*   **Inputs**:
    *   `mapping_document` (from Agent 3).
    *   `quality_report` (from Agent 2).

*   **Sample Output (`outputs/migration_spec.json`)**:
```json
{
  "entity_specification": {
    "Assets": [
      {
        "source_field": "asset_no",
        "target_field": "equipment_id",
        "data_type": "VARCHAR(50)",
        "nullable": false,
        "validation_rule": "REGEX('^[A-Z0-9_-]+$')",
        "transformation": "uppercase(trim(asset_no))",
        "business_constraint": "PRIMARY KEY"
      },
      {
        "source_field": "loc_code",
        "target_field": "location_id",
        "data_type": "VARCHAR(20)",
        "nullable": true,
        "validation_rule": "FOREIGN_KEY(Locations.location_key)",
        "transformation": "lookup(loc_code, LocationsRefTable)",
        "business_constraint": "NOT NULL"
      }
    ]
  }
}
```

---

## Agent 5: Migration Readiness Agent

*   **Inputs**:
    *   `quality_report` (profiling results).
    *   `mapping_document` (mapping coverage metrics).
    *   `migration_spec` (specification rules).

*   **Sample Output (`outputs/readiness_report.json`)**:
```json
{
  "migration_readiness_score": 72.0,
  "score_breakdown": {
    "data_quality_weight": 0.5,
    "data_quality_score": 68.0,
    "schema_mapping_weight": 0.3,
    "schema_mapping_score": 85.0,
    "spec_completeness_weight": 0.2,
    "spec_completeness_score": 62.0
  },
  "risk_register": [
    {
      "risk_id": "RSK-001",
      "severity": "CRITICAL",
      "impact_area": "Referential Integrity",
      "root_cause": "Workorders reference users that do not exist in the Users database (orphan records).",
      "recommended_action": "Cleanse the Workorders table or load master user database before performing wave migrations."
    },
    {
      "risk_id": "RSK-002",
      "severity": "HIGH",
      "impact_area": "Duplicates",
      "root_cause": "Workorders contain duplicate values on primary key 'wo_id'.",
      "recommended_action": "Run deduplication scripts filtering by latest 'created_date' or prompt user for selection."
    }
  ]
}
```

---

## Agent 6: Onboarding Planning Agent

*   **Inputs**:
    *   `readiness_report` (overall risks and recommendations).
    *   `entity_catalog` (relationship graph/dependencies).

*   **Sample Output (`outputs/onboarding_plan.json`)**:
```json
{
  "migration_roadmap": {
    "waves": [
      {
        "wave_number": 1,
        "wave_name": "Core Foundation Wave",
        "entities": ["Users", "Locations"],
        "estimated_effort_days": 2,
        "dependencies": [],
        "risk_mitigation": "Migrate Users and Locations first as they act as parent reference tables for down-stream entities."
      },
      {
        "wave_number": 2,
        "wave_name": "Assets Migration Wave",
        "entities": ["Assets"],
        "estimated_effort_days": 4,
        "dependencies": ["Locations"],
        "risk_mitigation": "Resolve 'LOC99' orphan values mapped to Locations before wave migration starts."
      },
      {
        "wave_number": 3,
        "wave_name": "Transactional History Wave",
        "entities": ["Workorders"],
        "estimated_effort_days": 5,
        "dependencies": ["Assets", "Users"],
        "risk_mitigation": "Run deduplication on 'wo_id' before initiating wave transactional load."
      }
    ]
  }
}
```
