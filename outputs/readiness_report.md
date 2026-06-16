# Migration Readiness Report

## Overall Score: 71.9/100  —  Grade: C

### Sub-scores

| Dimension | Score | Weight |
|---|---|---|
| Data Quality        | 68.0%  | 35% |
| Mapping Coverage    | 92.6%  | 35% |
| Spec Completeness   | 36.0%  | 20% |
| Relationship Clarity | 85.0% | 10% |

## Risk Register

### CRITICAL (1)

**[WorkOrders]** 1 required target field(s) unmapped: ['assigned_user']
- Impact: Required fields in target schema have no corresponding source data.
- Action: Provide default values, derive from other fields, or clarify with source owner.

### MEDIUM (9)

**[Assets]** Field 'loc_code' contains high null percentage (20.0%).
- Impact: Check type NULL_CHECK failed on field 'loc_code'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Assets]** Field 'status' contains high null percentage (10.0%).
- Impact: Check type NULL_CHECK failed on field 'status'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Users]** Field 'email' contains high null percentage (20.0%).
- Impact: Check type NULL_CHECK failed on field 'email'.
- Action: Review source data for this field and apply appropriate cleansing.

**[WorkOrders]** 1 orphan record(s) (broken FK references)
- Impact: Records in WorkOrders reference parent IDs that do not exist.
- Action: Resolve missing parent records or nullify FK before loading.

**[WorkOrders]** Field 'closed_date' contains high null percentage (55.0%).
- Impact: Check type NULL_CHECK failed on field 'closed_date'.
- Action: Review source data for this field and apply appropriate cleansing.

**[WorkOrders]** Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.
- Impact: Check type REFERENTIAL_INTEGRITY failed on field 'equip_id'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Assets]** Unresolved FK candidate(s): ['loc_code']
- Impact: These fields look like foreign keys but no matching parent entity was found.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

**[Locations]** Unresolved FK candidate(s): ['parent_ref']
- Impact: These fields look like foreign keys but no matching parent entity was found.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

**[WorkOrders]** Unresolved FK candidate(s): ['technician_ref']
- Impact: These fields look like foreign keys but no matching parent entity was found.
- Action: Upload the referenced parent table or confirm the FK is to an external system.

### LOW (16)

**[Asset]** Incomplete spec for 'asset_name': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.asset_name.

**[Asset]** Incomplete spec for 'b_location_id': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.b_location_id.

**[Asset]** Incomplete spec for 'asset_type': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.asset_type.

**[Asset]** Incomplete spec for 'status': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Asset.status.

**[WorkOrder]** Incomplete spec for 'status': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for WorkOrder.status.

**[WorkOrder]** Incomplete spec for 'priority': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for WorkOrder.priority.

**[WorkOrder]** Incomplete spec for 'description': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for WorkOrder.description.

**[User]** Incomplete spec for 'full_name': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for User.full_name.

**[User]** Incomplete spec for 'role': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for User.role.

**[User]** Incomplete spec for 'email': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for User.email.

**[User]** Incomplete spec for 'department': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for User.department.

**[User]** Incomplete spec for 'is_active': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for User.is_active.

**[Location]** Incomplete spec for 'location_name': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Location.location_name.

**[Location]** Incomplete spec for 'site': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Location.site.

**[Location]** Incomplete spec for 'building': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Location.building.

**[Location]** Incomplete spec for 'floor': missing ['validation_rule']
- Impact: Specification record is missing required contract attributes.
- Action: Manually fill ['validation_rule'] for Location.floor.
