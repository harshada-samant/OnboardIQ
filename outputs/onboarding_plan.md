# Onboarding Plan

**Migration Readiness Score:** 81.8/100

**Silver Waves:** 3


## Bronze-Silver-Gold Pipeline

### Bronze
Raw ingest layer — all source entities are captured as-is with no wave sequencing.
**Entities:** Users, Locations, Assets, WorkOrders
**Raw Ingest Items:**
- Users (RAW)
- Locations (RAW)
- Assets (RAW)
- WorkOrders (RAW)

### Silver
Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.
#### Wave 1
**Entities:** Users, Locations
**CSV Files:** outputs/silver/wave_01/users.csv, outputs/silver/wave_01/locations.csv
**Tool Stack:** Pandas
**Wave Rows:** 9
Establishes foundational master data by migrating Users and Locations, which serve as reference entities for downstream assets and work orders. These entities have no dependencies and must be loaded first to enable referential integrity in subsequent waves.
**Approach:** Full load to CSV with pre-migration data cleansing to resolve null emails and orphaned location records before export.
**Risk Mitigations:**
- Implement a pre-migration validation script to identify and remediate the 20% null email values in Users, either by sourcing from alternate systems or flagging for manual review
- Execute a reconciliation query to identify the 4 orphaned Locations records and either map them to valid parent locations or exclude them from migration with documented business approval
- Create a reference data validation report post-load to confirm all Locations have valid location_key values before proceeding to Wave 2
**Risks (3):**
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] 4 orphan record(s) (broken FK references)
- [MEDIUM] Referential integrity check failed: 4 orphan records reference invalid 'Locations.location_key' values.
#### Wave 2
**Entities:** Assets
**CSV Files:** outputs/silver/wave_02/assets.csv
**Tool Stack:** DuckDB, Pandas
**Wave Rows:** 10
Migrates Assets entity which depends on Locations from Wave 1, establishing the physical asset inventory that will be referenced by work orders in Wave 3. This wave focuses on asset master data with location and status attributes.
**Approach:** Full load to CSV with lookup validation against Wave 1 Locations data, applying default values for null loc_code and status fields based on business rules.
**Risk Mitigations:**
- Resolve the 1 orphaned Assets record by cross-referencing with the Locations table loaded in Wave 1, either correcting the location_key or excluding the record with business sign-off
- Define and apply business-approved default values for the 20% null loc_code and 10% null status fields, or implement a fallback location code strategy (e.g., 'UNKNOWN' placeholder)
- Execute a post-migration referential integrity check to validate all Assets.loc_code values exist in the Locations dimension before releasing to downstream systems
**Risks (4):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Locations.location_key' values.
#### Wave 3
**Entities:** WorkOrders
**CSV Files:** outputs/silver/wave_03/workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20
Completes the migration by loading WorkOrders, which depend on both Assets (Wave 2) and Users (Wave 1), representing transactional maintenance data. This wave captures the operational history and active work order lifecycle.
**Approach:** Full load to CSV with foreign key validation against Assets and Users, treating null closed_date as open work orders and filtering out orphaned records.
**Risk Mitigations:**
- Identify and resolve the 1 orphaned WorkOrders record by validating against the Assets.asset_no loaded in Wave 2, either correcting the reference or excluding with documented justification
- Establish a business rule for the 55% null closed_date values to distinguish between legitimately open work orders versus incomplete data, potentially backfilling dates from audit logs or status fields
- Implement a final end-to-end referential integrity test across all three waves to ensure WorkOrders correctly link to valid Assets and Users before production cutover
**Risks (3):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.

### Gold
Target load layer — Silver CSV outputs are loaded into the target database.
#### Load Wave 1
**Source CSVs:** outputs/silver/wave_01/users.csv, outputs/silver/wave_01/locations.csv
**Target Entities:** Users, Locations
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 2
**Source CSVs:** outputs/silver/wave_02/assets.csv
**Target Entities:** Assets
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 3
**Source CSVs:** outputs/silver/wave_03/workorders.csv
**Target Entities:** WorkOrders
**Target:** target_db
**Strategy:** bulk load from Silver CSVs

## Silver Wave Detail

### Wave 1 — Users, Locations
**CSV Files:** outputs/silver/wave_01/users.csv, outputs/silver/wave_01/locations.csv
**Tool Stack:** Pandas
**Wave Rows:** 9

Establishes foundational master data by migrating Users and Locations, which serve as reference entities for downstream assets and work orders. These entities have no dependencies and must be loaded first to enable referential integrity in subsequent waves.

**Approach:** Full load to CSV with pre-migration data cleansing to resolve null emails and orphaned location records before export.

**Risk Mitigations:**
- Implement a pre-migration validation script to identify and remediate the 20% null email values in Users, either by sourcing from alternate systems or flagging for manual review
- Execute a reconciliation query to identify the 4 orphaned Locations records and either map them to valid parent locations or exclude them from migration with documented business approval
- Create a reference data validation report post-load to confirm all Locations have valid location_key values before proceeding to Wave 2

**Risks (3):**
- [MEDIUM] Field 'email' contains high null percentage (20.0%).
- [MEDIUM] 4 orphan record(s) (broken FK references)
- [MEDIUM] Referential integrity check failed: 4 orphan records reference invalid 'Locations.location_key' values.

### Wave 2 — Assets
**CSV Files:** outputs/silver/wave_02/assets.csv
**Tool Stack:** DuckDB, Pandas
**Wave Rows:** 10

Migrates Assets entity which depends on Locations from Wave 1, establishing the physical asset inventory that will be referenced by work orders in Wave 3. This wave focuses on asset master data with location and status attributes.

**Approach:** Full load to CSV with lookup validation against Wave 1 Locations data, applying default values for null loc_code and status fields based on business rules.

**Risk Mitigations:**
- Resolve the 1 orphaned Assets record by cross-referencing with the Locations table loaded in Wave 1, either correcting the location_key or excluding the record with business sign-off
- Define and apply business-approved default values for the 20% null loc_code and 10% null status fields, or implement a fallback location code strategy (e.g., 'UNKNOWN' placeholder)
- Execute a post-migration referential integrity check to validate all Assets.loc_code values exist in the Locations dimension before releasing to downstream systems

**Risks (4):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'loc_code' contains high null percentage (20.0%).
- [MEDIUM] Field 'status' contains high null percentage (10.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Locations.location_key' values.

### Wave 3 — WorkOrders
**CSV Files:** outputs/silver/wave_03/workorders.csv
**Tool Stack:** Pandas
**Wave Rows:** 20

Completes the migration by loading WorkOrders, which depend on both Assets (Wave 2) and Users (Wave 1), representing transactional maintenance data. This wave captures the operational history and active work order lifecycle.

**Approach:** Full load to CSV with foreign key validation against Assets and Users, treating null closed_date as open work orders and filtering out orphaned records.

**Risk Mitigations:**
- Identify and resolve the 1 orphaned WorkOrders record by validating against the Assets.asset_no loaded in Wave 2, either correcting the reference or excluding with documented justification
- Establish a business rule for the 55% null closed_date values to distinguish between legitimately open work orders versus incomplete data, potentially backfilling dates from audit logs or status fields
- Implement a final end-to-end referential integrity test across all three waves to ensure WorkOrders correctly link to valid Assets and Users before production cutover

**Risks (3):**
- [MEDIUM] 1 orphan record(s) (broken FK references)
- [MEDIUM] Field 'closed_date' contains high null percentage (55.0%).
- [MEDIUM] Referential integrity check failed: 1 orphan records reference invalid 'Assets.asset_no' values.
