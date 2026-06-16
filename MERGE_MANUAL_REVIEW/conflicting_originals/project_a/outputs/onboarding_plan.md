# Onboarding Plan

**Migration Readiness Score:** 40.5/100

**Silver Waves:** 2


## Bronze-Silver-Gold Pipeline

### Bronze
Raw ingest layer — all source entities are captured as-is with no wave sequencing.
**Entities:** Assets, Locations, Users
**Raw Ingest Items:**
- Assets (RAW)
- Locations (RAW)
- Users (RAW)

### Silver
Wave-sequenced transformation layer — entities are processed into CSV files in dependency order.
#### Wave 1
**Entities:** Locations, Users
**CSV Files:** D:\Onboardiq\outputs\silver\wave_01\locations.csv, D:\Onboardiq\outputs\silver\wave_01\users.csv
**Tool Stack:** Pandas
**Wave Rows:** 9
This wave groups Locations and Users entities together to ensure data consistency and resolve foreign key issues.
**Approach:** Perform a full load to CSV for both Locations and Users entities to resolve foreign key issues and ensure data consistency.
**Risk Mitigations:**
- Verify the parent_ref foreign key in Locations is correctly referenced in the downstream system.
- Validate the email foreign key in Users is correctly referenced in the downstream system.
- Perform a data quality check on Locations and Users entities to ensure no orphan records exist.
**Risks (2):**
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Unresolved FK candidate(s): ['email']
#### Wave 2
**Entities:** Assets
**CSV Files:** D:\Onboardiq\outputs\silver\wave_02\assets.csv
**Tool Stack:** Pandas
**Wave Rows:** 10
This wave focuses on Assets entity to resolve orphan records and referential integrity issues.
**Approach:** Perform a full load to CSV for the Assets entity to resolve orphan records and referential integrity issues.
**Risk Mitigations:**
- Identify and correct the invalid 'Locations.parent_ref' values referenced by orphan Assets records.
- Verify the referential integrity of Assets records by checking for valid 'Locations.parent_ref' values.
- Perform a data quality check on Assets entity to ensure no orphan records exist after correction.
**Risks (2):**
- [HIGH] 10 orphan record(s) (broken FK references)
- [MEDIUM] Referential integrity check failed: 10 orphan records reference invalid 'Locations.parent_ref' values.

### Gold
Target load layer — Silver CSV outputs are loaded into the target database.
#### Load Wave 1
**Source CSVs:** D:\Onboardiq\outputs\silver\wave_01\locations.csv, D:\Onboardiq\outputs\silver\wave_01\users.csv
**Target Entities:** Locations, Users
**Target:** target_db
**Strategy:** bulk load from Silver CSVs
#### Load Wave 2
**Source CSVs:** D:\Onboardiq\outputs\silver\wave_02\assets.csv
**Target Entities:** Assets
**Target:** target_db
**Strategy:** bulk load from Silver CSVs

## Silver Wave Detail

### Wave 1 — Locations, Users
**CSV Files:** D:\Onboardiq\outputs\silver\wave_01\locations.csv, D:\Onboardiq\outputs\silver\wave_01\users.csv
**Tool Stack:** Pandas
**Wave Rows:** 9

This wave groups Locations and Users entities together to ensure data consistency and resolve foreign key issues.

**Approach:** Perform a full load to CSV for both Locations and Users entities to resolve foreign key issues and ensure data consistency.

**Risk Mitigations:**
- Verify the parent_ref foreign key in Locations is correctly referenced in the downstream system.
- Validate the email foreign key in Users is correctly referenced in the downstream system.
- Perform a data quality check on Locations and Users entities to ensure no orphan records exist.

**Risks (2):**
- [MEDIUM] Unresolved FK candidate(s): ['parent_ref']
- [MEDIUM] Unresolved FK candidate(s): ['email']

### Wave 2 — Assets
**CSV Files:** D:\Onboardiq\outputs\silver\wave_02\assets.csv
**Tool Stack:** Pandas
**Wave Rows:** 10

This wave focuses on Assets entity to resolve orphan records and referential integrity issues.

**Approach:** Perform a full load to CSV for the Assets entity to resolve orphan records and referential integrity issues.

**Risk Mitigations:**
- Identify and correct the invalid 'Locations.parent_ref' values referenced by orphan Assets records.
- Verify the referential integrity of Assets records by checking for valid 'Locations.parent_ref' values.
- Perform a data quality check on Assets entity to ensure no orphan records exist after correction.

**Risks (2):**
- [HIGH] 10 orphan record(s) (broken FK references)
- [MEDIUM] Referential integrity check failed: 10 orphan records reference invalid 'Locations.parent_ref' values.
