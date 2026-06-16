# Migration Readiness Report

## Overall Score: 40.5/100  —  Grade: D

### Sub-scores

| Dimension | Score | Weight |
|---|---|---|
| Data Quality        | 90.0%  | 35% |
| Mapping Coverage    | 0.0%  | 35% |
| Spec Completeness   | 0.0%  | 20% |
| Relationship Clarity | 90.0% | 10% |

## Risk Register

### CRITICAL (1)

**[Mapping]** mapping_document is missing
- Root Cause: Missing Mapping Agent output.
- Impact: Cannot assess mapping coverage.
- Action: Re-run Mapping Agent before Readiness assessment.

### HIGH (2)

**[Assets]** 10 orphan record(s) (broken FK references)
- Root Cause: Broken foreign key references in Assets.
- Impact: Records reference non-existent parent IDs.
- Action: Resolve missing parent records or nullify FK before loading.

**[Specification]** migration_spec is missing
- Root Cause: Missing Specification Agent output.
- Impact: Data contracts not generated.
- Action: Re-run Specification Agent.

### MEDIUM (3)

**[Assets]** Referential integrity check failed: 10 orphan records reference invalid 'Locations.parent_ref' values.
- Root Cause: Invalid 'Locations.parent_ref' values.
- Impact: Referential integrity check failed on field 'loc_code'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Locations]** Unresolved FK candidate(s): ['parent_ref']
- Root Cause: Missing parent entity for 'parent_ref'.
- Impact: Foreign key 'parent_ref' has no matching parent entity.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

**[Users]** Unresolved FK candidate(s): ['email']
- Root Cause: Missing parent entity for 'email'.
- Impact: Foreign key 'email' has no matching parent entity.
- Action: Upload the referenced parent table or confirm the FK is to an external system.
