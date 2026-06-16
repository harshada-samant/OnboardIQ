# Migration Readiness Report

## Overall Score: 80.1/100  —  Grade: B

### Sub-scores

| Dimension | Score | Weight |
|---|---|---|
| Data Quality        | 78.0%  | 35% |
| Mapping Coverage    | 94.1%  | 35% |
| Spec Completeness   | 66.7%  | 20% |
| Relationship Clarity | 65.0% | 10% |

## Risk Register

### MEDIUM (7)

**[Assets]** Field 'loc_code' contains high null percentage (20.0%).
- Root Cause: High null values in the 'loc_code' field indicate potential data quality issues in the source system.
- Impact: Check type NULL_CHECK failed on field 'loc_code'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Assets]** Field 'status' contains high null percentage (10.0%).
- Root Cause: High null values in the 'status' field suggest missing or incomplete data in the source system.
- Impact: Check type NULL_CHECK failed on field 'status'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Users]** Field 'email' contains high null percentage (20.0%).
- Root Cause: High null values in the 'email' field indicate potential data quality issues in the source system.
- Impact: Check type NULL_CHECK failed on field 'email'.
- Action: Review source data for this field and apply appropriate cleansing.

**[WorkOrders]** Field 'closed_date' contains high null percentage (55.0%).
- Root Cause: High null values in the 'closed_date' field suggest missing or incomplete data in the source system.
- Impact: Check type NULL_CHECK failed on field 'closed_date'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Users]** Unresolved FK candidate(s): ['email']
- Root Cause: The 'email' field is identified as a potential foreign key but lacks a corresponding parent entity.
- Impact: These fields look like foreign keys but no matching parent entity was found.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

**[WorkOrders]** Unresolved FK candidate(s): ['status', 'priority', 'created_date', 'closed_date']
- Root Cause: Multiple fields are identified as potential foreign keys without a linked parent entity.
- Impact: These fields look like foreign keys but no matching parent entity was found.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

**[Assets / Equipment]** Potential duplicate entities (MEDIUM confidence)
- Root Cause: Significant overlap in identifiers and business attributes suggests potential duplicate entities.
- Impact: Strong overlap in identifiers (asset_no) and business attributes (loc_code). Field names differ but semantics are similar.
- Action: Confirm whether these are the same entity and consolidate if so.

### LOW (2)

**[Asset]** Incomplete spec for 'asset_type': missing ['validation_rule']
- Root Cause: The 'asset_type' specification record is missing a required validation rule.
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.asset_type.

**[Asset]** Incomplete spec for 'status': missing ['validation_rule']
- Root Cause: The 'status' specification record is missing a required validation rule.
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.status.
