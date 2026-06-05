# Migration Readiness Report

## Overall Score: 81.8/100  —  Grade: B

### Sub-scores

| Dimension | Score | Weight |
|---|---|---|
| Data Quality        | 48.0%  | 35% |
| Mapping Coverage    | 100.0%  | 35% |
| Spec Completeness   | 100.0%  | 20% |
| Relationship Clarity | 100.0% | 10% |

## Risk Register

### MEDIUM (10)

**[Assets]** 1 orphan record(s) (broken FK references)
- Root Cause: Source data contains foreign key values pointing to parent records that were deleted, never migrated, or do not exist in the source system.
- Impact: Records in Assets reference parent IDs that do not exist.
- Action: Resolve missing parent records or nullify FK before loading.

**[Assets]** Field 'loc_code' contains high null percentage (20.0%).
- Root Cause: Source system allows optional location assignment or data entry processes skip this field during asset creation.
- Impact: Check type NULL_CHECK failed on field 'loc_code'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Assets]** Field 'status' contains high null percentage (10.0%).
- Root Cause: Asset status field is not consistently populated during data entry or legacy records lack status values.
- Impact: Check type NULL_CHECK failed on field 'status'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Assets]** Referential integrity check failed: 1 orphan records reference invalid 'Locations.location_key' values.
- Root Cause: Assets reference location codes that do not exist in the Locations table due to data inconsistency or missing location records.
- Impact: Check type REFERENTIAL_INTEGRITY failed on field 'loc_code'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Locations]** 4 orphan record(s) (broken FK references)
- Root Cause: Hierarchical location structure contains child locations referencing parent locations that are missing or were not migrated.
- Impact: Records in Locations reference parent IDs that do not exist.
- Action: Resolve missing parent records or nullify FK before loading.

**[Locations]** Referential integrity check failed: 4 orphan records reference invalid 'Locations.location_key' values.
- Root Cause: Self-referential parent-child location hierarchy has broken links where parent location keys are invalid or missing.
- Impact: Check type REFERENTIAL_INTEGRITY failed on field 'parent_ref'.
- Action: Review source data for this field and apply appropriate cleansing.

**[Users]** Field 'email' contains high null percentage (20.0%).
- Root Cause: User records created before email became mandatory or external/system users without email addresses in source system.
- Impact: Check type NULL_CHECK failed on field 'email'.
- Action: Review source data for this field and apply appropriate cleansing.

**[WorkOrders]** 1 orphan record(s) (broken FK references)
- Root Cause: Work orders reference parent records (assets or locations) that were deleted or excluded from migration scope.
- Impact: Records in WorkOrders reference parent IDs that do not exist.
- Action: Resolve missing parent records or nullify FK before loading.

**[WorkOrders]** Field 'closed_date' contains high null percentage (55.0%).
- Root Cause: Majority of work orders are still open or in-progress, or closed date was not historically tracked in source system.
- Impact: Check type NULL_CHECK failed on field 'closed_date'.
- Action: Review source data for this field and apply appropriate cleansing.

**[WorkOrders]** Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.
- Root Cause: Work orders link to asset numbers that do not exist in Assets table due to asset deletion or data entry errors.
- Impact: Check type REFERENTIAL_INTEGRITY failed on field 'equip_id'.
- Action: Review source data for this field and apply appropriate cleansing.
